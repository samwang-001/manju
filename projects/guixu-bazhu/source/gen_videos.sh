#!/bin/bash
# 归墟霸主 - 批量生成 12 段视频
cd /Users/ui/CodeBuddy/20260702102311
PY=/usr/bin/python3
T=tools/generate_video.py
D=projects/guixu-bazhu

echo "=== 归墟霸主 视频生成 01-12 ==="

for n in 01 02 03 04 05 06 07 08 09 10 11 12; do
  case $n in
    01) d=8 ;; 02) d=5 ;; 03) d=7 ;; 04) d=6 ;;
    05) d=8 ;; 06) d=7 ;; 07) d=8 ;; 08) d=8 ;;
    09) d=7 ;; 10) d=6 ;; 11) d=7 ;; 12) d=6 ;;
  esac
  echo "镜${n} (${d}s)..."
  $PY "$T" --image "$D/images/镜头${n}.png" --motion zoom_in --duration $d \
    --output "$D/videos/镜头${n}.mp4" --backend kenburns --project-dir "$D" 2>&1 | tail -1
done

echo "=== DONE ==="
ls -lh "$D/videos/"
