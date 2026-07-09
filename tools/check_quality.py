#!/usr/bin/env python3
"""
七维质量检测 — Director Gate 自动化质检

图片: 清晰度 | 曝光 | 色偏 | 主体居中 | 信息熵 | 人脸 | 宽高比
视频: 帧模糊率 | 帧间一致性 | 分辨率

用法:
  python3 tools/check_quality.py --type image --dir projects/项目名/images/
  python3 tools/check_quality.py --type video --file shot.mp4

人脸检测: OpenCV DNN（首次自动下载5MB模型）
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import cv2
import numpy as np

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
MODEL_DIR = os.path.expanduser("~/.manju_models")

# ==================== 人脸检测模型 ====================
# 动漫人脸 LBP Cascade（132KB，从gitee下载，国内可访问）
ANIME_CASCADE = os.path.join(MODEL_DIR, "lbpcascade_animeface.xml")
ANIME_URL = "https://gitee.com/chaofeili/lbpcascade_animeface/raw/master/lbpcascade_animeface.xml"

_anime_cascade = None


def _download_file(url, path):
    """下载文件（静默处理失败）"""
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return True
    os.makedirs(MODEL_DIR, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, path)
        return os.path.getsize(path) > 1000
    except Exception:
        return False


def get_anime_detector():
    """动漫脸 LBP Cascade 检测器"""
    global _anime_cascade
    if _anime_cascade is not None:
        return _anime_cascade
    if not _download_file(ANIME_URL, ANIME_CASCADE):
        return None
    _anime_cascade = cv2.CascadeClassifier(ANIME_CASCADE)
    return _anime_cascade if not _anime_cascade.empty() else None


def detect_faces(img):
    """
    动漫人脸检测（LBP Cascade）
    返回 [(source, x, y, w, h), ...]
    注：OpenCV 5.0 移除了 Caffe/SSD 真人脸检测。如需要真人脸，
    可安装 MediaPipe: pip3 install mediapipe
    """
    all_faces = []
    cascade = get_anime_detector()
    if cascade is not None:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=3, minSize=(40, 40))
        for (x, y, fw, fh) in faces:
            all_faces.append(("anime", x, y, fw, fh))
    return all_faces


# ==================== 检测标准 ====================
THRESHOLDS = {
    "image": {
        "min_sharpness": 20,        # Laplacian方差（柔和画风阈值）
        "min_entropy": 3.5,         # 信息熵（太低=空白/纯色）
        "max_overexposed_pct": 0.3, # 过曝区域占比上限
        "max_underexposed_pct": 0.6,# 欠曝区域上限（暗调风格放宽）
        "max_color_cast": 30.0,     # 风格化图片天然强色调
        "min_center_attention": 0.3,# 中央区域边缘密度占比（竖屏主体居中）
        "min_face_count": 0,        # 最少人脸数（0=不强制，但有人脸则检查）
        "max_face_count": 3,        # 最多人脸数（超多可能AI崩坏）
        "min_face_aspect": 0.5,     # 人脸宽高比下限（<0.5=太窄，AI拉伸变形）
        "max_face_aspect": 1.5,     # 人脸宽高比上限（>1.5=太宽，AI挤压变形）
        "min_face_confidence": 0.7, # 人脸置信度下限
        "min_resolution": (480, 640),
        "min_aspect_ratio": 0.45,
        "max_aspect_ratio": 0.75,
        "min_filesize_kb": 30,
    },
    "video": {
        "min_sharpness": 20,
        "max_blur_pct": 0.3,
        "max_interframe_diff": 80,  # 帧间差异骤变（闪烁/跳帧）
    },
}


def check_image(filepath):
    """六维图片质量检测"""
    name = os.path.basename(filepath)
    size_kb = os.path.getsize(filepath) / 1024

    img = cv2.imread(filepath)
    if img is None:
        return {"file": name, "pass": False, "issues": ["无法读取图片"], "scores": {}}

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    issues = []
    scores = {}

    # 1. 清晰度
    sharp = cv2.Laplacian(gray, cv2.CV_64F).var()
    scores["sharpness"] = round(sharp, 1)
    if sharp < THRESHOLDS["image"]["min_sharpness"]:
        issues.append(f"模糊(清晰度{sharp:.0f})")

    # 2. 曝光 — 直方图分析
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    hist = hist / hist.sum()
    overexposed = hist[240:].sum()
    underexposed = hist[:20].sum()
    scores["overexposed_pct"] = round(float(overexposed), 3)
    scores["underexposed_pct"] = round(float(underexposed), 3)
    if overexposed > THRESHOLDS["image"]["max_overexposed_pct"]:
        issues.append(f"过曝{overexposed:.0%}")
    if underexposed > THRESHOLDS["image"]["max_underexposed_pct"]:
        issues.append(f"欠曝{underexposed:.0%}")

    # 3. 色偏 — RGB通道均值偏差
    means = cv2.mean(img)[:3]
    avg = np.mean(means)
    color_cast = np.std(means)
    scores["color_cast"] = round(float(color_cast), 1)
    if color_cast > THRESHOLDS["image"]["max_color_cast"]:
        issues.append(f"色偏{color_cast:.0f}")

    # 4. 主体居中 — 中央区域 Sobel 边缘密度 vs 全局
    sobel = cv2.Sobel(gray, cv2.CV_64F, 1, 1, ksize=3)
    sobel_abs = np.abs(sobel)
    total_edges = sobel_abs.mean()
    ch, cw = h // 3, w // 3
    center_region = sobel_abs[ch:2*ch, cw:2*cw]
    center_density = center_region.mean() / (total_edges + 1e-6)
    scores["center_attention"] = round(float(center_density), 2)
    if center_density < THRESHOLDS["image"]["min_center_attention"]:
        issues.append(f"主体不居中(边缘密度{center_density:.1f})")

    # 5. 信息熵 — 检测空白/纯色区域
    hist_norm = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    hist_norm = hist_norm / hist_norm.sum()
    entropy = -np.sum(hist_norm[hist_norm > 0] * np.log2(hist_norm[hist_norm > 0] + 1e-10))
    scores["entropy"] = round(float(entropy), 1)
    if entropy < THRESHOLDS["image"]["min_entropy"]:
        issues.append(f"信息量过低(熵{entropy:.1f})")

    # 6. 人脸检测（SSD真人 + LBP动漫 双引擎）
    faces = detect_faces(img)
    scores["face_count"] = len(faces)
    if faces:
        # 选最大的人脸检查宽高比
        best = max(faces, key=lambda f: f[3] * f[4])  # 按面积选最大
        source, fx, fy, fw, fh = best
        face_ratio = fw / max(fh, 1)
        scores["face_aspect"] = round(face_ratio, 2)
        scores["face_source"] = source

        min_ar = THRESHOLDS["image"]["min_face_aspect"]
        max_ar = THRESHOLDS["image"]["max_face_aspect"]
        if face_ratio < min_ar or face_ratio > max_ar:
            issues.append(f"人脸变形(宽高比{face_ratio:.1f}, 正常{min_ar}-{max_ar})")

        if len(faces) > THRESHOLDS["image"]["max_face_count"]:
            issues.append(f"人脸过多({len(faces)}张)")
    else:
        scores["face_aspect"] = 0
        scores["face_source"] = "none"
        # 如果需要强制人脸检测，可设 min_face_count > 0

    # 7. 分辨率 + 宽高比 + 文件大小
    if h < THRESHOLDS["image"]["min_resolution"][0] or w < THRESHOLDS["image"]["min_resolution"][1]:
        issues.append(f"分辨率过低{w}×{h}")
    ratio = w / h if h > w else h / w
    if ratio < THRESHOLDS["image"]["min_aspect_ratio"] or ratio > THRESHOLDS["image"]["max_aspect_ratio"]:
        issues.append(f"宽高比异常{w/h:.2f}")
    if size_kb < THRESHOLDS["image"]["min_filesize_kb"]:
        issues.append(f"文件过小{size_kb:.0f}KB")

    return {
        "file": name,
        "resolution": f"{w}×{h}",
        "size_kb": round(size_kb, 1),
        "pass": len(issues) == 0,
        "issues": issues,
        "scores": scores,
    }


def check_directory(dirpath):
    """检测目录下所有图片，含风格一致性"""
    results = []
    for f in sorted(os.listdir(dirpath)):
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            r = check_image(os.path.join(dirpath, f))
            results.append(r)

    passed = sum(1 for r in results if r["pass"])

    # 风格一致性：色偏一致性
    casts = [r["scores"].get("color_cast", 0) for r in results]
    centers = [r["scores"].get("center_attention", 0) for r in results]

    consistency_issues = []
    if len(casts) > 1 and max(casts) - min(casts) > 4:
        consistency_issues.append(f"色偏不一致(极差{max(casts)-min(casts):.0f})")
    if len(centers) > 1 and max(centers) - min(centers) > 0.5:
        consistency_issues.append(f"构图不一致")

    return results, passed, len(results), consistency_issues


def check_video(filepath, sample_frames=6):
    """视频质量检测：帧模糊率 + 帧间一致性"""
    name = os.path.basename(filepath)
    tmpdir = tempfile.mkdtemp(prefix="vq_")

    # 获取时长
    result = subprocess.run([FFMPEG, "-i", filepath], capture_output=True, text=True)
    duration_s = 5
    for line in (result.stdout + result.stderr).split("\n"):
        if "Duration" in line:
            h, m, s = line.split(",")[0].split(":")[1:]
            duration_s = int(float(h) * 3600 + float(m) * 60 + float(s))
            break

    n = min(sample_frames, max(2, duration_s))
    interval = max(1, duration_s // n)

    blurry = 0
    sharpnesses = []
    last_gray = None
    interframe_diffs = []

    for i in range(n):
        t = min(i * interval, duration_s - 1)
        frame_path = os.path.join(tmpdir, f"f_{i:02d}.png")
        subprocess.run([FFMPEG, "-y", "-ss", str(t), "-i", filepath,
            "-vframes", "1", "-q:v", "2", frame_path], capture_output=True)

        if not os.path.exists(frame_path):
            continue

        img = cv2.imread(frame_path)
        if img is None:
            continue

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 模糊检测
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()
        sharpnesses.append(sharp)
        if sharp < THRESHOLDS["video"]["min_sharpness"]:
            blurry += 1

        # 帧间一致性（相邻帧差异）
        if last_gray is not None:
            diff = np.abs(gray.astype(float) - last_gray.astype(float)).mean()
            interframe_diffs.append(diff)
        last_gray = gray.copy()

    shutil.rmtree(tmpdir, ignore_errors=True)

    issues = []
    blur_pct = blurry / n if n > 0 else 0
    if blur_pct > THRESHOLDS["video"]["max_blur_pct"]:
        issues.append(f"模糊帧{blur_pct:.0%}")

    # 帧间差异异常（单帧突变 = 闪烁/跳帧）
    if interframe_diffs:
        avg_diff = np.mean(interframe_diffs)
        max_diff = max(interframe_diffs)
        if max_diff > avg_diff * THRESHOLDS["video"]["max_interframe_diff"] / 20:
            issues.append(f"帧间突变(闪烁)")

    return {
        "file": name,
        "duration_s": duration_s,
        "frames": n,
        "blur_pct": round(blur_pct, 2),
        "avg_sharpness": round(np.mean(sharpnesses), 1) if sharpnesses else 0,
        "pass": len(issues) == 0,
        "issues": issues,
    }


def format_report(results, passed, total, consistency=None):
    """格式化的质检报告"""
    header = f"{'='*60}" if not consistency else f"{'='*60}"
    lines = [header]

    for r in results:
        icon = "✅" if r["pass"] else "❌"
        scores = r.get("scores", {})
        detail = ""
        if scores:
            detail = f"| 清晰:{scores.get('sharpness','?')} "
            detail += f"过曝:{scores.get('overexposed_pct',0):.0%} "
            fc = scores.get('face_count', -1)
            if fc >= 0:
                detail += f"人脸:{fc}张 "
            if "face_aspect" in scores and scores.get("face_aspect"):
                detail += f"({scores.get('face_aspect',0):.1f}) "
            detail += f"| {r['size_kb']}KB"
        lines.append(f"  {icon} {r['file']} {detail}")
        for issue in r.get("issues", []):
            lines.append(f"     ⚠️  {issue}")

    if consistency:
        lines.append(f"  💡 风格一致性:")
        for c in consistency:
            lines.append(f"     ℹ️  {c}（画风变化属正常，仅供参考）")

    lines.append(f"\n  📊 通过: {passed}/{total}")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="六维质量检测 - Director Gate")
    parser.add_argument("--type", choices=["image", "video"], required=True)
    parser.add_argument("--file", help="单文件")
    parser.add_argument("--dir", help="目录")
    parser.add_argument("--output", help="JSON报告输出")
    parser.add_argument("--frames", type=int, default=6, help="视频采样帧数")

    args = parser.parse_args()

    if args.type == "image":
        if args.dir:
            results, passed, total, consistency = check_directory(args.dir)
            print(format_report(results, passed, total, consistency))
        elif args.file:
            r = check_image(args.file)
            results, passed, total = [r], 1 if r["pass"] else 0, 1
            print(format_report([r], passed, total))

        if args.output:
            with open(args.output, "w") as f:
                json.dump({"results": results, "total": total, "passed": passed,
                    "all_pass": passed == total}, f, indent=2, ensure_ascii=False)
        sys.exit(0 if passed == total else 1)

    elif args.type == "video":
        if args.file:
            results = [check_video(args.file, args.frames)]
        for r in results:
            icon = "✅" if r["pass"] else "❌"
            print(f"  {icon} {r['file']} | {r['duration_s']}s | 模糊:{r['blur_pct']:.0%} "
                  f"| 锐度:{r.get('avg_sharpness','?')}")
            for issue in r.get("issues", []):
                print(f"     ⚠️  {issue}")
        passed = sum(1 for r in results if r["pass"])
        print(f"\n  📊 通过: {passed}/{len(results)}")
        sys.exit(0 if passed == len(results) else 1)
