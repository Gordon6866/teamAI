#!/bin/bash
# ============================================================
# 视频人机对话分析与重命名 Skill - 工作流模板
#
# 用法：
#   bash workflow.sh <视频文件夹路径> [--execute]
#
# 参数：
#   <视频文件夹路径>  必填，包含待处理视频的文件夹绝对路径
#   --execute         可选，加上后执行真实改名；不加则为预览模式
#
# 示例：
#   bash workflow.sh /path/to/videos          # 预览模式
#   bash workflow.sh /path/to/videos --execute # 执行真实改名
# ============================================================

set -euo pipefail

# ---------- 参数解析 ----------
VIDEO_FOLDER="${1:-}"
EXECUTE_MODE="${2:-}"

if [ -z "$VIDEO_FOLDER" ]; then
    echo "[ERROR] 请指定视频文件夹路径"
    echo "用法: bash workflow.sh <视频文件夹路径> [--execute]"
    exit 1
fi

if [ ! -d "$VIDEO_FOLDER" ]; then
    echo "[ERROR] 文件夹不存在: $VIDEO_FOLDER"
    exit 1
fi

PREVIEW_ONLY="True"
if [ "$EXECUTE_MODE" = "--execute" ]; then
    PREVIEW_ONLY="False"
    echo "[WARN] 已指定 --execute，将执行真实文件重命名！"
    read -p "确认继续？(yes/no): " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo "已取消。"
        exit 0
    fi
fi

# ---------- 前置依赖检查 ----------
echo "[步骤0] 前置依赖检查..."

if ! command -v ffmpeg &> /dev/null; then
    echo "[ERROR] 未检测到 ffmpeg，请先安装并添加到 PATH"
    exit 1
fi
echo "  ffmpeg: OK"

if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo "[ERROR] 未检测到 Python"
    exit 1
fi
PYTHON_CMD=$(command -v python3 || command -v python)
echo "  Python: $($PYTHON_CMD --version)"

# 检查 Python 依赖
$PYTHON_CMD -c "import whisper, openpyxl, requests" 2>/dev/null || {
    echo "[ERROR] 缺少 Python 依赖，请执行: pip install openai-whisper openpyxl requests"
    exit 1
}
echo "  Python 依赖: OK"

# ---------- 执行主脚本 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_SCRIPT="$SCRIPT_DIR/../scripts/video_dialogue_analyzer.py"

echo ""
echo "[步骤1-4] 启动视频人机对话分析流水线..."
echo "  视频文件夹: $VIDEO_FOLDER"
echo "  预览模式: $PREVIEW_ONLY"
echo ""

# 通过环境变量传递配置，运行主脚本
VIDEO_FOLDER="$VIDEO_FOLDER" \
PREVIEW_ONLY="$PREVIEW_ONLY" \
$PYTHON_CMD "$MAIN_SCRIPT"

echo ""
echo "[完成] 流水线执行结束。"
echo "  Excel 报表位置: $VIDEO_FOLDER/视频人机对话分析结果.xlsx"
