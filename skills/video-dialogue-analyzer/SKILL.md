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
| --- | --------------------------------------- | ---- |
| ①   | 对话明确提到"离线状态""离线模式""已切换到离线"              | `离线` |
| ②   | 助手反馈"当前网络异常""网络连接失败""请检查网络""无法连接到服务器"   | `离线` |
| ③   | 以上均无，且助手只能响应**固定模板指令**（说法稍变即拒识、或反复答非所问） | `离线` |
| ④   | 以上均无，助手全程正常响应，且能理解**间接/模糊/多样**的口语表达     | `在线` |

**核心原则：举证责任在「离线」一方。** 必须存在**正面证据**才判 `离线`；若无任何离线信号，一律默认 `在线`。

> ⚠️ **常见误判（务必避免）**：不要用"对话里没有查天气/搜索/翻译"来判离线。  
> 这是**诉诸无知的逻辑错误**——没有云端查询的证据，不等于设备离线的证据。  
> 设备处于在线状态时，照样可以执行本地硬件控制（车控空调、开灯、关窗等）。  
> **网络状态 ≠ 命令的执行位置**，二者是正交维度，不可混为一谈。

判定 `在线` 的关键信号（具备其一即可，说明助手正在使用云端语义理解）：

- **从环境描述 / 间接表达推断意图**：如 `"车里太闷了，打开冷气"` → 助手推断出要开空调（用户并未说出"开空调"）。
- **把模糊口语映射为具体模式**：如 `"降降温"` → 助手执行"急速降温"。
- **同义说法归一**：如 `"调低冷气"` / `"温度往上调一调"` / `"升一度"` 被识别为同一意图。

这类能力来自云端大模型，纯离线的固定模板匹配做不到。

本步骤的异常分支（均跳过改名，但仍写入 Excel 保留对话原文）：

| 情况                               | `status`           |
| -------------------------------- | ------------------ |
| `online` 模式：API 调用失败 / JSON 解析异常 | `ai_fail`          |
| `agent` 模式：未提供该视频的分类结果           | `pending_classify` |

> 完整 Prompt 模板见 `templates/analyze_prompt.txt`（**仅 `online` / `offline` 模式使用**）；  
> 字段类型、状态枚举与两阶段函数签名见 `references/api-spec.md`。

### 步骤 4：按照提取的关键信息对视频文件进行重命名

1. 文件名拼接格式：`{net_type}-{wake_type}-{dialog_content}`，例如 `在线-唤醒-开关冷气`。
   > 注意：示例用「在线」而非「离线」——判 `离线` 需要正面证据，详见步骤 3 的判定细则。
2. 每个字段分别清洗 Windows 非法字符（`\ / : * ? " < > |` 及换行制表符），空值字段自动跳过。
3. 拼接后按 `max_filename_len` 截断总长度（默认 30 字符）。
4. 拼接原视频扩展名，生成新文件名。
5. 重名冲突时自动追加 `_1`、`_2` 后缀，防止覆盖。
6. **安全分支**：
   - `preview_only=True`（默认）：仅计算并打印预期新文件名，**不执行 `os.rename`**。
   - `preview_only=False`：执行真实磁盘重命名。

## 输出产物

### 1. 结构化结果列表（内存返回）

每个视频对应一个结果对象，字段定义见 `references/api-spec.md`。

### 2. Excel 报表

`export_excel=True` 时，在视频文件夹输出 `视频人机对话分析结果.xlsx`，列包括：

原文件名 | 完整对话 | 离线/在线 | 唤醒类型 | 具体指令 | 新文件名 | 处理状态

## 使用方式

### 直接运行脚本

```bash
python scripts/video_dialogue_analyzer.py
```

运行前修改脚本顶部 `SKILL_CONFIG` 字典中的参数。**首次务必保持 `preview_only=True`**，确认 Excel 结果符合预期后再改为 `False` 执行真实改名。

### 作为模块导入（agent 模式，推荐）

```python
from scripts.video_dialogue_analyzer import transcribe_videos, classify_and_rename

config = {
    "video_folder": r"D:\videos",
    "model_dir": r"C:\Users\Gordon\.workbuddy\binaries\faster-whisper-small",  # 跳过下载
    "run_mode": "agent",       # Agent 自己分类，无需 API Key
    "preview_only": True,
}

# 阶段一：转录
transcripts = transcribe_videos(config)

# 阶段二：Agent 分类后传回（键为原文件名）
classifications = {
    t["src_filename"]: {"net_type": "在线", "wake_type": "唤醒", "dialog_content": "开关冷气"}
    for t in transcripts if t["status"] == "success"
}
results = classify_and_rename(config, transcripts, classifications)
```

## 已验证的本地运行环境

以下路径在本机已实测跑通，可直接复用，**不要重复安装**：

| 项目          | 路径 / 值                                                                       |
| ----------- | ---------------------------------------------------------------------------- |
| Python venv | `C:\Users\Gordon\.workbuddy\binaries\python\envs\default`                    |
| venv 解释器    | `C:\Users\Gordon\.workbuddy\binaries\python\envs\default\Scripts\python.exe` |
| 已装包         | faster-whisper、openpyxl、requests、PyAV(av 18.1.0)                             |
| 本地模型目录      | `C:\Users\Gordon\.workbuddy\binaries\faster-whisper-small`                   |

**直接用这个解释器跑，并把 `model_dir` 指向本地模型**，即可完全离线、免下载：

