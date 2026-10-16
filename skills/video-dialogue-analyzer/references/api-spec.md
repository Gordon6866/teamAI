# API 规范与字段定义

## 1. 输入配置（SKILL_CONFIG）

| 字段名 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `video_folder` | `str` | 是 | — | 视频文件夹绝对路径，必须真实存在 |
| `whisper_model` | `str` | 否 | `"small"` | faster-whisper 模型大小，可选 `tiny`/`base`/`small`/`medium`/`large` |
| `model_dir` | `str` | 否 | `""` | 本地模型目录绝对路径；非空时直接加载，**跳过联网下载** |
| `device` | `str` | 否 | `"cpu"` | 推理设备：`cpu` / `cuda`（有 NVIDIA 显卡时用 cuda 大幅加速） |
| `compute_type` | `str` | 否 | `"int8"` | 推理精度：CPU 用 `int8`（推荐）；cuda 可用 `float16` |
| `hf_endpoint` | `str` | 否 | `"https://hf-mirror.com"` | HuggingFace 镜像地址，国内网络必配 |
| `language` | `str` | 否 | `"zh"` | 语音识别语言代码 |
| `preview_only` | `bool` | 否 | `True` | 预览模式：True 仅计算不改名；False 执行真实重命名 |
| `export_excel` | `bool` | 否 | `True` | 是否输出 Excel 分析报表 |
| `max_filename_len` | `int` | 否 | `30` | 生成文件名的最大字符数（汉字计 1 字符） |
| `run_mode` | `str` | 否 | `"agent"` | 分类方式：`agent`（Agent 直接分类，无需 Key）/ `online`（在线 API）/ `offline`（本地大模型） |
| `api_key` | `str` | `online` 时必填 | 占位符 | 大模型服务的 API Key，仅 `online` 模式需要 |
| `api_url` | `str` | 否 | 火山方舟默认地址 | 兼容 OpenAI Chat Completions 格式的接口 URL，仅 `online` 模式 |
| `llm_model_name` | `str` | 否 | `"doubao-pro-4k"` | 调用的大模型名称，仅 `online` 模式 |
| `video_suffix` | `tuple[str]` | 否 | `(".mp4", ".mkv", ".avi", ".mov")` | 待处理视频的文件后缀白名单 |

> **ffmpeg 不在配置表中，也不需要。** faster-whisper 依赖的 PyAV 自带 libavcodec / libavformat，
> 音频解码不依赖外部 ffmpeg CLI。

## 2. 分类输出（步骤 3 返回值）

无论 `run_mode` 取何值，步骤 3 的输出结构一致，包含以下三个字段：

| 字段名 | 类型 | 取值范围 | 说明 |
|---|---|---|---|
| `net_type` | `str` | `"离线"` \| `"在线"` | 对话依赖的能力运行位置，判断优先级见下方细则 |
| `wake_type` | `str` | `"唤醒"` \| `"免唤醒"` \| `"oneshot唤醒"` | 设备响应指令的唤醒模式 |
| `dialog_content` | `str` | 任意非空字符串 | 从对话中提取的用户具体指令内容，将与 net_type、wake_type 拼接用作视频文件名 |

### 字段判断细则

**net_type（离线 / 在线）—— 按优先级判断**

1. 对话中明确提到"离线状态""离线模式""已切换到离线""当前处于离线"等提示语 → `离线`。
2. 助手回复"当前网络异常""网络连接失败""请检查网络连接""无法连接到服务器"等类似表达 → `离线`。
3. 助手只能响应**固定模板指令**（说法稍变即拒识、反复答非所问） → `离线`。
4. 以上均无，助手全程正常响应，且能理解**间接 / 模糊 / 多样**的口语表达 → `在线`。

**核心原则：举证责任在「离线」一方。** 必须存在**正面证据**才判 `离线`；若无任何离线信号，一律默认 `在线`。

> ⚠️ **常见误判（务必避免）**：不得用"对话里没有查天气 / 搜索 / 翻译"来判离线。
> 这是**诉诸无知的逻辑错误**——没有云端查询的证据，不等于设备离线的证据。
> 设备在线时同样可以执行本地硬件控制（车控空调、开灯、关窗等）。
> **网络状态 ≠ 命令的执行位置**，二者正交，不可混为一谈。

判定 `在线` 的关键信号（具备其一即可，说明助手正在使用云端语义理解）：

- **从环境描述 / 间接表达推断意图**：`"车里太闷了，打开冷气"` → 助手推断出要开空调（用户并未说出"开空调"）。
- **把模糊口语映射为具体模式**：`"降降温"` → 助手执行"急速降温"。
- **同义说法归一**：`"调低冷气"` / `"温度往上调一调"` / `"升一度"` 被识别为同一意图。

这类能力来自云端大模型，纯离线的固定模板匹配做不到。

