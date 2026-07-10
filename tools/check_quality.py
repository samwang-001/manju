#!/usr/bin/env python3
"""
七维质量检测 — Director Gate 自动化质检（含AI生成图5维专项检测）

图片: 清晰度 | 曝光 | 色偏 | 主体居中 | 信息熵 | 人脸 | 宽高比
      面部变形 | 手指数目 | 肢体扭曲 | AI文字水印 | 画风一致性

视频: 帧模糊率 | 帧间一致性 | 分辨率 | 人脸稳定性

用法:
  python3 tools/check_quality.py --type image --dir projects/项目名/images/
  python3 tools/check_quality.py --type video --file shot.mp4

人脸检测: OpenCV LBP Cascade（首次自动下载模型）
人体检测: MediaPipe（可选，pip install mediapipe 后启用肢体/手指检测）
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

# ==================== 可选依赖: MediaPipe ====================
_MEDIAPIPE = None

def _get_mediapipe():
    """懒加载MediaPipe，避免未安装时崩溃"""
    global _MEDIAPIPE
    if _MEDIAPIPE is not None:
        return _MEDIAPIPE
    try:
        import mediapipe as mp
        _MEDIAPIPE = mp
        return _MEDIAPIPE
    except ImportError:
        return None


# ==================== 人脸检测模型 ====================
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
    if not hasattr(cv2, 'CascadeClassifier'):
        return None  # OpenCV 5.x 已移除
    if not _download_file(ANIME_URL, ANIME_CASCADE):
        return None
    _anime_cascade = cv2.CascadeClassifier(ANIME_CASCADE)
    return _anime_cascade if not _anime_cascade.empty() else None


def detect_faces(img):
    """
    动漫人脸检测（LBP Cascade）
    返回 [(source, x, y, w, h), ...]
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


# ==================== 人体/手指检测 (MediaPipe) ====================
def detect_pose(img):
    """
    MediaPipe Pose 检测人体关键点。
    返回 landmarks 列表或 None（未安装MediaPipe时返回None）。
    """
    mp = _get_mediapipe()
    if mp is None:
        return None

    try:
        with mp.solutions.pose.Pose(
            static_image_mode=True,
            model_complexity=1,
            min_detection_confidence=0.5,
        ) as pose:
            results = pose.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            return results.pose_landmarks if results and results.pose_landmarks else None
    except Exception:
        return None


def detect_hands(img):
    """
    MediaPipe Hands 检测手部。
    返回 [(hand_idx, landmarks), ...] 或 None。
    """
    mp = _get_mediapipe()
    if mp is None:
        return None

    try:
        with mp.solutions.hands.Hands(
            static_image_mode=True,
            max_num_hands=2,
            min_detection_confidence=0.5,
        ) as hands:
            results = hands.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            if results and results.multi_hand_landmarks:
                return list(enumerate(results.multi_hand_landmarks))
            return []
    except Exception:
        return None


# ==================== 文字/水印检测 (MSER + 关键词) ====================
AI_WATERMARK_KEYWORDS = [
    "ai", "generated", "midjourney", "stable diffusion", "dall-e",
    "artificial intelligence", "created by ai", "image by ai",
]


