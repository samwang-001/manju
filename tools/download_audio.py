#!/usr/bin/env python3
"""
音频下载工具 - Pixabay BGM + Freesound 音效 + 火山TTS 配音

用法:
  # 下载BGM（Pixabay CDN，免费可商用）
  python3 tools/download_audio.py --type bgm --keyword "summer piano" --output audio/bgm.mp3

  # 下载音效（Freesound API，免费）
  export FREESOUND_API_KEY="xxx"
  python3 tools/download_audio.py --type sfx --keyword "river water" --output audio/stream.mp3

  # 火山TTS 配音
  export DOUBAO_APP_ID="xxx"
  export DOUBAO_ACCESS_KEY="xxx"  
  python3 tools/download_audio.py --type tts --text "夏日午后，少女坐在河边" --output audio/narration.mp3
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
from pathlib import Path

# ==================== 配置 ====================
FREESOUND_KEY = os.environ.get("FREESOUND_API_KEY", "")
DOUBAO_APP_ID = os.environ.get("DOUBAO_APP_ID", "")
DOUBAO_ACCESS_KEY = os.environ.get("DOUBAO_ACCESS_KEY", "")

# ==================== 方案1：本地 BGM 库 ====================
BGM_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".bgm_library")

def list_bgm_library():
    """列出本地 BGM 库中的所有曲目"""
    if not os.path.exists(BGM_LIB):
        return []
    tracks = []
    for f in sorted(os.listdir(BGM_LIB)):
        if f.endswith(('.mp3', '.wav', '.m4a', '.flac')):
            path = os.path.join(BGM_LIB, f)
            size_mb = os.path.getsize(path) / (1024 * 1024)
            tracks.append((f, path, size_mb))
    return tracks

def pick_bgm(keyword, output_path):
    """
    从本地 BGM 库选取匹配的曲目。
    库路径: {项目根}/.bgm_library/
    
    如库为空，提示用户从 Pixabay 等免费音乐站手动下载放入。
    """
    tracks = list_bgm_library()
    if not tracks:
        print("[BGM库] 📂 本地库为空")
        print("  💡 请从以下免费音乐站下载曲目，放入 .bgm_library/ 目录：")
        print("     https://pixabay.com/music/     （搜索 summer/piano/relaxing）")
        print("     https://www.chosic.com/free-music/piano/")
        print("     https://freepd.com/")
        print(f"  📁 库路径: {BGM_LIB}")
        return None
    
    # 模糊匹配
    best = None
    kw_lower = keyword.lower()
    for name, path, size_mb in tracks:
        if any(w in name.lower() for w in kw_lower.split()):
            best = (name, path)
            break
    
    if not best:
        best = (tracks[0][0], tracks[0][1])  # 取第一个
    
    print(f"[BGM库] 🎵 {best[0]}")
    shutil.copy(best[1], output_path)
    print(f"[BGM库] ✅ {os.path.basename(output_path)}")
    return output_path


# ==================== 方案2：Freesound 音效 ====================
def download_freesound_sfx(keyword, output_path, duration_hint=10):
    """
    从 Freesound API 搜索并下载音效。
    需要 FREESOUND_API_KEY 环境变量。
    """
    if not FREESOUND_KEY:
        print("[Freesound] ⚠️  未设置 FREESOUND_API_KEY")
        print("  💡 注册: https://freesound.org/apiv2/apply/")
        print("     export FREESOUND_API_KEY=\"xxx\"")
        return None

    print(f"[Freesound] 🔍 搜索: {keyword}")
    
    # 搜索 API
    params = urllib.parse.urlencode({
        "query": keyword,
        "fields": "id,name,previews,download,duration",
        "page_size": "5",
        "sort": "rating_desc",
        "filter": f"duration:[1 TO {duration_hint * 2}]",
    })
    search_url = f"https://freesound.org/apiv2/search/text/?{params}&token={FREESOUND_KEY}"
    
    try:
        resp = urllib.request.urlopen(search_url, timeout=15)
        data = json.loads(resp.read())
        results = data.get("results", [])
        
        if not results:
            print(f"[Freesound] ❌ 无结果")
            return None
        
        # 选第一个有预览的结果
        sound = results[0]
        sound_id = sound["id"]
        name = sound.get("name", "unknown")
        
        # 尝试获取下载链接（高质量）
        detail_url = f"https://freesound.org/apiv2/sounds/{sound_id}/?token={FREESOUND_KEY}"
        detail_resp = urllib.request.urlopen(detail_url, timeout=10)
        detail = json.loads(detail_resp.read())
        
        # 优先下载原文件，否则用预览
        download_url = detail.get("download")
        if download_url:
            download_url = f"{download_url}?token={FREESOUND_KEY}"
        else:
            previews = detail.get("previews", {})
            download_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
            if not download_url:
                print(f"[Freesound] ❌ 无可下载文件")
                return None
        
        print(f"[Freesound] 📥 {name} (ID:{sound_id})")
        urllib.request.urlretrieve(download_url, output_path)
        
        size_kb = os.path.getsize(output_path) / 1024
        dur = detail.get("duration", 0)
        print(f"[Freesound] ✅ {os.path.basename(output_path)} ({size_kb:.0f}KB, {dur:.0f}s)")
        return output_path
        
    except Exception as e:
        print(f"[Freesound] ❌ {e}")
        return None


# ==================== 方案3：火山豆包 TTS ====================
def generate_doubao_tts(text, output_path, speaker=None):
    """
    调用火山引擎豆包 TTS 合成语音。
    需要 DOUBAO_APP_ID 和 DOUBAO_ACCESS_KEY 环境变量。
    """
    import base64
    
    if not DOUBAO_APP_ID or not DOUBAO_ACCESS_KEY:
        print("[豆包TTS] ⚠️  未设置 DOUBAO_APP_ID 或 DOUBAO_ACCESS_KEY")
        print("  💡 获取: https://console.volcengine.com/speech/app")
        print("     创建应用 → 获取 APP ID")
        print("     访问控制 → 创建 Access Key")
        print("     export DOUBAO_APP_ID=\"123456\"")
        print("     export DOUBAO_ACCESS_KEY=\"ak_xxx\"")
        return None

    # 默认用 2.0 女声
    if not speaker:
        speaker = "zh_female_vv_uranus_bigtts"  # Vivi - 温柔女声
    
    # 判断音色类型选择 resource_id
    if "uranus_bigtts" in speaker or "saturn" in speaker:
        resource_id = "seed-tts-2.0"
        additions = None
    elif "S_" in speaker:
        resource_id = "seed-icl-2.0"
        additions = '{"context_texts":["用温暖治愈的语气，轻轻诉说"],"model_type":4}'
    else:
        resource_id = "seed-tts-1.0"
        additions = None

    body = {
        "user": {"uid": "manju-tool"},
        "req_params": {
            "text": text,
            "speaker": speaker,
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
            },
        },
    }
    if additions:
        body["req_params"]["additions"] = additions

    print(f"[豆包TTS] 🎙️ {speaker}: {text[:40]}...")
    
    try:
        req = urllib.request.Request(
            "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Api-App-Id": DOUBAO_APP_ID,
                "X-Api-Access-Key": DOUBAO_ACCESS_KEY,
                "X-Api-Resource-Id": resource_id,
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=30)
        
        # 解析 NDJSON 响应
        audio_chunks = []
        for line in resp.read().decode(errors="replace").split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
                code = chunk.get("code")
                if code == 0 and "data" in chunk:
                    audio_chunks.append(base64.b64decode(chunk["data"]))
                elif code == 20000000:
                    break  # 结束标记
                else:
                    print(f"[豆包TTS] ⚠️  错误码: {code}")
            except (json.JSONDecodeError, base64.binascii.Error):
                continue
        
        if not audio_chunks:
            print("[豆包TTS] ❌ 无音频数据")
            return None
        
        with open(output_path, "wb") as f:
            f.write(b"".join(audio_chunks))
        
        size_kb = os.path.getsize(output_path) / 1024
        duration = len(b"".join(audio_chunks)) / 24000  # 估算时长
        print(f"[豆包TTS] ✅ {os.path.basename(output_path)} ({size_kb:.0f}KB, ~{duration:.0f}s)")
        return output_path
        
    except Exception as e:
        print(f"[豆包TTS] ❌ {e}")
        return None


# ==================== 主入口 ====================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="音频下载工具 - BGM/音效/配音")
    parser.add_argument("--type", choices=["bgm", "sfx", "tts"], required=True,
                        help="类型: bgm=本地BGM库, sfx=Freesound音效, tts=豆包配音")
    parser.add_argument("--keyword", help="搜索关键词（bgm/sfx类型需要）")
    parser.add_argument("--text", help="合成文本（tts类型需要）")
    parser.add_argument("--speaker", help="TTS音色ID（tts类型可选）")
    parser.add_argument("--output", required=True, help="输出文件路径")
    parser.add_argument("--duration", type=int, default=10, help="目标时长秒数（sfx类型参考）")
    parser.add_argument("--list", action="store_true", help="列出本地BGM库")

    args = parser.parse_args()
    
    if args.list:
        tracks = list_bgm_library()
        if tracks:
            print(f"📂 本地BGM库 ({BGM_LIB}):")
            for name, path, size_mb in tracks:
                print(f"  {size_mb:.1f}MB  {name}")
        else:
            print(f"📂 BGM库为空: {BGM_LIB}")
            print("  请从 https://pixabay.com/music/ 下载免费曲目放入此目录")
        sys.exit(0)
    
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    if args.type == "bgm":
        if not args.keyword:
            print("❌ BGM需要 --keyword 参数")
            sys.exit(1)
        result = pick_bgm(args.keyword, args.output)

    elif args.type == "sfx":
        if not args.keyword:
            print("❌ SFX需要 --keyword 参数")
            sys.exit(1)
        result = download_freesound_sfx(args.keyword, args.output, args.duration)

    elif args.type == "tts":
        if not args.text:
            print("❌ TTS需要 --text 参数")
            sys.exit(1)
        result = generate_doubao_tts(args.text, args.output, args.speaker)

    if result:
        print(f"\n🎵 输出: {result}")
        sys.exit(0)
    else:
        print("\n❌ 下载失败，降级到 FFmpeg 合成")
        sys.exit(1)
