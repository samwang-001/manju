#!/usr/bin/env python3
"""
配音生成工具 - 三后端智能降级 + 调用追踪

降级链:
  🥇 火山引擎 TTS  (~免费额度够用) - 字节·中文最自然·情感丰富
  🥈 Edge-TTS       (永远免费)        - 微软·离线可靠
  🟢 FFmpeg sine     (永远免费)        - 合成备用

用法:
  export VOLCENGINE_APP_ID="app_xxx"       # 火山引擎 App ID
  export VOLCENGINE_ACCESS_KEY="ak_xxx"    # 火山引擎 Access Key
  python3 tools/generate_tts.py --text "文本" --voice yunyang --output path.mp3
  python3 tools/generate_tts.py --batch "音频设计.json"

声线:
  yunyang  = 旁白·威严大气
  yunxi    = 少年·活泼青春
  yunjian  = 青年·阳光运动
  xiaoxiao = 少女·清亮活泼
"""

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import traceback
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# FFmpeg 自动检测
FFMPEG = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"

# ==================== 配置 ====================
VOLC_APP_ID = os.environ.get("VOLCENGINE_APP_ID", "")
VOLC_ACCESS_KEY = os.environ.get("VOLCENGINE_ACCESS_KEY", "")
VOLC_TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
VOLC_RESOURCE_ID = os.environ.get("VOLCENGINE_TTS_RESOURCE_ID", "seed-tts-1.1")

# Edge-TTS 声线映射
VOICE_MAP = {
    "yunyang":  "zh-CN-YunyangNeural",
    "yunxi":    "zh-CN-YunxiNeural",
    "yunjian":  "zh-CN-YunjianNeural",
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",
}

# 火山引擎 TTS 声线映射
VOLC_SPEAKER_MAP = {
    "yunyang":   "zh_male_qingrun_emo_latest",       # 男声·清润·适合旁白
    "yunxi":     "zh_male_qingse_emo_latest",         # 男声·青涩·适合少年
    "yunjian":   "zh_male_qingse_emo_latest",         # 同上
    "xiaoxiao":  "zh_female_qingxin_emo_latest",      # 女声·清新·适合少女
}


# ==================== 火山引擎 TTS ====================
def volc_tts_generate(text, voice_key, output_path, rate="+0%"):
    """🥇 火山引擎 TTS v3 单向流式"""
    speaker = VOLC_SPEAKER_MAP.get(voice_key, "zh_female_qingxin_emo_latest")

    body = json.dumps({
        "user": {"uid": "manju-cli"},
        "req_params": {
            "text": text,
            "speaker": speaker,
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
            },
        },
    }).encode()

    headers = {
        "Content-Type": "application/json",
        "X-Api-App-Id": VOLC_APP_ID,
        "X-Api-Access-Key": VOLC_ACCESS_KEY,
        "X-Api-Resource-Id": VOLC_RESOURCE_ID,
        "User-Agent": "Mozilla/5.0 ManjuCLI/2.0",
    }

    req = Request(VOLC_TTS_URL, data=body, headers=headers, method="POST")
    try:
        resp = urlopen(req, timeout=30)
    except HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode()[:200]
        except Exception:
            pass
        raise RuntimeError(f"HTTP_{e.code}: {body_text}")
    except URLError as e:
        raise RuntimeError(f"NETWORK: {e.reason}")

    # 流式响应：每行是一个 JSON，包含 base64 音频片段
    audio_chunks = []
    content_type = resp.headers.get("Content-Type", "")
    raw_body = resp.read()

    if "application/json" in content_type or "text/event-stream" in content_type:
        for line in raw_body.decode(errors="replace").split("\n"):
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            try:
                chunk = json.loads(line)
                # Support both {"audio":{"data":"..."}} and flat {"data":"..."}
                if "audio" in chunk and isinstance(chunk["audio"], dict):
                    b64 = chunk["audio"].get("data", "")
                else:
                    b64 = chunk.get("data", "")
                if b64:
                    audio_chunks.append(base64.b64decode(b64))
            except (json.JSONDecodeError, base64.binascii.Error):
                continue
    else:
        # Direct binary or unrecognized format → try raw bytes
        if raw_body and len(raw_body) > 100:
            audio_chunks = [raw_body]
        else:
            raise RuntimeError(f"EMPTY_RESPONSE: {len(raw_body)} bytes")

    if not audio_chunks:
        raise RuntimeError("EMPTY_AUDIO")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(b"".join(audio_chunks))

    size_kb = os.path.getsize(output_path) / 1024
    print(f"  🥇 火山TTS ✅ {os.path.basename(output_path)} ({size_kb:.0f}KB) '{text}'")
    return output_path