def detect_text_regions(img):
    """
    使用 MSER 检测疑似文本/水印区域。
    针对动漫/AI绘图优化：收紧过滤条件，减少色块误报。
    返回 (regions_count, suspicious_score, detected_keywords)
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]

    # 仅检测边缘区域（水印通常在角落或边缘）
    edge_mask = np.zeros((h, w), dtype=np.uint8)
    margin = min(h, w) // 10  # 边缘条带
    edge_mask[:margin, :] = 1        # 上
    edge_mask[-margin:, :] = 1       # 下
    edge_mask[:, :margin] = 1        # 左
    edge_mask[:, -margin:] = 1       # 右

    # MSER 检测
    mser = cv2.MSER_create(delta=3, min_area=30, max_area=8000, max_variation=0.15)
    regions, _ = mser.detectRegions(gray)

    if not regions or len(regions) == 0:
        return 0, 0.0, []

    suspicious = 0
    valid_regions = 0

    # 边缘密度图（用于判断文字区域）
    edges = cv2.Canny(gray, 50, 150)

    for region in regions:
        if len(region) < 4:
            continue

        hull = cv2.convexHull(region.reshape(-1, 1, 2))
        x, y, bw, bh = cv2.boundingRect(hull)
        if bw < 6 or bh < 6 or bw > w * 0.6 or bh > h * 0.2:
            continue

        aspect = bw / max(bh, 1)
        # 文字区域：横排 (aspect > 2) 或竖排 (aspect < 0.5)
        is_horizontal_text = aspect > 2.0
        is_vertical_text = aspect < 0.5
        if not (is_horizontal_text or is_vertical_text):
            continue

        # 检查区域与边缘条带重叠（水印通常在边缘）
        roi_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(roi_mask, [hull], 1)
        edge_overlap = cv2.countNonZero(cv2.bitwise_and(roi_mask, edge_mask))
        is_on_edge = edge_overlap > 0

        # 颜色一致性 + 边缘密度
        roi = img[y:y+bh, x:x+bw]
        roi_gray = gray[y:y+bh, x:x+bw]
        if roi.size == 0 or roi_gray.size == 0:
            continue

        color_std = np.std(roi.reshape(-1, 3), axis=0).mean()
        if color_std > 60:  # 颜色变化太大，不像文字
            continue

        edge_density = edges[y:y+bh, x:x+bw].mean() / 255.0
        if edge_density < 0.05:  # 边缘太少，不像文字
            continue

        # 二值化后黑白对比度（文字通常是高对比度）
        _, binary = cv2.threshold(roi_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        white_ratio = (binary == 255).sum() / binary.size
        if not (0.1 < white_ratio < 0.9):  # 文字应该黑白分明
            continue

        valid_regions += 1
        if is_on_edge:
            suspicious += 1

    # 尝试OCR检测常见AI水印词（仅对边缘区域）
    keywords_found = []
    try:
        import pytesseract
        # 只OCR底部边缘区域（常见水印位置）
        bottom_h = max(1, h // 8)
        bottom_roi = gray[-bottom_h:, :]
        text = pytesseract.image_to_string(bottom_roi, lang="eng").lower()
        for kw in AI_WATERMARK_KEYWORDS:
            if kw in text:
                keywords_found.append(kw)
        # 顶部边缘也检测
        top_roi = gray[:bottom_h, :]
        text = pytesseract.image_to_string(top_roi, lang="eng").lower()
        for kw in AI_WATERMARK_KEYWORDS:
            if kw in text and kw not in keywords_found:
                keywords_found.append(kw)
    except Exception:
        pass

    # 可疑分数：边缘区域占比 + 发现关键词
    score = (suspicious / max(valid_regions, 1)) * 0.5 + (1.0 if keywords_found else 0.0)
    return valid_regions, min(score, 1.0), keywords_found


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
        "min_face_local_sharpness_ratio": 0.3,  # 人脸清晰度/全图清晰度 最低比例（太低=面部糊/变形）
        "max_face_color_std": 60.0,  # 人脸区域色彩标准差上限（太高=色块/伪影）
        "min_resolution": (480, 640),
        "min_aspect_ratio": 0.45,
        "max_aspect_ratio": 0.75,
        "min_filesize_kb": 30,
        # 文字/水印（收紧阈值，避免动漫色块误报）
        "max_text_regions": 12,     # 疑似文字区域上限
        "max_watermark_score": 0.6, # 水印可疑分数
        # 画风一致性
        "max_brightness_diff": 25, # 亮度极差
        "max_saturation_diff": 20, # 饱和度极差
    },
    "video": {
        "min_sharpness": 20,
        "max_blur_pct": 0.3,
        "max_interframe_diff": 80,  # 帧间差异骤变（闪烁/跳帧）
        "max_face_pos_drift": 0.60, # 人脸位置帧间漂移（人物移动导致，放宽到60%）
        "max_face_ratio_change": 0.25, # 人脸宽高比帧间变化（>25%=面部变形）
    },
}

# 人体合理角度范围（弧度）用于肢体扭曲检测
LIMB_ANGLE_LIMITS = {
    "elbow": (0.0, 3.14),      # 肘部0-180度
    "knee": (0.0, 2.8),        # 膝盖0-160度（避免反关节）
    "shoulder": (0.0, 3.14),   # 肩膀
    "hip": (0.0, 3.14),        # 髋部
}


def _angle_between(p1, p2, p3):
    """计算三点形成的角度 (p2为顶点)"""
    a = np.array([p1.x, p1.y])
    b = np.array([p2.x, p2.y])
    c = np.array([p3.x, p3.y])
    ba = a - b
    bc = c - b
    cos_angle = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    cos_angle = np.clip(cos_angle, -1.0, 1.0)
    return np.arccos(cos_angle)


def check_face_deformation(img, face):
    """
    检测单个人脸区域的变形迹象。
    返回 issues 列表 和 scores 字典。
    """
    h, w = img.shape[:2]
    source, fx, fy, fw, fh = face
    issues = []
    scores = {}

    # 1. 宽高比（已有）
    face_ratio = fw / max(fh, 1)
    scores["face_aspect"] = round(face_ratio, 2)
    min_ar = THRESHOLDS["image"]["min_face_aspect"]
    max_ar = THRESHOLDS["image"]["max_face_aspect"]
    if face_ratio < min_ar or face_ratio > max_ar:
        issues.append(f"人脸变形(宽高比{face_ratio:.2f}, 正常{min_ar}-{max_ar})")

    # 2. 人脸局部清晰度 vs 全图清晰度
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    global_sharp = cv2.Laplacian(gray, cv2.CV_64F).var()

    face_x1, face_y1 = max(0, fx), max(0, fy)
    face_x2, face_y2 = min(w, fx + fw), min(h, fy + fh)
    face_gray = gray[face_y1:face_y2, face_x1:face_x2]
    if face_gray.size > 0:
        face_sharp = cv2.Laplacian(face_gray, cv2.CV_64F).var()
        scores["face_sharpness"] = round(face_sharp, 1)
        ratio = face_sharp / (global_sharp + 1e-6)
        scores["face_sharpness_ratio"] = round(ratio, 2)
        if ratio < THRESHOLDS["image"]["min_face_local_sharpness_ratio"]:
            issues.append(f"面部模糊/变形(清晰度比{ratio:.2f})")

    # 3. 人脸区域色彩异常（AI色块/伪影）
    face_color = img[face_y1:face_y2, face_x1:face_x2]
    if face_color.size > 0:
        color_std = np.std(face_color.reshape(-1, 3), axis=0).mean()
        scores["face_color_std"] = round(float(color_std), 1)
        if color_std > THRESHOLDS["image"]["max_face_color_std"]:
            issues.append(f"面部色彩异常(伪影/色块)")

    return issues, scores


def check_fingers(img):
    """
    使用 MediaPipe Hands 检测手指。
    返回 (issues, scores)。如果 MediaPipe 未安装，返回 (["手指检测需安装 mediapipe"], {})。
    """
    hands = detect_hands(img)
    if hands is None:
        return ["手指检测: 未安装 mediapipe (pip install mediapipe)"], {"mp_installed": False}

    issues = []
    scores = {"mp_installed": True, "hand_count": len(hands)}

    mp = _get_mediapipe()

    for idx, landmarks in hands:
        # MediaPipe Hands 有 21 个关键点，手指尖为 4,8,12,16,20
        # 简单检测：计算指尖是否可见（在图片范围内且置信度足够）
        visible_tips = 0
        tip_indices = [4, 8, 12, 16, 20]  # 拇指、食指、中指、无名指、小指
        for tip in tip_indices:
            lm = landmarks.landmark[tip]
            if lm.visibility > 0.5 if hasattr(lm, "visibility") else True:
                visible_tips += 1

        scores[f"hand_{idx}_visible_tips"] = visible_tips

        # 如果检测到超过5个可见指尖（不太可能）或异常少
        if visible_tips > 5:
            issues.append(f"手部{idx+1}: 疑似多指({visible_tips}个指尖)")

        # 通过手指长度比例检测异常
        # 计算食指近端关节(5)到指尖(8)的长度
        p5 = landmarks.landmark[5]
        p8 = landmarks.landmark[8]
        p0 = landmarks.landmark[0]  # 手腕
        finger_len = np.linalg.norm([p8.x - p5.x, p8.y - p5.y])
        hand_len = np.linalg.norm([p0.x - p5.x, p0.y - p5.y]) + 1e-6
        if finger_len / hand_len > 2.0:
            issues.append(f"手部{idx+1}: 手指比例异常(过长)")

    return issues, scores


def check_limbs(img):
    """
    使用 MediaPipe Pose 检测肢体扭曲。
    返回 (issues, scores)。如果未安装MediaPipe，返回提示。
    """
    landmarks = detect_pose(img)
    if landmarks is None:
        # 未检测到人体 或 MediaPipe 未安装
        mp = _get_mediapipe()
        if mp is None:
            return ["肢体检测: 未安装 mediapipe (pip install mediapipe)"], {"mp_installed": False}
        return [], {"mp_installed": True, "body_detected": False}

    issues = []
    scores = {"mp_installed": True, "body_detected": True}
    lm = landmarks.landmark

    # 关节角度检查（左右分别）
    # 左肘: 11-13-15 (肩-肘-腕)
    # 右肘: 12-14-16
    # 左膝: 23-25-27 (髋-膝-踝)
    # 右膝: 24-26-28
    joints = [
        ("left_elbow", 11, 13, 15, "elbow"),
        ("right_elbow", 12, 14, 16, "elbow"),
        ("left_knee", 23, 25, 27, "knee"),
        ("right_knee", 24, 26, 28, "knee"),
    ]

    for name, i1, i2, i3, joint_type in joints:
        # 确保关键点可见（z不判断，x,y在0-1范围内即认为有效）
        p1, p2, p3 = lm[i1], lm[i2], lm[i3]
        if not all(0.0 < p.x < 1.0 and 0.0 < p.y < 1.0 for p in (p1, p2, p3)):
            continue
        angle = _angle_between(p1, p2, p3)
        scores[f"{name}_angle"] = round(np.degrees(angle), 1)
        min_a, max_a = LIMB_ANGLE_LIMITS.get(joint_type, (0.0, 3.14))
        if angle < min_a or angle > max_a:
            issues.append(f"肢体扭曲: {name}角度异常({np.degrees(angle):.0f}°)")
        # 特别检查：反关节（角度极小但不应该）
        if angle < 0.3 and joint_type in ("elbow", "knee"):
            issues.append(f"肢体扭曲: {name}疑似反关节({np.degrees(angle):.0f}°)")

    # 左右对称性检查（肩-髋水平线差异）
    left_shoulder = lm[11]
    right_shoulder = lm[12]
    left_hip = lm[23]
    right_hip = lm[24]
    if all(0.0 < p.x < 1.0 for p in (left_shoulder, right_shoulder, left_hip, right_hip)):
        shoulder_slope = abs(left_shoulder.y - right_shoulder.y)
        hip_slope = abs(left_hip.y - right_hip.y)
        scores["shoulder_level_diff"] = round(shoulder_slope, 3)
        scores["hip_level_diff"] = round(hip_slope, 3)
        # 左右肩/髋严重不对称可能表示肢体扭曲
        if shoulder_slope > 0.15 or hip_slope > 0.15:
            issues.append(f"肢体扭曲: 身体严重歪斜(肩差{shoulder_slope:.2f}/髋差{hip_slope:.2f})")

    return issues, scores


def check_image(filepath):
    """多维图片质量检测（含AI生成5维专项）"""
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

    # 6. 人脸检测 + 面部变形专项
    faces = detect_faces(img)
    scores["face_count"] = len(faces)
    if faces:
        # 选最大的人脸检查
        best = max(faces, key=lambda f: f[3] * f[4])
        if len(faces) > THRESHOLDS["image"]["max_face_count"]:
            issues.append(f"人脸过多({len(faces)}张)")

        face_issues, face_scores = check_face_deformation(img, best)
        issues.extend(face_issues)
        scores.update(face_scores)
    else:
        scores["face_aspect"] = 0
        scores["face_source"] = "none"
        scores["face_sharpness"] = 0
        scores["face_sharpness_ratio"] = 0
        scores["face_color_std"] = 0

    # 7. 手指检测
    finger_issues, finger_scores = check_fingers(img)
    # 手指检测未安装时仅作为提示，不阻断
    scores.update(finger_scores)
    if finger_issues and finger_scores.get("mp_installed"):
        issues.extend(finger_issues)
    elif finger_issues and not finger_scores.get("mp_installed"):
        scores["finger_note"] = "未安装 mediapipe，跳过手指检测"

    # 8. 肢体扭曲检测
    limb_issues, limb_scores = check_limbs(img)
    scores.update(limb_scores)
    if limb_issues and limb_scores.get("mp_installed"):
        issues.extend(limb_issues)
    elif limb_issues and not limb_scores.get("mp_installed"):
        scores["limb_note"] = "未安装 mediapipe，跳过肢体检测"

    # 9. AI文字/水印检测
    text_regions, watermark_score, keywords = detect_text_regions(img)
    scores["text_regions"] = text_regions
    scores["watermark_score"] = round(watermark_score, 2)
    if keywords:
        issues.append(f"AI水印文字: {', '.join(keywords)}")
    if text_regions > THRESHOLDS["image"]["max_text_regions"]:
        issues.append(f"疑似AI乱码文字({text_regions}处)")
    if watermark_score > THRESHOLDS["image"]["max_watermark_score"]:
        issues.append(f"水印可疑({watermark_score:.2f})")

    # 10. 分辨率 + 宽高比 + 文件大小
    if h < THRESHOLDS["image"]["min_resolution"][0] or w < THRESHOLDS["image"]["min_resolution"][1]:
        issues.append(f"分辨率过低{w}×{h}")
    ratio = w / h if h > w else h / w
    if ratio < THRESHOLDS["image"]["min_aspect_ratio"] or ratio > THRESHOLDS["image"]["max_aspect_ratio"]:
        issues.append(f"宽高比异常{w/h:.2f}")
    if size_kb < THRESHOLDS["image"]["min_filesize_kb"]:
        issues.append(f"文件过小{size_kb:.0f}KB")

    # 亮度/饱和度（用于画风一致性）
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    scores["brightness"] = round(float(np.mean(hsv[:, :, 2])), 1)
    scores["saturation"] = round(float(np.mean(hsv[:, :, 1])), 1)

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

    # 风格一致性：色偏一致性 + 亮度一致性 + 饱和度一致性
    consistency_issues = []
    if len(results) > 1:
        casts = [r["scores"].get("color_cast", 0) for r in results]
        centers = [r["scores"].get("center_attention", 0) for r in results]
        brightnesses = [r["scores"].get("brightness", 0) for r in results]
        saturations = [r["scores"].get("saturation", 0) for r in results]

        if max(casts) - min(casts) > 4:
            consistency_issues.append(f"色偏不一致(极差{max(casts)-min(casts):.0f})")
        if max(centers) - min(centers) > 0.5:
            consistency_issues.append(f"构图不一致")
        if max(brightnesses) - min(brightnesses) > THRESHOLDS["image"]["max_brightness_diff"]:
            consistency_issues.append(f"亮度不一致(极差{max(brightnesses)-min(brightnesses):.0f})")
        if max(saturations) - min(saturations) > THRESHOLDS["image"]["max_saturation_diff"]:
            consistency_issues.append(f"饱和度不一致(极差{max(saturations)-min(saturations):.0f})")

    return results, passed, len(results), consistency_issues


def check_video(filepath, sample_frames=8):
    """视频质量检测：帧模糊率 + 帧间一致性 + 人脸稳定性"""
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
    last_face = None
    face_drifts = []
    face_ratio_changes = []

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
        h, w = img.shape[:2]

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

        # 人脸稳定性检测（帧间人脸框宽高比变化 + 位置漂移）
        faces = detect_faces(img)
        if faces:
            cur = max(faces, key=lambda f: f[3]*f[4])
            cur_cx = (cur[1] + cur[3]/2) / w
            cur_cy = (cur[2] + cur[4]/2) / h
            cur_ratio = cur[3] / max(cur[4], 1)

            if last_face is not None:
                prev_cx, prev_cy, prev_ratio = last_face
                # 位置漂移（镜头运动导致，阈值放宽）
                drift = np.linalg.norm([cur_cx - prev_cx, cur_cy - prev_cy])
                face_drifts.append(drift)
                # 宽高比变化（面部变形更敏感指标）
                ratio_change = abs(cur_ratio - prev_ratio) / max(prev_ratio, 0.1)
                face_ratio_changes.append(ratio_change)
            last_face = (cur_cx, cur_cy, cur_ratio)
        else:
            last_face = None

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

    scores = {}

    # 人脸位置漂移（宽松：人物可能在画面中移动）
    if face_drifts:
        max_drift = max(face_drifts)
        avg_drift = np.mean(face_drifts)
        scores["max_face_drift"] = round(max_drift, 3)
        scores["avg_face_drift"] = round(avg_drift, 3)
        if max_drift > THRESHOLDS["video"]["max_face_pos_drift"]:
            issues.append(f"人脸位置大幅变化(漂移{max_drift:.2f})")

    # 人脸宽高比变化（敏感：面部变形指标）
    if face_ratio_changes:
        max_ratio_change = max(face_ratio_changes)
        avg_ratio_change = np.mean(face_ratio_changes)
        scores["max_face_ratio_change"] = round(max_ratio_change, 3)
        scores["avg_face_ratio_change"] = round(avg_ratio_change, 3)
        if max_ratio_change > THRESHOLDS["video"]["max_face_ratio_change"]:
            issues.append(f"面部变形(宽高比突变{max_ratio_change:.2f})")

    return {
        "file": name,
        "duration_s": duration_s,
        "frames": n,
        "blur_pct": round(blur_pct, 2),
        "avg_sharpness": round(np.mean(sharpnesses), 1) if sharpnesses else 0,
        "pass": len(issues) == 0,
        "issues": issues,
        "scores": scores,
    }


def format_report(results, passed, total, consistency=None):
    """格式化的质检报告"""
    header = f"{'='*60}"
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
            if scores.get("text_regions", 0) > 0:
                detail += f"文字区:{scores.get('text_regions')} "
            if scores.get("watermark_score", 0) > 0:
                detail += f"水印:{scores.get('watermark_score',0):.2f} "
            detail += f"| {r['size_kb']}KB"
        lines.append(f"  {icon} {r['file']} {detail}")
        for issue in r.get("issues", []):
            lines.append(f"     ⚠️  {issue}")

    if consistency:
        lines.append(f"  💡 风格一致性:")
        for c in consistency:
            lines.append(f"     ℹ️  {c}")

    lines.append(f"\n  📊 通过: {passed}/{total}")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="七维质量检测 - Director Gate")
    parser.add_argument("--type", choices=["image", "video"], required=True)
    parser.add_argument("--file", help="单文件")
    parser.add_argument("--dir", help="目录")
    parser.add_argument("--output", help="JSON报告输出")
    parser.add_argument("--frames", type=int, default=8, help="视频采样帧数")

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
