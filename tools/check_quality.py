#!/usr/bin/env python3
"""
质量检测工具 — Director Gate3 图片质检 + Gate4 视频质检

用法:
  # 检测单张图片
  python3 tools/check_quality.py --type image --file shot.png

  # 检测整个目录
  python3 tools/check_quality.py --type image --dir projects/项目名/images/

  # 检测视频
  python3 tools/check_quality.py --type video --file shot.mp4
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

# ==================== 检测标准 ====================
THRESHOLDS = {
    "image": {
        "min_resolution": (480, 640),   # 最低 480×640（竖屏）
        "min_sharpness": 50,            # Laplacian 方差，低于此值 = 模糊
        "min_aspect_ratio": 0.45,       # 9:16 ≈ 0.56，太低 = 变形
        "max_aspect_ratio": 0.75,
        "min_filesize_kb": 30,          # 太小 = 可能空白/损坏
    },
    "video": {
        "min_sharpness": 30,            # 视频帧模糊阈值
        "blurry_frame_pct_max": 0.3,    # 最多 30% 帧可以模糊
    },
}


def check_image(filepath):
    """检测单张图片质量"""
    name = os.path.basename(filepath)
    size_kb = os.path.getsize(filepath) / 1024
    
    img = cv2.imread(filepath)
    if img is None:
        return {"file": name, "pass": False, "issues": ["无法读取图片文件"]}
    
    h, w = img.shape[:2]
    issues = []
    
    # 分辨率
    min_h, min_w = THRESHOLDS["image"]["min_resolution"]
    if h < min_h or w < min_w:
        issues.append(f"分辨率过低 {w}×{h}，最低要求 {min_w}×{min_h}")
    
    # 清晰度（Laplacian 方差）
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
    min_sharp = THRESHOLDS["image"]["min_sharpness"]
    if sharpness < min_sharp:
        issues.append(f"模糊严重（清晰度 {sharpness:.0f}，阈值 {min_sharp}）")
    
    # 文件太小
    if size_kb < THRESHOLDS["image"]["min_filesize_kb"]:
        issues.append(f"文件过小 {size_kb:.0f}KB")
    
    # 宽高比异常
    ratio = w / h if h > w else h / w
    if ratio < THRESHOLDS["image"]["min_aspect_ratio"] or ratio > THRESHOLDS["image"]["max_aspect_ratio"]:
        issues.append(f"宽高比异常 {w/h:.2f}")
    
    return {
        "file": name,
        "resolution": f"{w}×{h}",
        "size_kb": round(size_kb, 1),
        "sharpness": round(sharpness, 1),
        "pass": len(issues) == 0,
        "issues": issues,
    }


def check_video(filepath, sample_frames=5):
    """检测视频质量（采样帧检测模糊）"""
    name = os.path.basename(filepath)
    
    # 用 ffmpeg 提取样本帧
    tmpdir = tempfile.mkdtemp(prefix="vq_")
    ffmpeg = os.environ.get("FFMPEG", "ffmpeg")
    
    # 获取时长
    result = subprocess.run([ffmpeg, "-i", filepath],
        capture_output=True, text=True)
    duration_s = 5
    for line in (result.stdout + result.stderr).split("\n"):
        if "Duration" in line:
            parts = line.split(",")[0].split(":")
            h, m, s = parts[1], parts[2], parts[3].split(".")[0]
            duration_s = int(h) * 3600 + int(m) * 60 + int(s)
            break
    
    # 均匀采样
    n = min(sample_frames, max(1, duration_s))
    interval = max(1, duration_s // n)
    
    blurry_count = 0
    resolutions = []
    for i in range(n):
        t = min(i * interval, duration_s - 1)
        out_frame = os.path.join(tmpdir, f"frame_{i:02d}.png")
        subprocess.run([ffmpeg, "-y", "-ss", str(t), "-i", filepath,
            "-vframes", "1", "-q:v", "2", out_frame],
            capture_output=True)
        
        if not os.path.exists(out_frame):
            continue
        
        img = cv2.imread(out_frame)
        if img is None:
            continue
        
        h, w = img.shape[:2]
        resolutions.append(f"{w}×{h}")
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        if sharp < THRESHOLDS["video"]["min_sharpness"]:
            blurry_count += 1
    
    # 清理
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)
    
    blurry_pct = blurry_count / n if n > 0 else 0
    min_sharp = THRESHOLDS["video"]["min_sharpness"]
    max_blur = THRESHOLDS["video"]["blurry_frame_pct_max"]
    
    issues = []
    if blurry_pct > max_blur:
        issues.append(f"模糊帧占比 {blurry_pct:.0%}，超过上限 {max_blur:.0%}")
    
    res_set = set(resolutions)
    if len(res_set) > 1:
        issues.append(f"分辨率不一致: {res_set}")
    
    return {
        "file": name,
        "frames_sampled": n,
        "blurry_pct": round(blurry_pct, 2),
        "resolution": list(res_set)[0] if len(res_set) == 1 else str(res_set),
        "duration_s": duration_s,
        "pass": len(issues) == 0,
        "issues": issues,
    }


def check_directory(dirpath):
    """检测目录下所有图片"""
    results = []
    for f in sorted(os.listdir(dirpath)):
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            r = check_image(os.path.join(dirpath, f))
            results.append(r)
    
    passed = sum(1 for r in results if r["pass"])
    return results, passed, len(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="质量检测工具 - Director Gate")
    parser.add_argument("--type", choices=["image", "video"], required=True)
    parser.add_argument("--file", help="单文件路径")
    parser.add_argument("--dir", help="目录路径")
    parser.add_argument("--output", help="JSON 报告输出路径")
    parser.add_argument("--frames", type=int, default=5, help="视频采样帧数")

    args = parser.parse_args()

    results = []
    total = 0
    passed = 0

    if args.type == "image":
        if args.dir:
            results, passed, total = check_directory(args.dir)
        elif args.file:
            r = check_image(args.file)
            results = [r]
            total = 1
            passed = 1 if r["pass"] else 0

        for r in results:
            status = "✅" if r["pass"] else "❌"
            sharp = r.get("sharpness", "?")
            print(f"  {status} {r['file']} | {r['resolution']} | {r['size_kb']}KB | 清晰度:{sharp}")
            for issue in r.get("issues", []):
                print(f"     ⚠️  {issue}")

    elif args.type == "video":
        if args.file:
            r = check_video(args.file, args.frames)
            results = [r]
            total = 1
            passed = 1 if r["pass"] else 0

        for r in results:
            status = "✅" if r["pass"] else "❌"
            print(f"  {status} {r['file']} | {r['duration_s']}s | 模糊:{r['blurry_pct']:.0%}")
            for issue in r.get("issues", []):
                print(f"     ⚠️  {issue}")

    print(f"\n  📊 通过: {passed}/{total}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump({"results": results, "passed": passed, "total": total, "all_pass": passed == total}, f, indent=2)

    sys.exit(0 if passed == total else 1)
