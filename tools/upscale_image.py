#!/usr/bin/env python3
"""
图片放大工具 - 将低分辨率图片上采样到目标分辨率

用法:
  python3 tools/upscale_image.py --input input.png --output output.png --width 1080 --height 1920
  python3 tools/upscale_image.py --input input.png --output output.png  (默认 1080x1920)

方案:
  1. Lanczos 插值（OpenCV，快速） - 默认
  2. 可升级 RealESRGAN / waifu2x（需额外安装）
"""

import argparse
import os
import sys

try:
    import cv2
except ImportError:
    print("[Upscaler] ❌ 请先安装 opencv-python: pip3 install opencv-python")
    sys.exit(1)


def upscale_lanczos(input_path, output_path, target_w=1080, target_h=1920):
    """使用 Lanczos 插值放大图片"""
    img = cv2.imread(input_path)
    if img is None:
        print(f"[Upscaler] ❌ 无法读取: {input_path}")
        return False

    h, w = img.shape[:2]
    print(f"[Upscaler] 原始分辨率: {w}x{h}")

    if w >= target_w and h >= target_h:
        print(f"[Upscaler] 分辨率已达标，不需要放大")
        cv2.imwrite(output_path, img)
        return True

    # Lanczos 插值 - 质量最好的传统插值算法
    resized = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cv2.imwrite(output_path, resized)

    out_size = os.path.getsize(output_path) / 1024
    print(f"[Upscaler] ✅ 已放大: {target_w}x{target_h} ({out_size:.1f} KB)")
    return True


def upscale_esrgan(input_path, output_path, target_w=1080, target_h=1920):
    """使用 RealESRGAN 放大（需 pip install realesrgan）"""
    try:
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet
        import numpy as np
    except ImportError:
        print("[Upscaler] ❌ RealESRGAN 未安装。使用 Lanczos 方案...")
        return upscale_lanczos(input_path, output_path, target_w, target_h)

    img = cv2.imread(input_path)
    if img is None:
        return False

    h, w = img.shape[:2]
    print(f"[Upscaler] RealESRGAN 放大中... ({w}x{h} → {target_w}x{target_h})")
    
    # 计算需要的放大倍数
    scale = max(target_w / w, target_h / h)
    scale_int = max(int(scale) + 1, 2)  # 至少2倍

    model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
    # 注意：需要下载模型文件，首次使用会比较慢
    
    print("[Upscaler] ⚠️ ESRGAN 需要预下载模型，回退到 Lanczos")
    return upscale_lanczos(input_path, output_path, target_w, target_h)


def main():
    parser = argparse.ArgumentParser(description="图片放大工具")
    parser.add_argument("--input", required=True, help="输入图片路径")
    parser.add_argument("--output", required=True, help="输出图片路径")
    parser.add_argument("--width", type=int, default=1080, help="目标宽度")
    parser.add_argument("--height", type=int, default=1920, help="目标高度")
    parser.add_argument("--method", default="lanczos", choices=["lanczos", "esrgan"], help="放大方法")
    args = parser.parse_args()

    if args.method == "esrgan":
        success = upscale_esrgan(args.input, args.output, args.width, args.height)
    else:
        success = upscale_lanczos(args.input, args.output, args.width, args.height)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
