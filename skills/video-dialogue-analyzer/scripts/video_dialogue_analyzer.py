#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频人机对话分析与重命名 Skill 主脚本

四步流水线：
  步骤1：读取文件夹中的所有视频
  步骤2：对视频中的对话内容进行语音识别
  步骤3：将识别到的对话内容进行 AI 整理，提取关键信息
  步骤4：按照提取的关键信息对视频文件进行重命名

三种 run_mode：
  · agent   （默认，推荐）脚本只跑步骤1-2，把对话文本交回 Agent，
              Agent 按 SKILL.md 的判定规则直接分类，再把结果传回脚本完成步骤3-4。
              无需任何 API Key，零成本。
  · online  调用兼容 OpenAI 格式的大模型 API（需 api_key）。
  · offline 接入本地大模型（需自行实现推理函数）。

两阶段 API（供 Agent 模式使用）：
  transcripts = transcribe_videos(cfg)                      # 步骤1-2
  results     = classify_and_rename(cfg, transcripts, cls)  # 步骤3-4 + Excel

用法：
  python video_dialogue_analyzer.py
  （运行前修改下方 SKILL_CONFIG 配置）
"""

import os
import re
import json
import sys
import importlib
from typing import List, Dict, Optional

# ===================== Skill 配置参数 =====================
SKILL_CONFIG = {
    "video_folder": r"D:\video_test",
    "whisper_model": "small",
    "model_dir": "",               # 本地模型目录绝对路径；非空则直接加载，跳过联网下载
    "device": "cpu",               # 推理设备：cpu / cuda（有 N 卡时用 cuda 大幅加速）
    "compute_type": "int8",        # 推理精度：CPU 用 int8（推荐）；cuda 可用 float16
    "hf_endpoint": "https://hf-mirror.com",  # HuggingFace 镜像，国内网络必配
    "language": "zh",
    "preview_only": True,          # True=仅预览不改名；确认结果后改为False执行重命名
    "export_excel": True,
    "max_filename_len": 30,
    "run_mode": "agent",           # agent / online / offline（默认 agent，无需 API Key）
    "api_key": "sk-xxxxxxxxxxxxxxxxxxxx",   # 仅 run_mode=online 时需要
    "api_url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    "llm_model_name": "doubao-pro-4k",
    "video_suffix": (".mp4", ".mkv", ".avi", ".mov")
}
# ==========================================================

# AI 分析 Prompt 模板（run_mode=online / offline 时使用；run_mode=agent 时由 Agent 依同一规则判断）
LLM_ANALYZE_PROMPT = """你是人机对话场景分析专家。阅读下面完整人机对话记录，严格输出JSON，不要多余解释。
提取以下信息：
1. net_type：["离线","在线"]
   判断优先级：
   （1）对话中明确提到"离线状态""离线模式""已切换到离线"等提示 → 离线；
   （2）助手回复"当前网络异常""网络连接失败""请检查网络""无法连接到服务器"等 → 离线；
   （3）以上均无，且助手只能响应固定模板指令（说法稍变即拒识、反复答非所问） → 离线；
   （4）以上均无，助手全程正常响应，且能理解间接/模糊/多样的口语表达 → 在线。
   核心原则：举证责任在"离线"一方，必须有正面证据才判离线；无任何离线信号时默认判在线。
   特别注意：不得因为"对话里没有查天气/搜索/翻译"就判离线——这是逻辑错误。
   设备在线时同样可以执行本地硬件控制（车控空调、开灯、关窗等），网络状态不等于命令的执行位置。
   判定"在线"的关键信号（具备其一即可）：
     · 从环境描述或间接表达推断意图，如"车里太闷了，打开冷气"→助手推断出要开空调（用户并未说出"开空调"）；
     · 把模糊口语映射为具体模式，如"降降温"→助手执行"急速降温"；
     · 同义说法归一，如"调低冷气"/"温度往上调一调"/"升一度"被识别为同一意图。
   这类能力来自云端大模型，纯离线的固定模板匹配做不到。
