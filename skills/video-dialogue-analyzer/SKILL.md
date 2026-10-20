---
name: video-dialogue-analyzer
description: 批量分析视频中的人机对话（如车载/智能音箱语音助手录像）：本地 faster-whisper 语音识别提取对话文本，按离线/在线、唤醒方式、具体指令结构化分类，再按摘要批量重命名视频并输出 Excel 报表。默认由 Agent 直接分类，\*\*无需 API Key、无需 ffmpeg\*\*（PyAV 内置解码）。适用于含人机对话语音的视频批量分类、重命名与归档。  
tags:
  - foxskill
---

# video-dialogue-analyzer

\---  
name: video-dialogue-analyzer  
description: 批量分析视频中的人机对话（如车载/智能音箱语音助手录像）：本地 faster-whisper 语音识别提取对话文本，按离线/在线、唤醒方式、具体指令结构化分类，再按摘要批量重命名视频并输出 Excel 报表。默认由 Agent 直接分类，\*\*无需 API Key、无需 ffmpeg\*\*（PyAV 内置解码）。适用于含人机对话语音的视频批量分类、重命名与归档。  
\---

# 视频人机对话分析与重命名 Skill

## 概述

本 Skill 对文件夹中的视频执行四步流水线：读取视频 → 语音识别提取对话 → 分类提取关键信息 → 按关键信息重命名视频。

**三条默认约定（开箱即用，不需要任何额外配置）：**

1. **分类默认由 Agent 自己完成**（`run_mode=agent`），无需 API Key、零成本。
2. **识别用 faster-whisper + 本地模型**，无需 ffmpeg（PyAV 已内置解码库）。
3. **默认预览模式**（`preview_only=True`），只算不改，确认无误后才执行真实改名。

## 依赖检查与安装（执行前必须完成）

运行本 Skill 前，Agent 必须按以下流程逐项检查依赖，缺少时提示用户确认后自动安装，**不得在依赖缺失时直接运行脚本**。

### 检查流程

按顺序执行以下检查，每一项通过后才进入下一项：

#### 1. 检查 Python 环境

```bash
python --version
```

- 要求 Python 3.8 及以上。
- 未安装时提示用户安装 Python，本 Skill 不自动安装 Python（需用户手动从 python.org 下载安装）。

#### 2. 关于 ffmpeg：**本 Skill 不需要，跳过此步** ⛔

**不要检查、也不要安装 ffmpeg。** 原因：

- 本 Skill 使用 `faster-whisper`，其依赖的 **PyAV（pip 包 `av`）自带 libavcodec / libavformat**，解码视频音频不依赖外部 ffmpeg CLI。
- 装 `faster-whisper` 时 PyAV 会作为依赖自动装上，**无需任何额外操作**。
- 国内直连下载 ffmpeg 官方静态包（gyan.dev）极慢，实测 ETA 3-4 小时，**纯属自找麻烦**。

> ⚠️ **Agent 注意**：即使本机没有 ffmpeg、PATH 里也找不到，**也不要报缺失、不要尝试安装**，直接进入下一步。  
> 只有改用 `openai-whisper`（原版、走 ffmpeg CLI 解码）时才需要，而本 Skill **不推荐**该引擎。

#### 3. 检查 Python 依赖包

逐个检查以下包是否可导入：

```bash
python -c "import faster_whisper; print('faster-whisper OK')"
python -c "import openpyxl; print('openpyxl OK')"
```

> `requests` **仅在 `run_mode=online` 时需要**。默认的 `agent` 模式无需它，不必安装。

缺少任意包时，汇总缺失列表，向用户展示并请求确认：

> 检测到缺少以下 Python 依赖包：
>
> - faster-whisper（语音识别，首次运行需下载模型文件）
> - openpyxl（Excel 报表生成）
>
> 是否现在安装？

