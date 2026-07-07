#!/bin/bash
#
# 视频合成工具 - Editor Agent 调用
# 将多个视频片段 + 配音 + 字幕 + BGM 合成为最终视频
#
# 用法:
#   bash tools/compose_video.sh --project projects/demo
#   bash tools/compose_video.sh --videos "v1.mp4 v2.mp4" --audio "a1.mp3 a2.mp3" --output final.mp4
#

set -e

# ==================== macOS 兼容 timeout ====================
if command -v gtimeout &> /dev/null; then
  _to() { gtimeout "$@"; }
elif command -v timeout &> /dev/null; then
  _to() { timeout "$@"; }
else
  _to() {
    local t="$1"; shift
    perl -e '
      $SIG{ALRM} = sub { kill 9, $$child; exit 124 };
      my $pid = fork();
      if ($pid == 0) { exec @ARGV; exit 1 }
      $child = $pid;
      alarm('"${t}"');
      waitpid($pid, 0);
      my $rc = $?;
      alarm(0);
      exit $rc >> 8;
    ' -- "$@"
  }
fi

# ==================== 参数解析 ====================
PROJECT=""
VIDEOS=""
AUDIO=""
OUTPUT=""
BGM=""
SUBTITLE=""
RESOLUTION="1080x1920"

while [[ $# -gt 0 ]]; do
  case $1 in
    --project)   PROJECT="$2"; shift 2 ;;
    --videos)    VIDEOS="$2"; shift 2 ;;
    --audio)     AUDIO="$2"; shift 2 ;;
    --output)    OUTPUT="$2"; shift 2 ;;
    --bgm)       BGM="$2"; shift 2 ;;
    --subtitle)  SUBTITLE="$2"; shift 2 ;;
    --resolution) RESOLUTION="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

