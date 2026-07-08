#!/bin/bash
# 归墟霸主 - 批量生成剩余图片 05-12
export POLLINATIONS_KEY="sk_4Ci4zMDDTwQubKE99Ua2t6wZXUDvrwW3"
cd /Users/ui/CodeBuddy/20260702102311
N=/usr/local/bin/node
T=tools/generate_image.js
D=projects/guixu-bazhu
P="-w 1080 -h 1920 --project-dir $D"

echo "=== 归墟霸主 图片 05-12 ==="

$N $T --prompt "Chinese anime chibi comedy, boy messy hair dusty gray hoodie hiding behind altar, wiping sweat nervous grin, purple rim light, dark moody --ar 9:16" --output $D/images/镜头05.png $P
echo "05 done"

$N $T --prompt "Chinese anime dynamic, boy messy hair gray hoodie tripping backwards, hand slapping altar rune, golden light from impact, shocked face --ar 9:16" --output $D/images/镜头06.png $P
echo "06 done"

$N $T --prompt "Chinese ink wash epic, golden orb erupting light pillar skyward through purple mist, stone golem frozen confused, dramatic gold-blue-purple lighting --ar 9:16" --output $D/images/镜头07.png $P
echo "07 done"

$N $T --prompt "Chinese anime ink wash, boy messy hair gray hoodie, golden orb floating into palm, warm light through fingers, sacred glow, magical moment --ar 9:16" --output $D/images/镜头08.png $P
echo "08 done"

$N $T --prompt "Chinese anime epic, giant stone golem kneeling behind boy holding golden orb, red eyes fading to blue, dust settling, servant posture, overwhelmed boy looking back --ar 9:16" --output $D/images/镜头09.png $P
echo "09 done"

$N $T --prompt "Chinese anime ink wash portrait, extreme close-up boy messy hair, wide eyes O-mouth shocked, golden light on face, huge sweat drop, pure confusion --ar 9:16" --output $D/images/镜头10.png $P
echo "10 done"

$N $T --prompt "Chinese ink wash epic wide, boy and kneeling golem silhouetted against golden ring, distant glowing eyes awakening in purple void, cinematic pull-out --ar 9:16" --output $D/images/镜头11.png $P
echo "11 done"

$N $T --prompt "Pure black screen golden Chinese title fading, single golden eye lingering before cut to black --ar 9:16" --output $D/images/镜头12.png $P
echo "12 done"

echo "=== ALL DONE ==="
ls -lh $D/images/*.png