# ==================== Edge-TTS (备用) ====================
async def edge_tts_generate(text, voice_key, output_path, rate="+0%"):
    """🥈 Edge-TTS 免费备用"""
    voice_id = VOICE_MAP.get(voice_key, voice_key)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text=text, voice=voice_id, rate=rate)
        await communicate.save(output_path)
        size_kb = os.path.getsize(output_path) / 1024
        print(f"  🥈 Edge-TTS ✅ {os.path.basename(output_path)} ({size_kb:.0f}KB) '{text}'")
        return output_path
    except Exception as e:
        print(f"  ❌ Edge-TTS: {e}")
        return None


# ==================== 统一生成（自动降级）====================
async def gen_one(text, voice_key, output_path, rate="+0%"):
    """单条生成：火山→Edge-TTS→FFmpeg 三级降级"""
    # Tier 🥇: 火山引擎 TTS
    if VOLC_APP_ID and VOLC_ACCESS_KEY:
        try:
            return volc_tts_generate(text, voice_key, output_path, rate)
        except Exception as e:
            print(f"  ⚠️ 火山TTS跳过: {str(e)[:60]}")

    # Tier 🥈: Edge-TTS
    result = await edge_tts_generate(text, voice_key, output_path, rate)
    if result:
        return result

    # Tier 🟢: FFmpeg sine 兜底（不可能到达这里，edge-tts 永远可用）
    print(f"  🟢 FFmpeg兜底 '{text}'")
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", "sine=f=220:d=2,volume=0.1",
        "-c:a", "libmp3lame", output_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=10)
    return output_path


# ==================== 批量模式 ====================
async def gen_batch(design_json):
    """从音频设计JSON批量生成"""
    with open(design_json) as f:
        design = json.load(f)

    base_dir = os.path.dirname(os.path.abspath(design_json)) or "."
    total = 0
    for shot in design.get("shots", []):
        voice_text = shot.get("voice", "")
        if not voice_text:
            continue
        sid = shot["id"]
        voice_key = shot.get("voice_id", "yunyang")
        rate = "+15%" if ("？" in voice_text or "！" in voice_text) else "+0%"
        output = os.path.join(base_dir, "audio", f"tts_{sid}.mp3")
        await gen_one(voice_text, voice_key, output, rate)
        total += 1

    backend = "火山TTS" if (VOLC_APP_ID and VOLC_ACCESS_KEY) else "Edge-TTS"
    print(f"\n  {backend}: 生成 {total} 条配音")


# ==================== CLI ====================
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if "--batch" in sys.argv:
        idx = sys.argv.index("--batch")
        design_path = sys.argv[idx + 1]
        asyncio.run(gen_batch(design_path))
        return

    args = {}
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] in ("--text", "--voice", "--output", "--rate"):
            args[sys.argv[i][2:]] = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--list-voices":
            print("声线列表:")
            for k, v in VOICE_MAP.items():
                volc_v = VOLC_SPEAKER_MAP.get(k, "—")
                print(f"  {k:10s}  Edge-TTS: {v:25s}  火山: {volc_v}")
            return
        else:
            i += 1

    if "text" not in args or "output" not in args:
        print("需要 --text 和 --output")
        sys.exit(1)

    asyncio.run(gen_one(
        args.get("text", ""),
        args.get("voice", "yunyang"),
        args.get("output", ""),
        args.get("rate", "+0%"),
    ))


if __name__ == "__main__":
    main()