# ==================== 从项目目录推断参数 ====================
if [ -n "$PROJECT" ]; then
  VIDEO_DIR="$PROJECT/videos"
  AUDIO_DIR="$PROJECT/audio"
  OUTPUT="${OUTPUT:-$PROJECT/final.mp4}"
  BGM="${BGM:-$PROJECT/bgm/bgm.mp3}"
  SUBTITLE="${SUBTITLE:-$PROJECT/subtitles.srt}"

  # 按文件名排序收集所有视频
  if [ -d "$VIDEO_DIR" ]; then
    VIDEOS=$(ls "$VIDEO_DIR"/*.mp4 2>/dev/null | sort | tr '\n' ' ')
  fi
  if [ -d "$AUDIO_DIR" ]; then
    AUDIO=$(ls "$AUDIO_DIR"/*.mp3 2>/dev/null | sort | tr '\n' ' ')
  fi
fi

# ==================== 检查依赖 ====================
if ! command -v ffmpeg &> /dev/null; then
  echo "[Editor] ❌ 请先安装 FFmpeg: brew install ffmpeg"
  exit 1
fi

echo "[Editor] ========== 开始合成 =========="
echo "  视频片段: $(echo $VIDEOS | wc -w) 个"
echo "  配音文件: $(echo $AUDIO | wc -w) 个"
echo "  输出文件: $OUTPUT"

# ==================== 创建临时目录 ====================
TMP_DIR=$(mktemp -d)
trap "rm -rf $TMP_DIR" EXIT

# ==================== 步骤1: 拼接视频片段 ====================
echo "[Editor] 步骤1: 拼接视频片段..."

CONCAT_LIST="$TMP_DIR/concat.txt"
for v in $VIDEOS; do
  echo "file '$(realpath "$v")'" >> "$CONCAT_LIST"
done

CONCAT_VIDEO="$TMP_DIR/concat_video.mp4"
_to 120 ffmpeg -y -f concat -safe 0 -i "$CONCAT_LIST" \
  -c:v libx264 -preset fast -crf 23 \
  -vf "scale=$RESOLUTION:force_original_aspect_ratio=decrease,pad=$RESOLUTION:(ow-iw)/2:(oh-ih)/2" \
  -pix_fmt yuv420p -an \
  "$CONCAT_VIDEO" 2>&1 | tail -1

echo "[Editor] ✅ 视频拼接完成: $(du -h "$CONCAT_VIDEO" | cut -f1)"

# ==================== 步骤2: 拼接所有配音 ====================
echo "[Editor] 步骤2: 拼接配音..."

if [ -n "$AUDIO" ]; then
  AUDIO_LIST="$TMP_DIR/audio_list.txt"
  for a in $AUDIO; do
    echo "file '$(realpath "$a")'" >> "$AUDIO_LIST"
  done

  CONCAT_AUDIO="$TMP_DIR/concat_audio.mp3"
  _to 60 ffmpeg -y -f concat -safe 0 -i "$AUDIO_LIST" -c copy "$CONCAT_AUDIO" 2>&1 | tail -1
  echo "[Editor] ✅ 配音拼接完成"
else
  echo "[Editor] ⚠️ 没有配音文件，跳过"
  CONCAT_AUDIO=""
fi

# ==================== 步骤3: 混合视频和音频 ====================
echo "[Editor] 步骤3: 混合音视频..."

VIDEO_WITH_AUDIO="$TMP_DIR/video_with_audio.mp4"

if [ -n "$CONCAT_AUDIO" ]; then
  VIDEO_DURATION=$(_to 10 ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$CONCAT_VIDEO" 2>/dev/null || echo "0")

  _to 120 ffmpeg -y -i "$CONCAT_VIDEO" -i "$CONCAT_AUDIO" \
    -c:v copy -c:a aac -b:a 192k \
    -map 0:v:0 -map 1:a:0 \
    -shortest \
    "$VIDEO_WITH_AUDIO" 2>&1 | tail -1
else
  cp "$CONCAT_VIDEO" "$VIDEO_WITH_AUDIO"
fi

echo "[Editor] ✅ 音视频混合完成"

# ==================== 步骤4: 添加 BGM（如果有） ====================
FINAL_BEFORE_SUB="$VIDEO_WITH_AUDIO"

if [ -n "$BGM" ] && [ -f "$BGM" ]; then
  echo "[Editor] 步骤4: 添加背景音乐..."

  FINAL_WITH_BGM="$TMP_DIR/with_bgm.mp4"
  VIDEO_DURATION=$(_to 10 ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$VIDEO_WITH_AUDIO" 2>/dev/null || echo "0")

  _to 120 ffmpeg -y -i "$VIDEO_WITH_AUDIO" -stream_loop -1 -i "$BGM" \
    -t "$VIDEO_DURATION" \
    -filter_complex "[1:a]volume=0.15[bgm];[0:a][bgm]amix=inputs=2:duration=first[a]" \
    -map 0:v -map "[a]" \
    -c:v copy -c:a aac -b:a 192k \
    "$FINAL_WITH_BGM" 2>&1 | tail -1

  echo "[Editor] ✅ BGM 已添加"
  FINAL_BEFORE_SUB="$FINAL_WITH_BGM"
else
  echo "[Editor] ⚠️ 没有 BGM 文件，跳过"
fi

# ==================== 步骤5: 添加字幕 ====================
if [ -n "$SUBTITLE" ] && [ -f "$SUBTITLE" ]; then
  echo "[Editor] 步骤5: 添加字幕..."

  _to 120 ffmpeg -y -i "$FINAL_BEFORE_SUB" -vf "subtitles=$SUBTITLE:force_style='FontName=PingFang SC,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=1'" \
    -c:v libx264 -preset fast -crf 23 \
    -c:a copy \
    "$OUTPUT" 2>&1 | tail -1

  echo "[Editor] ✅ 字幕已添加"
else
  echo "[Editor] ⚠️ 没有字幕文件，跳过"
  cp "$FINAL_BEFORE_SUB" "$OUTPUT"
fi

# ==================== 完成 ====================
FINAL_SIZE=$(du -h "$OUTPUT" | cut -f1)
FINAL_DURATION=$(_to 10 ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$OUTPUT" 2>/dev/null || echo "N/A")

echo ""
echo "[Editor] ========== 合成完成 =========="
echo "  输出文件: $OUTPUT"
echo "  文件大小: $FINAL_SIZE"
echo "  总时长: ${FINAL_DURATION}s"
echo ""
echo "  下一步: 可以用播放器打开 final.mp4 查看效果"
