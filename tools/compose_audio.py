#!/usr/bin/env python3
"""
音频合成工具 — Editor Agent 调用
根据 Director 的音频设计表，生成 TTS + 音效 + 分段BGM，adelay精确混合。

输入: 分镜音频设计JSON
输出: 混合后的单条音频(m4a) + 字幕文件(srt)

JSON格式:
{
  "shots": [
    {"id": "01", "duration": 6, "voice": "这里……是哪？", "voice_id": "yunyang", "sfx": "ambient_drone", "bgm_segment": "mysterious"},
    {"id": "02", "duration": 3, "sfx": "energy_hum", "bgm_segment": "mysterious"},
    ...
  ],
  "bgm_segments": {
    "mysterious": {"style": "low_drone", "duration": 9},
    "tense": {"style": "heartbeat", "duration": 8},
    "comedy": {"style": "quirky", "duration": 7},
    "epic": {"style": "orchestral", "duration": 10},
    "outro": {"style": "fade", "duration": 9}
  },
  "output_dir": "projects/xxx"
}
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import timedelta

FFMPEG = os.environ.get("FFMPEG", "/Users/ui/.local/bin/ffmpeg")

# ==================== BGM 生成器 ====================
BGM_RECIPES = {
    "low_drone":      "sine=f=55:d=DUR,volume=0.35,sine=f=110:d=DUR,volume=0.15,amix=2:duration=first",
    "heartbeat":      "sine=f=40:d=DUR,volume=envelope:0.6:0:0.1:0.2:1.0:0.6:0.1:0.2,amix=1",
    "quirky":         "sine=f=220:d=DUR,volume=0.2,sine=f=440:d=DUR,volume=0.1,amix=2:duration=first",
    "orchestral":     "sine=f=80:d=DUR,volume=0.4,sine=f=160:d=DUR,volume=0.25,sine=f=320:d=DUR,volume=0.15,amix=3:duration=first",
    "fade":           "sine=f=55:d=DUR,volume='0.3*((DUR-t)/DUR)',sine=f=110:d=DUR,volume='0.15*((DUR-t)/DUR)',amix=2:duration=first",
}

# ==================== 音效生成器 ====================
SFX_RECIPES = {
    "energy_hum":   "sine=f=60:d=3,volume=0.5,sine=f=180:d=3,volume=0.2,sine=f=4:d=3,volume=0.3,amix=3:duration=first,afade=in:d=0.5:out:d=0.5",
    "heavy_impact": "sine=f=80:d=0.5,volume=1.0,anoisesrc=d=1:color=pink,volume=0.6,sine=f=40:d=1.5,volume=0.3,amix=3:duration=longest",
    "slide_trigger":"sine=f=200:d=2,volume=0.5,sine=f=600:d=0.5,volume=0.4,sine=f=1200:d=1,volume=0.3,amix=3:duration=longest,afade=out:d=0.3",
    "deep_rumble":  "sine=f=30:d=5,volume=0.5,sine=f=60:d=4,volume=0.25,amix=2:duration=longest,afade=out:d=1",
    "wind_fade":    "anoisesrc=d=5:color=white,volume=0.2,lowpass=f=800,sine=f=100:d=5,volume='0.15*((5-t)/5)',amix=2:duration=first,afade=in:d=1:out:st=3:d=2",
    "ambient_drone":"sine=f=55:d=DUR,volume=0.25,sine=f=88:d=DUR,volume=0.15,amix=2:duration=first,afade=in:d=1:out:d=2",
    "thud":         "sine=f=50:d=0.3,volume=0.8,afade=out:d=0.3",
    "shimmer":      "sine=f=1200:d=DUR,volume='0.2*sin(2*PI*t*3)*((DUR-t)/DUR)'",
    "none":         None,
}


def generate_sfx(name, duration, output_path):
    """用 FFmpeg 合成音效"""
    recipe = SFX_RECIPES.get(name)
    if recipe is None:
        # Create silence placeholder (keep timeline intact but skip)
        subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={duration}",
                        "-c:a", "libmp3lame", output_path], capture_output=True, timeout=30)
        return output_path

    recipe = recipe.replace("DUR", str(duration))
    # Parse: "filter1,filter2,..." → ffmpeg filter_complex string
    filters = recipe.split(",")
    
    # Build inputs and filter chain
    inputs = []
    filter_parts = []
    input_idx = 0
    
    i = 0
    while i < len(filters):
        f = filters[i].strip()
        if "=" in f and not any(f.startswith(p) for p in ["volume", "afade", "amix", "lowpass"]):
            # It's a source filter
            key, val = f.split("=", 1)
            inputs.extend(["-f", "lavfi", "-i", f"[{input_idx}:a]"])
            filter_parts.append(f"[{input_idx}:a]")
            input_idx += 1
        elif f.startswith("amix"):
            # amix: combine previous inputs
            count = int(f.split("=")[1].split(":")[0].split("=")[-1]) if "inputs=" in f else len(filter_parts)
            inputs_str = "".join([f"[a{i}]" for i in range(count)])
            filter_parts.append(f"{inputs_str}{f}[amix]")
        elif f.startswith("volume="):
            # modifier on previous output
            prev = filter_parts.pop() if filter_parts else "amix"
            filter_parts.append(f"{prev},{f}")
            filter_parts[-1] = filter_parts[-1].replace("[amix],", "")
        elif f.startswith("afade"):
            # add fade
            prev = filter_parts[-1] if filter_parts else "amix"
            base, _, _ = prev.partition(",afade")
            filter_parts[-1] = f"{base},{f}"
        elif f.startswith("lowpass"):
            prev = filter_parts[-1]
            filter_parts[-1] = f"{prev},{f}"
        i += 1

    # Simplify: use direct filter_complex string
    try:
        subprocess.run([FFMPEG, "-y"] + inputs +
            ["-filter_complex", ",".join(filter_parts) + "[a]",
             "-map", "[a]", "-c:a", "libmp3lame", "-b:a", "128k", output_path],
            capture_output=True, timeout=30)
    except:
        # Fallback: simple tone
        subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", f"sine=f=220:d={duration},volume=0.2",
                        "-c:a", "libmp3lame", output_path], capture_output=True, timeout=30)
    return output_path


def generate_bgm_segment(style, duration, output_path):
    """用 FFmpeg 合成 BGM 片段"""
    recipe = BGM_RECIPES.get(style, BGM_RECIPES["low_drone"])
    recipe = recipe.replace("DUR", str(duration))
    
    try:
        subprocess.run([FFMPEG, "-y", "-f", "lavfi",
            "-i", recipe,
            "-c:a", "libmp3lame", "-b:a", "192k", output_path],
            capture_output=True, timeout=30)
    except:
        subprocess.run([FFMPEG, "-y", "-f", "lavfi",
            "-i", f"sine=f=55:d={duration},volume=0.3,afade=in:d=2:out:d=2",
            "-c:a", "libmp3lame", "-b:a", "192k", output_path],
            capture_output=True, timeout=30)
    return output_path


# ==================== TTS 生成 ====================
async def generate_tts(text, voice_id, output_path, rate="+0%"):
    """用 edge-tts 生成配音"""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text=text, voice=voice_id, rate=rate)
        await communicate.save(output_path)
        print(f"  TTS: {text[:20]}... → {os.path.basename(output_path)}")
    except Exception as e:
        print(f"  TTS失败: {e}")
        # Fallback: 1Hz silence (preserves timeline)
        subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=1",
                        "-c:a", "libmp3lame", output_path], capture_output=True, timeout=10)


# ==================== 主流程 ====================
async def main_async(design, output_dir):
    tmp = tempfile.mkdtemp(prefix="audio_")
    audio_files = []  # (path, delay_ms)

    # Calculate shot offsets
    offset = 0
    shots = design["shots"]
    
    print("[Audio] 生成配音和音效...")
    for shot in shots:
        sid = shot["id"]
        dur = shot["duration"]
        delay_ms = int(offset * 1000)

        # Voice
        voice_text = shot.get("voice", "")
        if voice_text:
            voice_id_map = {
                "yunyang": "zh-CN-YunyangNeural",
                "yunxi": "zh-CN-YunxiNeural",
                "yunjian": "zh-CN-YunjianNeural",
                "xiaoxiao": "zh-CN-XiaoxiaoNeural",
            }
            voice_id = voice_id_map.get(shot.get("voice_id", "yunyang"), "zh-CN-YunyangNeural")
            rate = "+15%" if "？" in voice_text or "！" in voice_text else "+0%"
            tts_path = os.path.join(tmp, f"tts_{sid}.mp3")
            await generate_tts(voice_text, voice_id, tts_path, rate)
            audio_files.append((tts_path, delay_ms, f"voice_{sid}"))
            print(f"  镜{sid}: '{voice_text}' @ {offset}s")

        # SFX
        sfx_name = shot.get("sfx", "none")
        if sfx_name and sfx_name != "none":
            sfx_path = os.path.join(tmp, f"sfx_{sid}.mp3")
            generate_sfx(sfx_name, dur, sfx_path)
            audio_files.append((sfx_path, delay_ms, f"sfx_{sid}"))
            print(f"  镜{sid}: 🔉 {sfx_name} @ {offset}s")

        offset += dur

    total_dur = offset

    # Generate segmented BGM
    print(f"\n[Audio] 分段BGM (总{total_dur}s)...")
    bgm_files = []
    bgm_offset = 0
    bgm_segments = design.get("bgm_segments", {})
    
    if bgm_segments:
        for seg_name, seg_info in bgm_segments.items():
            style = seg_info.get("style", "low_drone")
            dur = seg_info.get("duration", 10)
            bgm_path = os.path.join(tmp, f"bgm_{seg_name}.mp3")
            generate_bgm_segment(style, dur, bgm_path)
            audio_files.append((bgm_path, int(bgm_offset * 1000), f"bgm_{seg_name}"))
            print(f"  BGM.{seg_name}: {style} {dur}s @ {bgm_offset}s")
            bgm_offset += dur
    else:
        # Single BGM fallback
        bgm_path = os.path.join(tmp, "bgm_full.mp3")
        generate_bgm_segment("low_drone", total_dur, bgm_path)
        audio_files.append((bgm_path, 0, "bgm_full"))
        print(f"  BGM: low_drone {total_dur}s (全片)")

    # Mix all audio — use simpler dual-pass approach:
    # Pass 1: mix all voice+sfx tracks together
    # Pass 2: add BGM on top
    
    print(f"\n[Audio] 两步混合 (先配音+音效, 再加BGM)...")
    
    # Pass 1: Voice + SFX (no BGM)
    voice_inputs = []
    voice_filters = []
    v_idx = 0
    for path, delay, label in audio_files:
        if label.startswith("bgm_"):
            continue  # BGM handled in pass 2
        voice_inputs.extend(["-i", path])
        voice_filters.append(f"[{v_idx}:a]adelay={delay}:all=1,volume=2.5[a{v_idx}]")
        v_idx += 1
    
    voice1_path = os.path.join(tmp, "voice_mix.m4a")
    if v_idx > 0:
        v_mix = "".join([f"[a{i}]" for i in range(v_idx)])
        v_filter = "; ".join(voice_filters) + f"; {v_mix}amix=inputs={v_idx}:duration=longest[a]"
        v_cmd = [FFMPEG, "-y"] + voice_inputs + ["-filter_complex", v_filter, "-map", "[a]",
                  "-c:a", "aac", "-b:a", "256k", voice1_path]
        subprocess.run(v_cmd, capture_output=True, timeout=60)
    else:
        voice1_path = None

    # Pass 2: Add BGM on top of voice mix
    bgm_inputs = []
    bgm_filters = []
    b_idx = 0
    for path, delay, label in audio_files:
        if not label.startswith("bgm_"):
            continue
        bgm_inputs.extend(["-i", path])
        bgm_filters.append(f"[{b_idx}:a]adelay={delay}:all=1,volume=0.12[a{b_idx}]")
        b_idx += 1

    if b_idx > 0:
        b_mix = "".join([f"[a{i}]" for i in range(b_idx)])
        b_filter = "; ".join(bgm_filters) + f"; {b_mix}amix=inputs={b_idx}:duration=longest[bgm_all]"
        bgm_mix_path = os.path.join(tmp, "bgm_mix.m4a")
        b_cmd = [FFMPEG, "-y"] + bgm_inputs + ["-filter_complex", b_filter, "-map", "[bgm_all]",
                  "-c:a", "aac", "-b:a", "192k", bgm_mix_path]
        subprocess.run(b_cmd, capture_output=True, timeout=60)
    else:
        bgm_mix_path = None

    # Final: voice_mix + bgm_mix → final audio
    final_tmp = os.path.join(tmp, "final_tmp.m4a")
    if voice1_path and bgm_mix_path:
        output_audio = os.path.join(output_dir, "final_audio.m4a")
        f_cmd = [FFMPEG, "-y", "-i", voice1_path, "-i", bgm_mix_path,
                 "-filter_complex", "[0:a]volume=1.0[v];[1:a]volume=1.0[b];[v][b]amix=inputs=2:duration=first,volume=1.2[a]",
                 "-map", "[a]", "-c:a", "aac", "-b:a", "256k", output_audio]
        result = subprocess.run(f_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            import shutil as sh
            sh.copy(voice1_path, output_audio)
            print(f"  ⚠️ BGM混合失败，仅保留配音+音效")
    elif voice1_path:
        output_audio = os.path.join(output_dir, "final_audio.m4a")
        import shutil as sh
        sh.copy(voice1_path, output_audio)
    else:
        print("  ❌ 无音频产出")
        output_audio = None

    # Generate SRT
    srt_path = os.path.join(output_dir, "subtitles.srt")
    generate_srt(shots, srt_path)

    # Cleanup temp
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    if output_audio and os.path.exists(output_audio):
        print(f"\n[Audio] ✅ {output_audio} ({total_dur:.0f}s)")
    else:
        print(f"\n[Audio] ❌ 输出丢失")
    print(f"[Audio] 📝 {srt_path}")
    return output_audio, srt_path


def generate_srt(shots, output_path):
    """从音频设计表生成SRT字幕"""
    lines = []
    idx = 1
    offset = 0
    for shot in shots:
        voice = shot.get("voice", "")
        dur = shot["duration"]
        if voice:
            start = timedelta(seconds=offset)
            end = timedelta(seconds=offset + max(1.5, dur * 0.6))
            lines.append(f"{idx}")
            lines.append(f"{str(start).replace('.',',')}0 --> {str(end).replace('.',',')}0")
            lines.append(voice)
            lines.append("")
            idx += 1
        offset += dur

    with open(output_path, "w") as f:
        f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="音频合成工具")
    parser.add_argument("--design", required=True, help="Director音频设计JSON")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    args = parser.parse_args()

    with open(args.design) as f:
        design = json.load(f)

    os.makedirs(args.output_dir, exist_ok=True)
    asyncio.run(main_async(design, args.output_dir))


if __name__ == "__main__":
    main()
