#!/usr/bin/env python3
"""
程序化图片质量检测工具 - Director Gate3 调用

通过 OpenCV 分析图片的：
1. 色彩一致性 - 主色调是否统一
2. 亮度一致性 - 曝光是否统一
3. 风格相似度 - 感知哈希判断风格漂移
4. 构图检查 - 分辨率、裁切问题
5. 生成结构化报告，Director 读文字即可判断

用法:
  python3 tools/check_images.py --dir projects/comedy-xiuxian/images --output projects/comedy-xiuxian/图片质量检测报告.md
"""

import argparse
import os
import json
import hashlib
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    print("[Checker] ❌ 请先安装: pip3 install opencv-python")
    exit(1)

# ==================== 1. 色彩分析 ====================
def get_dominant_colors(img, k=5):
    """K-means 提取图片主色调"""
    h, w = img.shape[:2]
    # 缩放到 200x200 加速
    scale = 200 / max(h, w)
    small = cv2.resize(img, (int(w * scale), int(h * scale)))
    pixels = small.reshape(-1, 3).astype(np.float32)

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)

    centers = centers.astype(int)
    # 按占比排序
    unique, counts = np.unique(labels, return_counts=True)
    sorted_idx = np.argsort(counts)[::-1]

    result = []
    for i in sorted_idx:
        color = centers[i].tolist()
        ratio = counts[i] / len(labels)
        result.append({"rgb": color, "ratio": round(ratio, 3), "hex": f"#{color[2]:02x}{color[1]:02x}{color[0]:02x}"})
    return result

def color_distance(c1, c2):
    """计算两个 RGB 颜色的欧氏距离"""
    return np.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))

def analyze_color_consistency(images):
    """检测所有图片的主色调是否一致"""
    all_dominant = {}
    for name, img in images.items():
        all_dominant[name] = get_dominant_colors(img, 3)

    # 取所有图的主色调（排名第一的颜色）
    primary_colors = {k: v[0]["rgb"] for k, v in all_dominant.items()}
    
    # 计算两两之间的色差
    ref = list(primary_colors.values())[0]
    deviations = []
    for name, color in primary_colors.items():
        dist = color_distance(ref, color)
        deviations.append({"shot": name, "distance": round(dist, 1)})

    return all_dominant, deviations

# ==================== 2. 亮度分析 ====================
def analyze_brightness_consistency(images):
    """检测所有图片的平均亮度是否一致"""
    brightness_data = {}
    for name, img in images.items():
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mean_brightness = np.mean(gray)
        std_brightness = np.std(gray)
        brightness_data[name] = {
            "mean": round(mean_brightness, 1),
            "std": round(std_brightness, 1)
        }

    # 计算偏差
    means = [v["mean"] for v in brightness_data.values()]
    avg_mean = np.mean(means)
    std_mean = np.std(means)

    deviations = []
    for name, data in brightness_data.items():
        dev = abs(data["mean"] - avg_mean)
        deviations.append({"shot": name, "mean": data["mean"], "deviation": round(dev, 1)})

    return brightness_data, deviations, round(avg_mean, 1), round(std_mean, 1)

