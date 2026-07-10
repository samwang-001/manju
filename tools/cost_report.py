#!/usr/bin/env python3
"""消耗统计工具 - 汇总所有项目图片+视频+音效花费"""

import json, glob, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_dirs = sorted(glob.glob(os.path.join(BASE, "projects", "*/")))

total_img = total_vid = total_sfx = 0
img_cost = 0.0

for p in project_dirs:
    name = os.path.basename(p.rstrip("/"))
    if name == ".template":
        continue

    imgs = vids = p_img_cost = 0

    # 图片追踪
    img_file = os.path.join(p, "图片生成追踪.json")
    if os.path.exists(img_file):
        with open(img_file) as f:
            data = json.load(f)
        gens = data.get("generations", [])
        imgs = sum(1 for g in gens if g["status"] == "success")
        p_img_cost = sum(g.get("cost", 0) for g in gens)
        total_img += imgs
        img_cost += p_img_cost

    # 视频追踪
    vid_file = os.path.join(p, "视频生成追踪.json")
    if os.path.exists(vid_file):
        with open(vid_file) as f:
            data = json.load(f)
        gens = data.get("generations", [])
        vids = sum(1 for g in gens if g["status"] == "success")
        total_vid += vids

    # 音效
    sfx = 0
    audiodir = os.path.join(p, "audio")
    if os.path.exists(audiodir):
        sfx = len(glob.glob(os.path.join(audiodir, "*.mp3")))
        total_sfx += sfx

    print(f"{name}: 图{imgs}张(\${p_img_cost:.2f}) | 视频{vids}段(Kling {vids}积分) | 音效{sfx}个")

print(f"\n{'='*50}")
print(f"总计: 图{total_img}张(\${img_cost:.2f}) | 视频{total_vid}段(Kling {total_vid}积分) | 音效{total_sfx}个")
print(f"ElevenLabs: ~{total_sfx}次调用 (10积分/次 = ~{total_sfx*10}积分)")
