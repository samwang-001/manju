#!/bin/bash
#
# 漫剧工具链健康检查
# 用法: bash tools/health_check.sh
#

# macOS 兼容 timeout 函数（使用内置 perl）
if command -v gtimeout &> /dev/null; then
  TIMEOUT_CMD="gtimeout"
elif command -v timeout &> /dev/null; then
  TIMEOUT_CMD="timeout"
else
  TIMEOUT_CMD=""
  _run_with_timeout() {
    local t="$1"; shift
    perl -e '
      $SIG{ALRM} = sub { kill 9, $$child; print STDERR "[超时] 命令超过 '${t}'秒，已终止\n"; exit 124 };
      my $pid = fork();
      if ($pid == 0) { exec @ARGV; exit 1 }
      $child = $pid;
      alarm('${t}');
      waitpid($pid, 0);
      my $rc = $?;
      alarm(0);
      exit $rc >> 8;
    ' -- "$@"
  }
  alias mytimeout=_run_with_timeout
fi

# 包装函数：统一超时调用
_to() {
  local t="$1"; shift
  if [ -n "$TIMEOUT_CMD" ]; then
    "$TIMEOUT_CMD" "$t" "$@"
  else
    _run_with_timeout "$t" "$@"
  fi
}

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check() {
  local name="$1"
  shift
  echo -n "  [$name] "
  if _to 10 "$@" 2>&1; then
    echo -e "${GREEN}✅ OK${NC}"
    ((PASS++))
  else
    echo -e "${RED}❌ FAIL${NC}"
    ((FAIL++))
  fi
}

check_version() {
  local name="$1"
  shift
  echo -n "  [$name] "
  local result
  result=$(_to 10 "$@" 2>&1 | /usr/bin/head -1)
  if [ -n "$result" ]; then
    echo -e "${GREEN}✅ $result${NC}"
    ((PASS++))
  else
    echo -e "${RED}❌ FAIL${NC}"
    ((FAIL++))
  fi
}

check_warn() {
  local name="$1"
  shift
  echo -n "  [$name] "
  if _to 10 "$@" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ OK${NC}"
    ((PASS++))
  else
    echo -e "${YELLOW}⚠️  WARN (非关键)${NC}"
    ((WARN++))
  fi
}

echo "============================================"
echo "  漫剧工具链健康检查"
echo "============================================"
echo ""

# ===== 系统依赖 =====
echo -e "${YELLOW}[系统依赖]${NC}"
check_version "FFmpeg" ffmpeg -version
check_version "Python3" python3 --version
check_version "Node.js" node --version

echo ""

# ===== Python 包 =====
echo -e "${YELLOW}[Python 包]${NC}"
check "edge_tts" python3 -c "import edge_tts"
check "OpenCV" python3 -c "import cv2"

echo ""

# ===== Node 包 =====
echo -e "${YELLOW}[Node 包]${NC}"
check_warn "puter.js" node -e "require('@heyputer/puter.js')"

echo ""