2. wake_type：["唤醒","免唤醒","oneshot唤醒"]
   唤醒：对话中出现独立的唤醒词（如"小度小度""你好小度"），设备应答后用户再下达指令；
   免唤醒：无需唤醒词，设备直接接收并响应指令；
   oneshot唤醒：唤醒词与指令在同一句话中连续说出（如"小度小度打开灯"），中间没有设备应答间隔。
3. dialog_content：字符串，从对话中提取用户下达的具体指令内容（去掉唤醒词、寒暄、设备应答），简洁明确，用于视频文件名。

输出示例：
{{"net_type":"在线","wake_type":"唤醒","dialog_content":"打开客厅的灯"}}

对话内容：
{dialog_content}
"""


def check_dependencies(cfg: Optional[Dict] = None) -> bool:
    """
    启动时依赖自检：检查 Python 第三方包。

    注意：本 Skill **不需要独立 ffmpeg CLI**。
    faster-whisper 依赖的 PyAV 自带 libavcodec / libavformat，解码不依赖外部 ffmpeg，
    因此这里不做 ffmpeg 检查，也不要去下载 ffmpeg 静态包（国内直连极慢）。

    requests 仅在 run_mode=online 时需要。
    """
    run_mode = (cfg or {}).get("run_mode", "agent")

    required_pkgs = {
        "faster_whisper": "faster-whisper",
        "openpyxl": "openpyxl",
    }
    if run_mode == "online":
        required_pkgs["requests"] = "requests"

    missing_pkgs = []
    for module_name, pip_name in required_pkgs.items():
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing_pkgs.append(pip_name)

    if missing_pkgs:
        print("=" * 60)
        print("依赖检查未通过，缺少以下 Python 包：")
        print("=" * 60)
        print("  " + ", ".join(missing_pkgs))
        print()
        print("安装命令（国内网络务必加清华镜像，否则极慢）：")
        print(f"  pip install -i https://pypi.tuna.tsinghua.edu.cn/simple {' '.join(missing_pkgs)}")
        print()
        print("提示：本 Skill 不需要安装 ffmpeg —— PyAV 已内置解码库。")
        print("=" * 60)
        return False

    extra = "requests, " if run_mode == "online" else ""
    print(f"[依赖检查] faster-whisper, {extra}openpyxl 全部就绪"
          f"（无需 ffmpeg，PyAV 内置解码）\n")
    return True


def sanitize_filename(text: str, max_len: int) -> str:
    """清洗 Windows 文件名非法字符并截断长度"""
    bad_chars = r'[\\/:*?"<>|\n\r\t]'
    text = re.sub(bad_chars, "", text).strip()
    return text[:max_len]


def _setup_env_and_imports(cfg: Dict):
    """
    设置 HF 镜像环境变量并导入第三方包。
    国内网络下载模型的两个必备配置：走镜像 + 禁用 Xet 协议。
    不禁用 Xet 会绕开镜像直连 cas-server.xethub.hf.co，导致 401 Unauthorized。
    """
    os.environ.setdefault("HF_ENDPOINT", cfg.get("hf_endpoint", "https://hf-mirror.com"))
    os.environ["HF_HUB_DISABLE_XET"] = "1"

    from faster_whisper import WhisperModel
    from openpyxl import Workbook
    return WhisperModel, Workbook


# ===================== 阶段一：步骤1 + 步骤2 =====================

def transcribe_videos(cfg: Dict) -> List[Dict]:
    """
    步骤1：读取文件夹中的所有视频
    步骤2：对视频中的对话内容进行语音识别

    返回转录结果列表（每个视频一项）。此时 status 为 success / no_speech，
    分类字段（net_type / wake_type / dialog_content）尚未填充。
    """
    if not os.path.isdir(cfg["video_folder"]):
        raise FileNotFoundError(f"视频文件夹不存在：{cfg['video_folder']}")

    WhisperModel, _ = _setup_env_and_imports(cfg)

    # -------- 步骤1：读取文件夹中的所有视频 --------
    print("=" * 60)
    print("【步骤1】读取文件夹中的所有视频")
    print("=" * 60)
    file_list = [
        f for f in os.listdir(cfg["video_folder"])
        if f.lower().endswith(cfg["video_suffix"])
    ]
    print(f"步骤1完成，共读取 {len(file_list)} 个视频文件\n")

    if not file_list:
        print("文件夹中没有匹配的视频文件，流程结束。")
        return []

    # 加载 faster-whisper 模型：优先用 model_dir 指向的本地目录，跳过联网下载
    model_src = cfg.get("model_dir") or cfg["whisper_model"]
    print(f"加载 faster-whisper 模型 [{model_src}] ...")
    whisper_model = WhisperModel(
        model_src,
        device=cfg.get("device", "cpu"),
        compute_type=cfg.get("compute_type", "int8"),
    )
    print("模型加载完成\n")

    transcripts: List[Dict] = []

    for idx, fname in enumerate(file_list, 1):
        full_video_path = os.path.join(cfg["video_folder"], fname)
        item = {
            "src_filename": fname,
            "full_dialogue": "",
            "net_type": "",
            "wake_type": "",
            "dialog_content": "",
            "expect_new_filename": "",
            "status": "success",
            "error_msg": ""
        }

        print(f"--- [{idx}/{len(file_list)}] 处理：{fname} ---")
        print("【步骤2】语音识别提取对话内容...")
        try:
            # faster-whisper 返回 (generator, info)，需遍历取 seg.text
            segments_iter, _info = whisper_model.transcribe(
                full_video_path,
                language=cfg["language"],
                beam_size=5
            )
            full_dialog = "\n".join(
                [seg.text.strip() for seg in segments_iter if seg.text.strip()]
            )
            item["full_dialogue"] = full_dialog

            if not full_dialog.strip():
                item["status"] = "no_speech"
                print("步骤2：未识别到有效人声对话，跳过后续步骤\n")
            else:
                print(f"步骤2完成，识别到 {len(full_dialog)} 字符对话")
                if len(full_dialog) > 200:
                    print(f"  对话预览：{full_dialog[:200]}...")
                else:
                    print(f"  对话内容：{full_dialog}")
                print()
        except Exception as e:
            item["status"] = "error"
            item["error_msg"] = str(e)
            print(f"步骤2处理异常：{e}\n")

        transcripts.append(item)

    return transcripts


# ===================== 步骤3：分类 =====================

def _ai_online(dialog_text: str, cfg: Dict) -> Optional[Dict]:
    """在线 API 模式：调用兼容 OpenAI 格式的大模型接口"""
    # 必须在本函数内导入：模块级函数访问不到其他函数内的局部 import，否则抛 NameError。
    import requests

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": cfg["llm_model_name"],
        "temperature": 0,
        "messages": [
            {"role": "user", "content": LLM_ANALYZE_PROMPT.format(dialog_content=dialog_text)}
        ]
    }
    try:
        resp = requests.post(cfg["api_url"], json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        js = resp.json()
        raw = js["choices"][0]["message"]["content"].strip()
        # 提取 JSON 部分（兼容 AI 输出前后有多余文字的情况）
        s = raw.find("{")
        e = raw.rfind("}") + 1
        if s == -1 or e == 0:
            print(f"[步骤3] AI 输出未包含JSON: {raw[:200]}")
            return None
        return json.loads(raw[s:e])
    except Exception as e:
        print(f"[步骤3 AI提取失败] {e}")
        return None


def step3_ai_extract_keyinfo(dialog_text: str, cfg: Dict) -> Optional[Dict]:
    """
    步骤3：将识别到的对话内容进行 AI 整理，提取关键信息
    online  → 调大模型 API
    offline → 本地大模型（需自行接入推理函数）
    agent   → 不由本函数处理，由 Agent 依 SKILL.md 规则直接判断后传入
    """
    if cfg["run_mode"] == "online":
        return _ai_online(dialog_text, cfg)
    elif cfg["run_mode"] == "offline":
        raise NotImplementedError(
            "离线模式未实现：请在 step3_ai_extract_keyinfo 中接入本地大模型推理，"
            "输入为对话文本+Prompt，输出为包含 net_type/wake_type/dialog_content 的 JSON dict"
        )
    else:
        raise ValueError(
            f"run_mode={cfg['run_mode']} 不走 API 分类。"
            "agent 模式请将分类结果通过 classify_and_rename(cfg, transcripts, classifications) 传入。"
        )


# ===================== 阶段二：步骤3注入 + 步骤4 + Excel =====================

def classify_and_rename(cfg: Dict,
                        transcripts: List[Dict],
                        classifications: Optional[Dict[str, Dict]] = None) -> List[Dict]:
    """
    步骤3：注入分类结果（agent 模式由 Agent 提供；online 模式此处现场调 API）
    步骤4：按照提取的关键信息对视频文件进行重命名，并输出 Excel 报表

    classifications 格式（agent 模式，键为**原文件名**）：
        {"VID_001.mp4": {"net_type": "在线", "wake_type": "唤醒", "dialog_content": "开关冷气"}}
    """
    _, Workbook = _setup_env_and_imports(cfg)
    classifications = classifications or {}

    wb = Workbook()
    ws = wb.active
    ws.append([
        "原文件名", "完整对话", "离线/在线", "唤醒类型",
        "具体指令", "新文件名", "处理状态"
    ])

    result_list: List[Dict] = []

    for idx, item in enumerate(transcripts, 1):
        fname = item["src_filename"]

        # 无法分类的（无对话 / 转写异常）直接落表
        if item["status"] != "success":
            ws.append([fname, item["full_dialogue"], "", "", "", "",
                       "无有效对话" if item["status"] == "no_speech" else f"异常：{item['error_msg']}"])
            result_list.append(item)
            continue

        print(f"--- [{idx}/{len(transcripts)}] 分类并命名：{fname} ---")

        # -------- 步骤3：提取关键信息 --------
        print("【步骤3】提取关键信息...")
        if cfg.get("run_mode", "agent") == "agent":
            ai_info = classifications.get(fname)
            if not ai_info:
                item["status"] = "pending_classify"
                ws.append([fname, item["full_dialogue"], "", "", "", "", "待Agent分类"])
                result_list.append(item)
                print("步骤3：未提供分类结果，跳过改名\n")
                continue
        else:
            ai_info = step3_ai_extract_keyinfo(item["full_dialogue"], cfg)
            if not ai_info:
                item["status"] = "ai_fail"
                ws.append([fname, item["full_dialogue"], "", "", "", "", "AI解析失败"])
                result_list.append(item)
                print("步骤3：AI提取失败，跳过改名\n")
                continue

        item["net_type"] = ai_info.get("net_type", "")
        item["wake_type"] = ai_info.get("wake_type", "")
        item["dialog_content"] = ai_info.get("dialog_content", "")

        print("步骤3完成：")
        print(f"  离线/在线：{item['net_type']}")
        print(f"  唤醒/免唤醒：{item['wake_type']}")
        print(f"  具体指令：{item['dialog_content']}")

        # -------- 步骤4：重命名 --------
        print("【步骤4】按分类+指令生成新文件名...")
        # 文件名格式：net_type-wake_type-dialog_content，如"在线-唤醒-开关冷气"
        name_parts = [
            sanitize_filename(item["net_type"], 10),
            sanitize_filename(item["wake_type"], 10),
            sanitize_filename(item["dialog_content"], cfg["max_filename_len"])
        ]
        base_name = "-".join([p for p in name_parts if p])  # 过滤空值后拼接
        base_name = base_name[:cfg["max_filename_len"]]
        ext = os.path.splitext(fname)[1]
        new_name = base_name + ext
        new_full_path = os.path.join(cfg["video_folder"], new_name)

        # 处理重名冲突
        counter = 1
        while os.path.exists(new_full_path):
            new_name = f"{base_name}_{counter}{ext}"
            new_full_path = os.path.join(cfg["video_folder"], new_name)
            counter += 1

        item["expect_new_filename"] = new_name

        if not cfg["preview_only"]:
            src_path = os.path.join(cfg["video_folder"], fname)
            os.rename(src_path, new_full_path)
            print(f"步骤4完成：已重命名为 [{new_name}]\n")
        else:
            print(f"步骤4完成（预览模式）：预期新文件名 [{new_name}]，文件未修改\n")

        ws.append([
            fname, item["full_dialogue"],
            item["net_type"], item["wake_type"], item["dialog_content"],
            new_name, "处理成功"
        ])
        result_list.append(item)

    # -------- 输出 Excel 报表 --------
    if cfg["export_excel"]:
        excel_save_path = os.path.join(cfg["video_folder"], "视频人机对话分析结果.xlsx")
        wb.save(excel_save_path)
        print(f"✅ Excel 分析报表已保存：{excel_save_path}")

    _print_summary(result_list, cfg)
    return result_list


def _print_summary(result_list: List[Dict], cfg: Dict) -> None:
    """打印处理汇总统计"""
    total = len(result_list)
    success = sum(1 for r in result_list if r["status"] == "success")
    no_speech = sum(1 for r in result_list if r["status"] == "no_speech")
    ai_fail = sum(1 for r in result_list if r["status"] == "ai_fail")
    pending = sum(1 for r in result_list if r["status"] == "pending_classify")
    error = sum(1 for r in result_list if r["status"] == "error")

    print("\n" + "=" * 60)
    print("处理完成汇总")
    print("=" * 60)
    print(f"  总计：{total}")
    print(f"  成功：{success}")
    print(f"  无对话：{no_speech}")
    print(f"  AI失败：{ai_fail}")
    print(f"  待分类：{pending}")
    print(f"  异常：{error}")
    if cfg["preview_only"]:
        print("\n  ⚠️ 当前为预览模式，视频文件未被修改。")
        print("  确认结果无误后，将 preview_only 改为 False 再次运行即可执行真实改名。")
    print("=" * 60)


# ===================== 主入口 =====================

def run_video_dialogue_skill(cfg: Dict,
                             classifications: Optional[Dict[str, Dict]] = None
                             ) -> List[Dict]:
    """
    主入口：一次性执行完整四步流水线，返回每个视频的结构化结果列表。

    agent 模式（默认）下若不传 classifications，则只完成步骤1-2，
    所有可分类视频标记为 pending_classify，由 Agent 分类后再调用
    classify_and_rename(cfg, transcripts, classifications) 续跑步骤3-4，
    避免重复转录（转录是全流程最耗时的部分）。
    """
    transcripts = transcribe_videos(cfg)

    if not transcripts:
        return []

    if cfg.get("run_mode", "agent") == "agent" and not classifications:
        print("\n[agent 模式] 步骤1-2 已完成，等待 Agent 提供分类结果。\n")
        for t in transcripts:
            if t["status"] == "success":
                print(f"■ {t['src_filename']}")
                print(f"{t['full_dialogue']}\n")
        return transcripts

    return classify_and_rename(cfg, transcripts, classifications)


if __name__ == "__main__":
    # 启动时先执行依赖自检，未通过则退出
    if not check_dependencies(SKILL_CONFIG):
        sys.exit(1)
    output_results = run_video_dialogue_skill(SKILL_CONFIG)
