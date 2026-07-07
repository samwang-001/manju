#!/bin/bash
# 漫剧工具链 - 一键安装脚本
# macOS/Linux 通用
set -e

echo "============================================"
echo "  漫剧工具链 (Manju) 一键安装"
echo "============================================"
echo ""

# 1. 检查基础工具
echo "[1/5] 检查基础工具..."
for cmd in python3 node npm git curl; do
    if ! command -v $cmd &> /dev/null; then
        echo "  ❌ 缺少 $cmd，请先安装"
        exit 1
    fi
    echo "  ✅ $cmd"
done

# 2. 安装 FFmpeg (macOS)
echo ""
echo "[2/5] 安装 FFmpeg..."
if command -v ffmpeg &> /dev/null; then
    echo "  ✅ ffmpeg 已安装"
else
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if command -v brew &> /dev/null; then
            echo "  📦 brew install ffmpeg..."
            brew install ffmpeg
        else
            echo "  ⚠️  请先安装 Homebrew: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            echo "  然后运行: brew install ffmpeg"
            exit 1
        fi
    else
        echo "  📦 apt install ffmpeg..."
        sudo apt-get update && sudo apt-get install -y ffmpeg
    fi
fi

# 3. 安装 Python 依赖
echo ""
echo "[3/5] 安装 Python 依赖..."
pip3 install edge-tts opencv-python 2>&1 | tail -1
echo "  ✅ edge-tts + opencv-python"

# 4. 安装 Node 依赖
echo ""
echo "[4/5] 安装 Node 依赖..."
npm install 2>&1 | tail -1
echo "  ✅ node_modules"

# 5. 检查环境变量
echo ""
echo "[5/5] 环境变量..."
cp -n .env.example .env 2>/dev/null || true

if [ -f .env ]; then
    echo "  ✅ .env 已创建，请编辑填入你的 API Key:"
    echo ""
    cat .env
else
    echo "  请创建 .env 文件并填入你的 API Key:"
    echo ""
    echo "  export VOLCENGINE_API_KEY=\"volc_xxx\"        # 火山引擎 → 🥇 图片"
    echo "  export VOLCENGINE_APP_ID=\"app_xxx\"          # 火山引擎 → 🥇 配音"
    echo "  export VOLCENGINE_ACCESS_KEY=\"ak_xxx\"       # 火山引擎 → 🥇 配音"
    echo "  export POLLINATIONS_KEY=\"sk_xxx\"            # 🥉 图片备选"
    echo "  export SEEDANCE_API_KEY=\"sk_xxx\"            # 🥇 视频"
    echo "  export KLING_API_TOKEN=\"api-key-kling-xxx\"  # 🥈 视频备选"
fi

echo ""
echo "============================================"
echo "  ✅ 安装完成！"
echo ""
echo "  验证安装: bash tools/health_check.sh"
echo "  运行漫剧: @manju-workflow 帮我制作漫剧《xxx》"
echo "============================================"