**wake_type（唤醒 / 免唤醒 / oneshot唤醒）**

- `唤醒`：对话中出现独立的唤醒词（如"小度小度""你好小度""小爱同学"），设备先应答（如"在呢""我在"），用户随后再下达指令。唤醒词与指令之间有设备应答间隔。
- `免唤醒`：设备无需唤醒词，直接接收并响应指令。通常出现在持续监听场景或已唤醒后的连续交互中。
- `oneshot唤醒`：唤醒词与指令在同一句话中连续说出（如"小度小度打开客厅的灯""小爱同学今天天气怎么样"），中间没有设备应答间隔，一句话同时完成唤醒和指令下达。

**dialog_content（对话中的具体指令）**
- 从完整人机对话中提取用户下达的具体指令内容，去掉唤醒词、寒暄、设备应答等无关部分。
- 要求简洁明确，能直接反映用户意图，例如"打开客厅的灯"、"查询今天北京天气"、"设置明天早上7点闹钟"。
- 该字段将与 net_type、wake_type 拼接为视频文件名，格式为 `net_type-wake_type-dialog_content`。

## 3. 单视频处理结果（步骤 4 输出对象）

```json
{
  "src_filename": "原视频文件名.mp4",
  "full_dialogue": "Whisper 提取的完整对话文本，含换行分段",
  "net_type": "在线",
  "wake_type": "唤醒",
  "dialog_content": "打开客厅的灯",
  "expect_new_filename": "在线-唤醒-打开客厅的灯.mp4",
  "status": "success",
  "error_msg": ""
}
```

| 字段名 | 类型 | 说明 |
|---|---|---|
| `src_filename` | `str` | 原始视频文件名 |
| `full_dialogue` | `str` | Whisper 提取的完整对话文本，无对话时为空字符串 |
| `net_type` | `str` | 分类结果，失败时为空 |
| `wake_type` | `str` | 分类结果，失败时为空 |
| `dialog_content` | `str` | 提取的用户具体指令内容，失败时为空 |
| `expect_new_filename` | `str` | 预期或实际的新文件名（预览模式下为预期值） |
| `status` | `str` | 处理状态：`success` / `no_speech` / `ai_fail` / `pending_classify` / `error` |
| `error_msg` | `str` | 异常详情，正常时为空字符串 |

### status 状态说明

| 状态 | 含义 | 后续处理 |
|---|---|---|
| `success` | 全流程成功，已生成新文件名（预览或已改名） | 正常记录 |
| `no_speech` | 步骤 2 未识别到有效人声对话 | 跳过分类和改名 |
| `ai_fail` | `online` 模式下 AI 调用失败或 JSON 解析异常 | 跳过改名，记录原始对话 |
| `pending_classify` | `agent` 模式下尚未提供分类结果 | 补齐 `classifications` 后重跑 `classify_and_rename` |
| `error` | 任意步骤抛出未捕获异常 | 记录错误信息 |

## 3.1 两阶段函数接口（`agent` 模式专用）

转录是最耗时环节，批量处理务必用两阶段写法避免重复转录。

```python
def transcribe_videos(cfg: Dict) -> List[Dict]:
    """步骤 1-2：读取视频 + 语音识别。返回转录列表，分类字段为空，status=success/no_speech/error。"""

def classify_and_rename(cfg: Dict,
                        transcripts: List[Dict],
                        classifications: Optional[Dict[str, Dict]] = None) -> List[Dict]:
    """步骤 3-4 + Excel：注入分类结果、生成新文件名、改名（或预览）、落盘报表。"""

def run_video_dialogue_skill(cfg: Dict,
                             classifications: Optional[Dict[str, Dict]] = None) -> List[Dict]:
    """主入口：一次性跑完四步。agent 模式不传 classifications 时只跑到步骤 2。"""
```

`classifications` 格式为 **原文件名 → 分类字段** 的字典：

```python
{
    "VID_20260422_100852_DOLBY.mp4": {
        "net_type": "在线", "wake_type": "唤醒", "dialog_content": "开关冷气"
    },
    "VID_20260422_101222_DOLBY.mp4": {
        "net_type": "在线", "wake_type": "唤醒", "dialog_content": "调高空调温度"
    },
}
```

## 4. Excel 报表列定义

文件名：`视频人机对话分析结果.xlsx`，保存于 `video_folder` 目录。

| 列序号 | 列名 | 对应字段 |
|---|---|---|
| A | 原文件名 | `src_filename` |
| B | 完整对话 | `full_dialogue` |
| C | 离线/在线 | `net_type` |
| D | 唤醒类型 | `wake_type` |
| E | 具体指令 | `dialog_content` |
| F | 新文件名 | `expect_new_filename` |
| G | 处理状态 | `status`（中文描述） |