# ===== 工具脚本 =====
echo -e "${YELLOW}[工具脚本]${NC}"
TOOLS_DIR="$(/usr/bin/dirname "$0")"
for f in "$TOOLS_DIR"/*.sh "$TOOLS_DIR"/*.py "$TOOLS_DIR"/*.js; do
  if [ -f "$f" ]; then
    fname=$(/usr/bin/basename "$f")
    if [ -x "$f" ]; then
      echo "  [$fname] ${GREEN}✅ 可执行${NC}"
      ((PASS++))
    else
      echo "  [$fname] ${YELLOW}⚠️  无执行权限，自动修复${NC}"
      chmod +x "$f"
      ((WARN++))
    fi
  fi
done

echo ""

# ===== Agent & Skill 文件完整性 =====
echo -e "${YELLOW}[Agent 文件]${NC}"
AGENT_DIR="$(cd "$TOOLS_DIR/../.codebuddy/agents" 2>/dev/null && pwd)"
if [ -d "$AGENT_DIR" ]; then
  for f in "$AGENT_DIR"/*.md; do
    fname=$(basename "$f")
    size=$(wc -c < "$f")
    if [ "$size" -gt 100 ]; then
      echo "  [$fname] ${GREEN}✅ ($size bytes)${NC}"
      ((PASS++))
    else
      echo "  [$fname] ${RED}❌ 文件过小 ($size bytes)${NC}"
      ((FAIL++))
    fi
  done
else
  echo "  ${RED}❌ Agent 目录不存在${NC}"
  ((FAIL++))
fi

echo ""

# ===== 外网连接 =====
echo -e "${YELLOW}[外网连接]${NC}"
check_warn "Pollinations 旧API" curl -s --connect-timeout 5 -o /dev/null -w "%{http_code}" "https://image.pollinations.ai/prompt/test?width=1&height=1"
check_warn "Pollinations 新API" curl -s --connect-timeout 5 -o /dev/null -w "%{http_code}" "https://gen.pollinations.ai/image/test?width=1&height=1"

echo ""

# ===== 外网连接 =====
echo -e "${YELLOW}[外网连接]${NC}"
check_warn "火山引擎 Ark" curl -s --connect-timeout 5 -o /dev/null -w "%{http_code}" "https://ark.cn-beijing.volces.com/api/v3"
check_warn "Pollinations 旧API" curl -s --connect-timeout 5 -o /dev/null -w "%{http_code}" "https://image.pollinations.ai/prompt/test?width=1&height=1"
check_warn "Pollinations 新API" curl -s --connect-timeout 5 -o /dev/null -w "%{http_code}" "https://gen.pollinations.ai/image/test?width=1&height=1"

echo ""

# ===== API Keys =====
echo -e "${YELLOW}[API Keys]${NC}"

# 火山引擎 Seedream 直连 (🥇 图片)
if [ -n "$VOLCENGINE_API_KEY" ]; then
  echo "  [Seedream直连] ${GREEN}✅ 已设置${NC} 🥇 火山引擎 Ark ¥0.15/张·原生2K"
  ((PASS++))
else
  echo "  [Seedream直连] ${YELLOW}⚠️ 未设置 VOLCENGINE_API_KEY${NC}"
  echo "  💡 https://console.volcengine.com/ark → API Key管理"
  ((WARN++))
fi

# 火山引擎 TTS (🥇 配音)
if [ -n "$VOLCENGINE_APP_ID" ] && [ -n "$VOLCENGINE_ACCESS_KEY" ]; then
  echo "  [火山TTS] ${GREEN}✅ 已设置${NC} 🥇 字节·中文最自然·情感丰富"
  ((PASS++))
else
  echo "  [火山TTS] ${YELLOW}⚠️ 未设置 VOLCENGINE_APP_ID + ACCESS_KEY${NC}"
  echo "  💡 https://console.volcengine.com → 语音技术 → 服务管理"
  ((WARN++))
fi

# Pollinations (图片生成备选)
if [ -n "$POLLINATIONS_KEY" ]; then
  echo "  [Pollinations] ${GREEN}✅ 已设置 (${POLLINATIONS_KEY:0:10}...)${NC}"
  echo "  🥉 z-image-turbo: 免费 1080×1920"
  ((PASS++))
else
  echo "  [Pollinations] ${YELLOW}⚠️  未设置${NC}"
  ((WARN++))
fi

# Seedance (视频生成)
if [ -n "$SEEDANCE_API_KEY" ]; then
  echo "  [Seedance] ${GREEN}✅ 已设置 (${SEEDANCE_API_KEY:0:10}...)${NC}"
  echo "  🥇 图生视频: 720p/$0.14-0.42/段 (seedanceapi.org)"
  ((PASS++))
else
  echo "  [Seedance] ${YELLOW}⚠️  未设置 SEEDANCE_API_KEY${NC}"
  echo "  💡 获取: https://seedanceapi.org → 注册→控制台→API Keys → export SEEDANCE_API_KEY=\"sk_xxx\""
  ((WARN++))
fi

# Kling (视频生成)
if [ -n "$KLING_API_TOKEN" ]; then
  echo "  [Kling] ${GREEN}✅ 已设置 (${KLING_API_TOKEN:0:10}...)${NC}"
  echo "  🥈 图生视频: 每日免费66积分"
  ((PASS++))
else
  echo "  [Kling] ${YELLOW}⚠️  未设置 KLING_API_TOKEN${NC}"
  echo "  💡 获取: https://klingapi.com → 注册→买API计划→ export KLING_API_TOKEN=\"api-key-kling-xxx\""
  ((WARN++))
fi

echo ""

# ===== 汇总 =====
echo "============================================"
TOTAL=$((PASS + FAIL + WARN))
echo -e "  通过: ${GREEN}$PASS${NC}  |  警告: ${YELLOW}$WARN${NC}  |  失败: ${RED}$FAIL${NC}  |  总计: $TOTAL"
if [ $FAIL -eq 0 ]; then
  echo -e "  ${GREEN}✅ 所有关键检查通过，可以开始使用！${NC}"
else
  echo -e "  ${RED}❌ 有 $FAIL 项检查失败，请先修复${NC}"
fi
echo "============================================"