# ==================== 3. 风格相似度（感知哈希） ====================
def dhash(img, hash_size=16):
    """差值哈希（dHash），对缩放、颜色变化有鲁棒性"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (hash_size + 1, hash_size))
    diff = resized[:, 1:] > resized[:, :-1]
    return sum([2 ** i for (i, v) in enumerate(diff.flatten()) if v])

def hamming_distance(h1, h2):
    """汉明距离"""
    return bin(h1 ^ h2).count('1')

def analyze_style_similarity(images):
    """通过 dHash 判断风格漂移程度"""
    hashes = {}
    for name, img in images.items():
        hashes[name] = dhash(img)

    # 取第一张为基线
    baseline_hash = list(hashes.values())[0]
    baseline_name = list(hashes.keys())[0]

    similarities = []
    for name, h in hashes.items():
        dist = hamming_distance(baseline_hash, h)
        # 汉明距离 > 80 通常意味着完全不同
        if dist < 30:
            level = "高度相似"
        elif dist < 60:
            level = "中等相似"
        elif dist < 80:
            level = "风格可能漂移"
        else:
            level = "⚠️ 风格严重不一致"
        similarities.append({
            "shot": name,
            "distance": dist,
            "level": level
        })

    return similarities, baseline_name

# ==================== 4. 构图检查 ====================
def check_composition(images, target_resolution=(1080, 1920)):
    """检查分辨率和基础构图的合规性"""
    results = []
    for name, img in images.items():
        h, w = img.shape[:2]
        aspect = round(w / h, 3)
        target_aspect = round(target_resolution[0] / target_resolution[1], 3)
        aspect_ok = abs(aspect - target_aspect) < 0.05
        resolution_ok = w >= target_resolution[0] * 0.9 and h >= target_resolution[1] * 0.9
        results.append({
            "shot": name,
            "resolution": f"{w}x{h}",
            "aspect": aspect,
            "aspect_match": aspect_ok,
            "resolution_ok": resolution_ok
        })
    return results

# ==================== 主流程 ====================
def main():
    parser = argparse.ArgumentParser(description="图片质量检测工具")
    parser.add_argument("--dir", required=True, help="图片目录")
    parser.add_argument("--output", required=True, help="输出报告路径 (.md)")
    parser.add_argument("--json", help="同时输出JSON格式")
    args = parser.parse_args()

    img_dir = Path(args.dir)
    if not img_dir.exists():
        print(f"[Checker] ❌ 目录不存在: {args.dir}")
        exit(1)

    # 读取所有图片
    images = {}
    skipped = []
    for f in sorted(img_dir.glob("*.png")):
        img = cv2.imread(str(f))
        if img is not None:
            images[f.stem] = img
        else:
            skipped.append(f.name)

    if not images:
        print("[Checker] ❌ 没有可读取的PNG图片")
        exit(1)

    print(f"[Checker] 读取 {len(images)} 张图片, 跳过 {len(skipped)} 张")

    # ==== 分析 ====
    # 1. 色彩
    print("[Checker] 分析主色调...")
    color_data, color_deviations = analyze_color_consistency(images)

    # 2. 亮度
    print("[Checker] 分析亮度...")
    brightness_data, brightness_deviations, avg_brightness, std_brightness = analyze_brightness_consistency(images)

    # 3. 风格相似度
    print("[Checker] 分析风格相似度...")
    style_similarities, baseline_shot = analyze_style_similarity(images)

    # 4. 构图
    print("[Checker] 检查构图...")
    composition_results = check_composition(images)

    # ==== 生成报告 ====
    # 判断总体评价
    style_issues = [s for s in style_similarities if s["distance"] >= 60]
    brightness_outliers = [b for b in brightness_deviations if b["deviation"] > 20]
    color_outliers = [c for c in color_deviations if c["distance"] > 100]
    composition_issues = [c for c in composition_results if not c["resolution_ok"]]

    total_shots = len(images)
    problems = {
        "风格漂移": len(style_issues),
        "亮度不均": len(brightness_outliers),
        "色调跳跃": len(color_outliers),
        "分辨率问题": len(composition_issues)
    }

    report = []
    report.append("# 图片质量检测报告\n")
    report.append(f"**检测时间**: 自动化程序分析\n")
    report.append(f"**图片数量**: {total_shots} 张\n")
    report.append(f"**风格基线**: `{baseline_shot}.png`\n")

    # 总览
    report.append("## 总览\n")
    report.append("| 维度 | 问题镜头数 | 严重度 |")
    report.append("|------|-----------|--------|")
    for dim, count in problems.items():
        severity = "🟢 正常" if count == 0 else ("🟡 关注" if count <= 2 else "🔴 严重")
        shots_list = ""
        if dim == "风格漂移" and style_issues:
            shots_list = ", ".join([f"`{s['shot']}`" for s in style_issues])
        elif dim == "色调跳跃" and color_outliers:
            shots_list = ", ".join([f"`{c['shot']}`" for c in color_outliers])
        elif dim == "亮度不均" and brightness_outliers:
            shots_list = ", ".join([f"`{b['shot']}`" for b in brightness_outliers])
        elif dim == "分辨率问题" and composition_issues:
            shots_list = ", ".join([f"`{c['shot']}`" for c in composition_issues])
        report.append(f"| {dim} | {count} | {severity} {shots_list} |")
    report.append("")

    # 色彩详情
    report.append("## 一、色彩一致性\n")
    report.append("### 各镜主色调\n")
    report.append("| 镜头 | 第1主色 | 占比 | 第2主色 | 占比 | 第3主色 | 占比 | 色差 |")
    report.append("|------|---------|------|---------|------|---------|------|------|")
    for shot_name in sorted(color_data.keys()):
        c = color_data[shot_name]
        dev = next((d["distance"] for d in color_deviations if d["shot"] == shot_name), 0)
        c1 = f"<span style='background:{c[0]['hex']};padding:2px 8px;color:white'>{c[0]['hex']}</span>"
        c2 = f"<span style='background:{c[1]['hex']};padding:2px 8px;color:white'>{c[1]['hex']}</span>"
        c3 = f"<span style='background:{c[2]['hex']};padding:2px 8px;color:white'>{c[2]['hex']}</span>"
        flag = " ⚠️" if dev > 100 else ""
        report.append(f"| {shot_name} | {c1} | {c[0]['ratio']} | {c2} | {c[1]['ratio']} | {c3} | {c[2]['ratio']} | {dev}{flag} |")
    report.append("")
    if color_outliers:
        report.append("> ⚠️ 色差 > 100 的镜头色调明显偏离基线，建议检查 Prompt 中的色调关键词\n")
    else:
        report.append("> ✅ 所有镜头主色调一致\n")
    report.append("")

    # 亮度详情
    report.append("## 二、亮度一致性\n")
    report.append(f"**平均亮度**: {avg_brightness:.1f} ± {std_brightness:.1f}\n")
    report.append("| 镜头 | 平均亮度 | 偏差 |")
    report.append("|------|----------|------|")
    for b in sorted(brightness_deviations, key=lambda x: x["deviation"], reverse=True):
        flag = " ⚠️" if b["deviation"] > 20 else ""
        report.append(f"| {b['shot']} | {b['mean']:.1f} | {b['deviation']:.1f}{flag} |")
    report.append("")

    # 风格相似度
    report.append("## 三、风格相似度（dHash）\n")
    report.append(f"**基线**: `{baseline_shot}.png`（汉明距离越小越相似）\n")
    report.append("| 镜头 | 汉明距离 | 判定 |")
    report.append("|------|----------|------|")
    for s in sorted(style_similarities, key=lambda x: x["distance"], reverse=True):
        flag = " ⚠️" if s["distance"] >= 60 else (" 🔴" if s["distance"] >= 80 else "")
        report.append(f"| {s['shot']} | {s['distance']} | {s['level']}{flag} |")
    report.append("")

    # 构图
    report.append("## 四、构图合规性\n")
    report.append("| 镜头 | 分辨率 | 宽高比 | 匹配 |")
    report.append("|------|--------|--------|------|")
    for c in composition_results:
        match_icon = "✅" if c["aspect_match"] else "❌"
        report.append(f"| {c['shot']} | {c['resolution']} | {c['aspect']} | {match_icon} |")
    report.append("")

    # 总体结论
    report.append("## 五、结论\n")
    total_issues = sum(problems.values())
    if total_issues == 0:
        report.append("✅ **全部通过** - 所有图片风格统一，构图规范，可进入下一阶段。\n")
    else:
        report.append(f"⚠️ **发现 {total_issues} 处问题**，建议 Director 逐项审查后决定是否退回重做。\n")
        report.append("\n### 待修复清单\n")
        for s in style_issues:
            report.append(f"- `{s['shot']}`: 风格漂移（距离={s['distance']}），建议统一画风关键词")
        for b in brightness_outliers:
            report.append(f"- `{b['shot']}`: 亮度过{('暗' if b['mean'] < avg_brightness else '亮')}（偏差={b['deviation']}），建议调整 lighting 关键词")
        for c in color_outliers:
            report.append(f"- `{c['shot']}`: 色调偏离基线（色差={c['distance']}），建议加入统一色调关键词")
        for c in composition_issues:
            report.append(f"- `{c['shot']}`: 分辨率不达标（{c['resolution']}），建议检查生成参数")
    report.append("")

    # 写出
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print(f"[Checker] ✅ 报告已生成: {output_path}")

    # JSON
    if args.json:
        json_data = {
            "summary": {"total_shots": total_shots, "total_issues": total_issues, "problems": problems},
            "color_consistency": color_deviations,
            "brightness_consistency": {"avg": avg_brightness, "std": std_brightness, "shots": brightness_deviations},
            "style_similarity": {"baseline": baseline_shot, "shots": style_similarities},
            "composition": composition_results
        }
        json_path = Path(args.json)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        print(f"[Checker] ✅ JSON 已生成: {json_path}")

if __name__ == "__main__":
    main()