```python
config = {
    "video_folder": r"C:\Users\Gordon\Desktop\test",
    "model_dir": r"C:\Users\Gordon\.workbuddy\binaries\faster-whisper-small",
    "run_mode": "agent",
    "preview_only": True,
}

## 配置参数

| 参数                 | 类型    | 默认值                     | 说明                                                    |
| ------------------ | ----- | ----------------------- | ----------------------------------------------------- |
| `video_folder`     | str   | 必填                      | 视频文件夹绝对路径                                             |
| `whisper_model`    | str   | `small`                 | faster-whisper 模型：tiny/base/small/medium              |
| `model_dir`        | str   | 空                       | 本地模型目录绝对路径；非空时直接加载，**跳过联网下载**（推荐，见下方注意事项）             |
| `device`           | str   | `cpu`                   | 推理设备：`cpu` / `cuda`（有 NVIDIA 显卡时用 cuda 大幅加速）          |
| `compute_type`     | str   | `int8`                  | 推理精度：CPU 用 `int8`（推荐）；cuda 可用 `float16`               |
| `hf_endpoint`      | str   | `https://hf-mirror.com` | HuggingFace 镜像地址，国内网络必配                               |
| `language`         | str   | `zh`                    | 语音识别语言                                                |
| `preview_only`     | bool  | `True`                  | 预览模式，不修改文件                                            |
| `export_excel`     | bool  | `True`                  | 是否输出 Excel 报表                                         |
| `max_filename_len` | int   | `30`                    | 生成文件名最大字符数                                            |
| `run_mode`         | str   | `agent`                 | 分类方式：`agent`（Agent 直接分类，无需 Key）/ `online` / `offline` |
| `api_key`          | str   | 占位符                     | 大模型 API Key，**仅 `online` 模式需要**                       |
| `api_url`          | str   | 火山方舟地址                  | 兼容 OpenAI 格式的接口地址，**仅 `online` 模式**                   |
| `llm_model_name`   | str   | `doubao-pro-4k`         | 大模型名称，**仅 `online` 模式**                               |
| `video_suffix`     | tuple | `.mp4 .mkv .avi .mov`   | 支持的视频后缀                                               |

## 分类模式说明

- **`run_mode=agent`（默认）**：步骤 3 由 Agent 按本文「离线/在线 判定细则」直接判断，**不需要 API Key，也没有额外成本**。实测质量不输 API——因为判定依赖的是对对话语义的理解，而这正是 Agent 的强项。
- **`run_mode=online`**：调用火山方舟 doubao 等兼容 OpenAI 格式的接口，Prompt 见 `templates/analyze_prompt.txt`。需配置 `api_key` 并安装 `requests`。
- **`run_mode=offline`**：替换为本地大模型推理（如 Qwen 量化模型 via llama-cpp-python 或 transformers）。输入（对话文本 + Prompt）和输出（JSON 结构）与前两者完全一致，仅推理函数不同，步骤 1、2、4 及 Excel 输出逻辑无需改动。

## 注意事项

- Whisper 语音识别可能产生错别字，直接影响分类和文件名质量。唤醒词、助手自称最容易被误识（实测出现过"看一晚""智能"这类错字），判读时优先看**对话结构**（唤醒→应答→指令）而非个别词面。
- 视频开头静音或纯背景音乐时，识别文本可能为空，标记为 `no_speech`。
- faster-whisper 在 CPU 上已足够快（实测 `small` 模型处理 147 秒音频约 1 分钟）；有 NVIDIA 显卡可用 `device="cuda"` + `compute_type="float16"` 进一步加速。
- 建议先用 2-3 个视频复制到测试文件夹验证全流程，再批量处理原始视频。
- 批量处理时用 `transcribe_videos` → `classify_and_rename` 两阶段写法，**避免重复转录**。

### 国内网络下载模型的两个必备配置

首次运行需从 HuggingFace 下载模型（如 `small` 约 483MB）。国内网络必须同时做两件事，否则会失败：
```


```python
import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # 走国内镜像
os.environ["HF_HUB_DISABLE_XET"] = "1"                          # 关键：禁用 Xet 协议
```

- **不禁用 Xet 会报 `401 Unauthorized`**：hf-mirror 不支持 Xet 协议，请求仍会打到 `cas-server.xethub.hf.co` 被拒。
- **禁用 Xet 后可能报 `model.bin is incomplete`**：这是 Windows 下 HF 缓存目录的**快照符号链接失效**导致的，blob 本体通常已完整下载（可用 Content-Length 比对确认），不是文件损坏。

**推荐做法：把模型落到本地目录，一劳永逸。** 从 HF 缓存的 `blobs/` 里把文件按原名复制出来即可，避免重复下载几百 MB：

```bash
# 缓存路径：~/.cache/huggingface/hub/models--Systran--faster-whisper-<size>/blobs/
mkdir -p ~/.workbuddy/binaries/faster-whisper-small
cp <blob_model.bin>      ~/.workbuddy/binaries/faster-whisper-small/model.bin
cp <blob_tokenizer.json> ~/.workbuddy/binaries/faster-whisper-small/tokenizer.json
cp <blob_vocab.txt>      ~/.workbuddy/binaries/faster-whisper-small/vocabulary.txt
cp <blob_config.json>    ~/.workbuddy/binaries/faster-whisper-small/config.json
```

随后在配置里指定 `model_dir` 为该目录，即可完全跳过联网下载。
