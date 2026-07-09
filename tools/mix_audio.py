#!/usr/bin/env python3
"""
标准化混音工具 — Editor Agent 核心工具

音量标准（LUFS）:
  人声(narrator):     -12 dB LUFS  绝对主导
  音效(sfx):          -24 dB LUFS  辅助，不抢人声
  BGM(music):         -30 dB LUFS  隐约背景
  打击点(hit):        -18 dB LUFS  短暂强调

用法:
  python3 tools/mix_audio.py \
    --narrator audio/narr_01.mp3 --delay 0 \
    --narrator audio/narr_02.mp3 --delay 6000 \
    --sfx audio/stream.mp3 --sfx audio/bite.mp3 --delay 6500 \
    --bgm audio/piano.mp3 \
    --duration 16000 --output audio/final_mix.mp3
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

# ==================== 音量标准 ====================
LUFS = {
    "narrator":  -12,   # 人声绝对主导
    "sfx":       -24,   # 辅助音效
    "bgm":       -30,   # 隐约背景
    "hit":       -18,   # 打击点强调
}


def normalize_loudness(input_path, output_path, target_lufs):
    """用 loudnorm 归一化到目标 LUFS"""
    subprocess.run([FFMPEG, "-y", "-i", input_path,
        "-af", f"loudnorm=I={target_lufs}:LRA=7:TP=-1:linear=true",
        "-c:a", "libmp3lame", "-b:a", "192k", output_path],
        capture_output=True, check=True)


def get_duration_ms(filepath):
    """获取音频时长（毫秒）"""
    result = subprocess.run([FFMPEG, "-i", filepath],
        capture_output=True, text=True)
    for line in (result.stdout + result.stderr).split("\n"):
        if "Duration" in line:
            h, m, s = line.split(",")[0].split(":")[1:]
            return int(float(h) * 3600000 + float(m) * 60000 + float(s) * 1000)
    return 1000


def mix(args):
    """
    标准化混音流程：
    1. 所有输入按类型 loudnorm 归一化
    2. 按时序延迟排列
    3. amix 混合，人声绝对优先
    """
    tmpdir = tempfile.mkdtemp(prefix="mix_")
    inputs = []
    filter_parts = []
    idx = 0

    # --- 收集并归一化所有输入 ---
    all_entries = []

    # 人声
    for i, (path, delay) in enumerate(args.narrators):
        norm_path = os.path.join(tmpdir, f"norm_narr_{i}.mp3")
        normalize_loudness(path, norm_path, LUFS["narrator"])
        all_entries.append(("narrator", norm_path, delay))
        print(f"  🎙️ 人声 {i+1}: {os.path.basename(path)} → -12dB LUFS, delay={delay}ms")

    # 音效
    for i, (path, delay) in enumerate(args.sfxs):
        norm_path = os.path.join(tmpdir, f"norm_sfx_{i}.mp3")
        normalize_loudness(path, norm_path, LUFS["sfx"])
        all_entries.append(("sfx", norm_path, delay))
        print(f"  🔉 音效 {i+1}: {os.path.basename(path)} → -24dB LUFS, delay={delay}ms")

    # 打击点
    for i, (path, delay) in enumerate(args.hits):
        norm_path = os.path.join(tmpdir, f"norm_hit_{i}.mp3")
        normalize_loudness(path, norm_path, LUFS["hit"])
        all_entries.append(("hit", norm_path, delay))
        print(f"  💥 打击点 {i+1}: {os.path.basename(path)} → -18dB LUFS, delay={delay}ms")

    # BGM
    for i, (path, _) in enumerate(args.bgms):
        norm_path = os.path.join(tmpdir, f"norm_bgm_{i}.mp3")
        normalize_loudness(path, norm_path, LUFS["bgm"])
        all_entries.append(("bgm", norm_path, 0))
        print(f"  🎵 BGM {i+1}: {os.path.basename(path)} → -30dB LUFS")

    if not all_entries:
        print("❌ 无输入文件")
        sys.exit(1)

    # --- 构建 FFmpeg 命令 ---
    cmd = [FFMPEG, "-y"]
    filter_inputs = []
    filter_labels = []

    for i, (etype, path, delay) in enumerate(all_entries):
        cmd += ["-i", path]
        dur = get_duration_ms(path)
        label = f"{etype[0]}{i}"
        # adelay 示例: 3000ms → '3000|3000'（所有声道）
        adelay_str = f"{delay}|{delay}" if delay > 0 else ""
        if adelay_str:
            filter_inputs.append(f"[{i}:a]adelay={adelay_str}:all=1[{label}]")
        else:
            filter_inputs.append(f"[{i}:a]anull[{label}]")
        filter_labels.append(label)

    # amix 所有轨
    mix_inputs = "".join(f"[{l}]" for l in filter_labels)
    filter_inputs.append(f"{mix_inputs}amix=inputs={len(filter_labels)}:duration=longest,loudnorm=I=-14:LRA=7:TP=-1[a]")

    # 组装 filter_complex 并限制总时长
    filter_str = ";".join(filter_inputs)
    cmd += ["-filter_complex", filter_str]
    cmd += ["-map", "[a]", "-c:a", "libmp3lame", "-b:a", "192k"]
    if args.duration:
        cmd += ["-t", str(args.duration / 1000)]

    out_path = args.output
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    cmd.append(out_path)

    print(f"\n  🎚️ 混音中... ({len(filter_labels)}轨)")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ❌ FFmpeg 失败: {result.stderr[-300:]}")
        sys.exit(1)

    # --- 验证输出音量 ---
    verify = subprocess.run([FFMPEG, "-i", out_path, "-af", "volumedetect",
        "-f", "null", "/dev/null"], capture_output=True, text=True)
    for line in (verify.stdout + verify.stderr).split("\n"):
        if "mean_volume" in line:
            vol = float(line.split(":")[1].strip().split()[0])
            print(f"  📊 输出音量: {vol} dB")
            if vol < -25:
                print(f"  ⚠️  音量为 {vol}dB，低于 -25dB，可能听不清")
            elif vol > -6:
                print(f"  ⚠️  音量为 {vol}dB，高于 -6dB，可能失真")

    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print(f"  ✅ {os.path.basename(out_path)} ({size_mb:.1f}MB)")

    # 清理临时文件
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


class DelayArg:
    """存储所有输入和选项"""
    def __init__(self, duration=None, output=None):
        self.narrators = []
        self.sfxs = []
        self.hits = []
        self.bgms = []
        self.duration = duration
        self.output = output

    def add(self, type_, path, delay=0):
        getattr(self, type_ + "s").append((path, delay))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="标准化混音工具 - Editor Agent")
    parser.add_argument("--narrator", action="append", nargs=2, metavar=("PATH", "DELAY_MS"), default=[],
                        help="人声文件 延迟毫秒")
    parser.add_argument("--sfx", action="append", nargs=2, metavar=("PATH", "DELAY_MS"), default=[],
                        help="音效文件 延迟毫秒")
    parser.add_argument("--hit", action="append", nargs=2, metavar=("PATH", "DELAY_MS"), default=[],
                        help="打击点 延迟毫秒")
    parser.add_argument("--bgm", action="append", metavar="PATH", default=[],
                        help="BGM 文件")
    parser.add_argument("--duration", type=int, help="总时长（毫秒）")
    parser.add_argument("--output", required=True, help="输出文件")

    opts = parser.parse_args()

    args = DelayArg(duration=opts.duration, output=opts.output)
    for path, delay in opts.narrator:
        args.add("narrator", path, int(delay))
    for path, delay in opts.sfx:
        args.add("sfx", path, int(delay))
    for path, delay in opts.hit:
        args.add("hit", path, int(delay))
    for path in opts.bgm:
        args.add("bgm", path)

    print("mix_audio — 标准化混音")
    print("=" * 40)
    mix(args)