获得用户肯定答复后执行安装。**国内网络必须用清华镜像，否则极慢**：

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple faster-whisper openpyxl
```

> **为什么用 faster-whisper 而不是 openai-whisper**
>
> - `openai-whisper` 依赖 PyTorch，Windows 下约 2GB+ 下载，CPU 推理慢。
> - `faster-whisper` 基于 CTranslate2，模型同源、识别质量相当，CPU 快数倍，安装体积小得多，且通过 PyAV 内置 FFmpeg。

安装完成后重新运行上述导入检查，全部通过后方可进入下一步。

#### 4. 检查视频文件夹

- 确认 `video_folder` 路径真实存在。
- 确认文件夹内包含至少一个匹配 `video_suffix` 的视频文件。
- 文件夹为空或不存在时直接终止并告知用户。

#### 5. 检查 AI 模式配置

- `run_mode=agent`（**默认，推荐**）：无需任何 API Key，由 Agent 按本文件的判定规则直接分类。跳过此项检查。
- `run_mode=online`：确认 `api_key` 非占位符（不以 `sk-xxxx` 开头）、`api_url`、`llm_model_name` 均已配置，且 `requests` 已安装。
- `run_mode=offline`：确认本地大模型权重文件路径存在，提示用户机器内存需 ≥ 16GB。

### 依赖检查通过后的提示

所有依赖检查通过后，向用户输出确认信息：

> 所有依赖检查通过：
>
> - Python 3.x ✓
> - faster-whisper / openpyxl ✓（**无需 ffmpeg**，PyAV 内置解码）
> - 视频文件夹：xxx（含 N 个视频）✓
> - 分类模式：agent（无需 API Key）/ online / offline ✓
>
> 当前为预览模式（preview_only=True），不会修改任何文件。是否开始执行？

获得用户确认后，才运行主脚本进入四步流水线。

## 四步执行流程

### 步骤 1：读取文件夹中的所有视频

- 遍历 `video_folder`，按 `video_suffix` 筛选视频文件（默认 `.mp4 .mkv .avi .mov`）。
- 仅获取文件名列表，不加载视频内容。
- 文件夹不存在时直接终止并报错。

### 步骤 2：对视频中的对话内容进行识别

- 加载 faster-whisper 模型：优先用 `model_dir` 指向的本地目录，否则按 `whisper_model` 从镜像下载（中文人机对话推荐 `small`）。
- 对每个视频执行语音转写，遍历 `segments` 取文本。
- 拼接所有分段文本，得到该视频的**完整人机对话字符串**。
- 无有效人声对话时标记 `status=no_speech`，跳过后续步骤，写入 Excel。

### 步骤 3：将识别到的对话内容整理，提取关键信息

输出三个字段：

| 字段               | 取值                         | 判断依据                                                            |
| ---------------- | -------------------------- | --------------------------------------------------------------- |
| `net_type`       | `离线` / `在线`                | 按下方「离线/在线 判定细则」的四条优先级判断                                         |
| `wake_type`      | `唤醒` / `免唤醒` / `oneshot唤醒` | 唤醒：独立唤醒词+设备应答后再下指令；免唤醒：无需唤醒词直接响应；oneshot唤醒：唤醒词与指令同句连续说出，无设备应答间隔 |
| `dialog_content` | 字符串                        | 从对话中提取的用户具体指令内容，用于视频文件名                                         |

三种执行方式，由 `run_mode` 决定：

| `run_mode`         | 谁来做分类                                     | 前置条件                     |
| ------------------ | ----------------------------------------- | ------------------------ |
| **`agent`（默认，推荐）** | **Agent 本人**按下方判定细则直接判断                   | 无需 API Key，零成本           |
| `online`           | 调用大模型 API（`templates/analyze_prompt.txt`） | 需 `api_key` + `requests` |
| `offline`          | 本地大模型推理                                   | 需自行接入推理函数                |

#### Agent 模式的两阶段调用（务必按此执行）

转录是全流程最耗时的部分，**不要跑两遍**。先转录、再分类、最后续跑改名：

```python
from scripts.video_dialogue_analyzer import transcribe_videos, classify_and_rename

# 阶段一：步骤1-2，拿到对话文本
cfg = {"video_folder": r"D:\videos", "model_dir": r"...\faster-whisper-small",
       "run_mode": "agent", "preview_only": True}
transcripts = transcribe_videos(cfg)

# 阶段二：Agent 阅读每个 full_dialogue，按判定细则给出分类后传回
classifications = {
    "VID_001.mp4": {"net_type": "在线", "wake_type": "唤醒", "dialog_content": "开关冷气"},
    "VID_002.mp4": {"net_type": "在线", "wake_type": "唤醒", "dialog_content": "调高空调温度"},
}
results = classify_and_rename(cfg, transcripts, classifications)
```

> `run_video_dialogue_skill(cfg)` 单次调用也支持 agent 模式，但不传 `classifications` 时  
> 只会跑到步骤 2 并把视频标为 `pending_classify`——**此时再补分类需要重新跑一遍转录**。  
> 批量处理时请直接用上面两阶段写法。

#### 离线 / 在线 判定细则（按优先级）

| 优先级 | 条件                                      | 判定   |
| --- | -------------------------------
