#!/usr/bin/env python3
"""
音频工具 - AI BGM + 豆包 TTS + ElevenLabs 音效

用法:
  # 豆包 TTS 配音
  python3 tools/download_audio.py --type tts --text "夏日午后" --output audio/01.mp3

  # AI BGM（需 AIMUSIC_API_KEY + 积分）
  python3 tools/download_audio.py --type bgm --keyword "summer piano" --output audio/bgm.mp3

  # ElevenLabs 音效（免费 1万积分/月）
  python3 tools/download_audio.py --type sfx --keyword "watermelon bite crunch" --output audio/bite.mp3
"""

import argparse
import base64
import json
import os
import ssl
import sys
import time
import urllib.request

# macOS Python SSL workaround
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

DOUBAO_KEY = os.environ.get("DOUBAO_TTS_KEY", "")
AIMUSIC_KEY = os.environ.get("AIMUSIC_API_KEY", "")
ELEVENLABS_KEY = os.environ.get("ELEVENLABS_API_KEY", "")


def generate_tts(text, output_path, speaker="zh_female_vv_uranus_bigtts"):
    """火山豆包 TTS - 返回生成的 MP3 文件路径"""
    if not DOUBAO_KEY:
        print("[TTS] ❌ 未设置 DOUBAO_TTS_KEY")
        return None

    body = json.dumps({"req_params": {
        "text": text, "speaker": speaker,
        "audio_params": {"format": "mp3", "sample_rate": 24000},
    }}).encode()

    req = urllib.request.Request(
        "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
        data=body, headers={
            "Content-Type": "application/json",
            "X-Api-Key": DOUBAO_KEY,
            "X-Api-Resource-Id": "seed-tts-2.0",
            "X-Api-Connect-Id": "manju-tts",
        }, method="POST")

    print(f"[TTS] 🎙️ {text[:30]}...")
    resp = urllib.request.urlopen(req, timeout=30, context=_SSL_CTX)
    chunks = []
    for line in resp.read().decode(errors="replace").split("\n"):
        line = line.strip()
        if not line: continue
        try:
            d = json.loads(line)
            code = d.get("code")
            if code == 0 and d.get("data"):
                chunks.append(base64.b64decode(d["data"]))
            elif code == 20000000:
                break
        except (json.JSONDecodeError, base64.binascii.Error, TypeError):
            continue

    audio = b"".join(chunks)
    if not audio:
        print("[TTS] ❌ 无音频数据")
        return None

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(audio)
    print(f"[TTS] ✅ {os.path.basename(output_path)} ({len(audio)/1024:.0f}KB, ~{len(audio)/24000:.1f}s)")
    return output_path


def generate_bgm(keyword, output_path):
    """AI Music API 生成 BGM（需积分）"""
    if not AIMUSIC_KEY:
        print("[BGM] ❌ 未设置 AIMUSIC_API_KEY")
        return None

    body = json.dumps({
        "gpt_description_prompt": keyword,
        "make_instrumental": True,
        "model": "chirp-v5",
    }).encode()

    print(f"[BGM] 🎹 {keyword[:40]}...")
    req = urllib.request.Request("https://aimusicapi.org/api/v2/generate",
        data=body, headers={
            "Authorization": f"Bearer {AIMUSIC_KEY}",
            "Content-Type": "application/json",
        }, method="POST")

    try:
        data = json.loads(urllib.request.urlopen(req, timeout=20, context=_SSL_CTX).read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        msg = json.loads(body).get("message", f"HTTP {e.code}") if body else f"HTTP {e.code}"
        print(f"[BGM] ❌ {msg}")
        return None

    task_id = data["data"]["task_id"]
    print(f"[BGM] 📋 {task_id}")

    for i in range(30):
        time.sleep(3)
        try:
            q = urllib.request.Request(
                f"https://aimusicapi.org/api/v2/generate/record?task_id={task_id}",
                headers={"Authorization": f"Bearer {AIMUSIC_KEY}"})
            qd = json.loads(urllib.request.urlopen(q, timeout=10, context=_SSL_CTX).read())
            status = qd.get("data", {}).get("status", "")
            if status in ("completed", "success"):
                url = qd["data"].get("audio_url", "")
                if url:
                    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                    urllib.request.urlretrieve(url, output_path)
                    print(f"[BGM] ✅ {os.path.basename(output_path)} ({os.path.getsize(output_path)/1024:.0f}KB)")
                    return output_path
            if i % 5 == 0:
                print(f"[BGM] ⏳ {status}")
        except Exception:
            continue

    print("[BGM] ❌ 超时")
    return None


def generate_sfx(keyword, output_path, duration=3):
    """ElevenLabs Sound Effects API - 文字描述生成真实音效"""
    if not ELEVENLABS_KEY:
        print("[SFX] ❌ 未设置 ELEVENLABS_API_KEY")
        print("  💡 https://elevenlabs.io/app/settings/api-keys")
        return None

    body = json.dumps({
        "text": keyword,
        "duration_seconds": min(duration, 22),
    }).encode()

    print(f"[SFX] 🔊 '{keyword[:50]}' ({duration}s)...")

    try:
        req = urllib.request.Request("https://api.elevenlabs.io/v1/sound-generation",
            data=body, headers={
                "xi-api-key": ELEVENLABS_KEY,
                "Content-Type": "application/json",
            }, method="POST")
        data = urllib.request.urlopen(req, timeout=60, context=_SSL_CTX).read()
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")[:300]
        print(f"[SFX] ❌ HTTP {e.code}: {err}")
        return None

    if not data or len(data) < 100:
        print("[SFX] ❌ 空响应")
        return None

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(data)

    print(f"[SFX] ✅ {os.path.basename(output_path)} ({len(data)/1024:.0f}KB)")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="音频工具 - TTS 配音 / AI BGM")
    parser.add_argument("--type", choices=["tts", "bgm", "sfx"], required=True)
    parser.add_argument("--text", help="合成文本（tts）")
    parser.add_argument("--speaker", default="zh_female_vv_uranus_bigtts", help="TTS 音色")
    parser.add_argument("--keyword", help="BGM/SFX 描述")
    parser.add_argument("--duration", type=int, default=3, help="SFX 时长（秒）")
    parser.add_argument("--output", required=True, help="输出文件路径")

    args = parser.parse_args()

    if args.type == "tts":
        if not args.text:
            print("❌ 需要 --text"); sys.exit(1)
        result = generate_tts(args.text, args.output, args.speaker)
    elif args.type == "bgm":
        if not args.keyword:
            print("❌ 需要 --keyword"); sys.exit(1)
        result = generate_bgm(args.keyword, args.output)
    elif args.type == "sfx":
        if not args.keyword:
            print("❌ 需要 --keyword"); sys.exit(1)
        result = generate_sfx(args.keyword, args.output, args.duration)

    sys.exit(0 if result else 1)
