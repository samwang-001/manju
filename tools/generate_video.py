#!/usr/bin/env python3
"""
视频生成工具 - 三后端智能路由 + 调用追踪

后端1：Seedance 2.0 (seedanceapi.org v2) - 🥇 业界第1图生视频，720p/$0.14
后端2：Kling/可灵 - 🥈 运动最流畅，每日免费66积分
后端3：Ken Burns (OpenCV) - 🟢 本地运镜，永远可用

智能降级：
  有Key+有余额 → Seedance
  Seedance失败 → Kling (如有Token)
  Kling失败/无Token → Ken Burns

用法:
  python3 tools/generate_video.py --image shot1.png --motion "zoom_in" --output shot1.mp4
  python3 tools/generate_video.py --image in.png --output out.mp4 --backend seedance
  python3 tools/generate_video.py --image in.png --output out.mp4 --prompt "camera push in"
"""

import argparse
import json
import os
import shutil
import sys
import subprocess
import time
import hashlib
import tempfile
from datetime import datetime

# ==================== 配置 ====================
CONFIG = {
    "seedance": {
        "enabled": True,
        "base_url": "https://seedanceapi.org/v2",
        "cost_per_gen": 28,  # 积分 (720p/8s/no-audio), 100积分=$1
        "model_default": "seedance-2.0",
        "resolution": "720p",
        "duration": "8",
        "max_retries": 1,
        "poll_interval": 10,   # 轮询间隔（秒）
        "poll_max_wait": 300,  # 最大等待（秒）
        "auth_key": os.environ.get("SEEDANCE_API_KEY", ""),
    },
    "kling": {
        "enabled": True,
        "base_url": "https://api-beijing.klingai.com",
        "submit_url": "https://api-beijing.klingai.com/v1/videos/image2video",
        "model": "kling-v2.6-pro",
        "mode": "pro",  # 专业模式，1080p
        "cost_per_gen": 0,  # 新用户有试用积分
        "max_retries": 2,
        "poll_interval": 5,
        "poll_max_wait": 300,
        "api_key": os.environ.get("KLING_API_KEY", ""),  # klingai.com 简单 API Key
    },
    "kenburns": {
        "enabled": True,
        "cost_per_gen": 0,
    },
}


# ==================== 图片上传（转为公网URL） ====================
def upload_image_to_url(image_path):
    """将本地图片上传到临时公网URL（纯Python，不依赖curl子进程）。"""
    import urllib.request
    import io
    import uuid

    # 读取图片
    with open(image_path, "rb") as f:
        img_data = f.read()

    ext = os.path.splitext(image_path)[1].lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext.lstrip("."), "image/png")

    def _multipart_post(url, field_name="files[]"):
        """构建multipart请求体并发送"""
        boundary = uuid.uuid4().hex.encode()
        safe_name = f"shot{uuid.uuid4().hex[:6]}{ext}"
        body = b"--" + boundary + b"\r\n"
        body += f'Content-Disposition: form-data; name="{field_name}"; filename="{safe_name}"\r\n'.encode()
        body += f"Content-Type: {mime}\r\n\r\n".encode()
        body += img_data + b"\r\n"
        body += b"--" + boundary + b"--\r\n"

        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
        })
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())

    # uguu.se - 免费，无需key，返回直链
    try:
        result = _multipart_post("https://uguu.se/upload.php")
        url = result.get("files", [{}])[0].get("url", "")
        if url and url.startswith("http"):
            print(f"  [Upload] ✅ uguu.se → {url}")
            return url
    except Exception as e:
        print(f"  [Upload] uguu.se 失败: {e}")

    # gofile.io 备用
    try:
        result = _multipart_post("https://store1.gofile.io/uploadFile", field_name="file")
        data = result.get("data", {})
        if result.get("status") == "ok" and data.get("parentFolderCode"):
            url = f"https://gofile.io/d/{data['parentFolderCode']}/{data.get('name', 'file')}"
            print(f"  [Upload] ✅ gofile.io → {url}")
            return url
    except Exception as e:
        print(f"  [Upload] gofile.io 失败: {e}")

    print(f"  [Upload] ❌ 所有上传服务均失败")
    return None


# ==================== 调用追踪 ====================
class Tracker:
    """记录每次生成调用的元数据"""

    def __init__(self, project_dir):
        self.log_path = os.path.join(project_dir, "视频生成追踪.json") if project_dir else None
        self.records = self._load()

    def _load(self):
        if self.log_path and os.path.exists(self.log_path):
            with open(self.log_path) as f:
                return json.load(f)
        return {"generations": []}

    def record(self, shot_id, backend, status, **kwargs):
        entry = {
            "shot": shot_id,
            "backend": backend,
            "status": status,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        self.records["generations"].append(entry)
        self._save()
        return entry

    def _save(self):
        if self.log_path:
            os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
            with open(self.log_path, "w") as f:
                json.dump(self.records, f, indent=2, ensure_ascii=False)

    def summary(self):
        gens = self.records["generations"]
        if not gens:
            return "无记录"
        total = len(gens)
        success = sum(1 for g in gens if g["status"] == "success")
        backends = {}
        for g in gens:
            b = g["backend"]
            backends[b] = backends.get(b, 0) + 1
        total_cost = sum(g.get("cost", 0) for g in gens)
        return (
            f"共 {total} 段 | 成功 {success}/{total} | "
            f"后端分布: {backends} | 积分: {total_cost}"
        )


# ==================== 后端1: Seedance 2.0 (seedanceapi.org v2) ====================
def _seedance_submit(prompt, image_url, cfg):
    """提交Seedance任务，返回task_id或None"""
    import urllib.request

    # Map user-requested duration to Seedance-allowed values
    allowed_durations = [5, 10, 15]
    target_dur = int(cfg.get("duration", 8))
    closest = min(allowed_durations, key=lambda x: abs(x - target_dur))
    if closest != target_dur:
        print(f"[Seedance] ⚠️  duration {target_dur}s → {closest}s (API允许5/10/15)")

    payload = json.dumps({
        "prompt": prompt or "cinematic camera movement, smooth motion, professional video",
        "image_urls": [image_url],
        "aspect_ratio": "9:16",
        "resolution": cfg["resolution"],
        "duration": closest,
        "generate_audio": False,
        "fixed_lens": True,
    }).encode()

    # Cloudflare bypass headers (seedanceapi.org uses CF protection)
    req = urllib.request.Request(
        f"{cfg['base_url']}/generate",
        data=payload,
        headers={
            "Authorization": f"Bearer {cfg['auth_key']}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) SeedanceCLI/1.0",
            "Accept": "application/json",
            "Origin": "https://seedanceapi.org",
            "Referer": "https://seedanceapi.org/",
        },
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        code = result.get("code")
        
        if code == 200:
            task_id = result.get("data", {}).get("task_id")
            if task_id:
                return task_id, None
        
        if code == 401:
            return None, "INVALID_KEY"
        if code == 402:
            return None, "INSUFFICIENT_CREDITS"
        if code == 400:
            return None, f"BAD_REQUEST: {result.get('message', '')}"
        if code == 403:
            return None, "FORBIDDEN (Cloudflare?)"
        msg = result.get("message", f"code={code}")
        return None, msg

    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        if "1010" in body or e.code == 403:
            return None, "CLOUDFLARE_BLOCK"
        return None, f"HTTP_{e.code}: {body}"
    except Exception as e:
        return None, str(e)[:100]


def _seedance_poll(task_id, cfg):
    """轮询Seedance任务状态，返回(video_url, consumed_credits)或(None, error)"""
    import urllib.request

    query_url = f"{cfg['base_url']}/status?task_id={task_id}"
    headers = {
        "Authorization": f"Bearer {cfg['auth_key']}",
        "User-Agent": "Mozilla/5.0 SeedanceCLI/1.0",
        "Accept": "application/json",
    }

    waited = 0
    while waited < cfg["poll_max_wait"]:
        time.sleep(cfg["poll_interval"])
        waited += cfg["poll_interval"]

        try:
            req = urllib.request.Request(query_url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=15)
            result = json.loads(resp.read())
        except Exception:
            continue

        data = result.get("data", {})
        status = data.get("status", "")

        if status == "SUCCESS":
            videos = data.get("response", [])
            video_url = videos[0] if videos else None
            credits = data.get("consumed_credits", 0)
            if video_url:
                return video_url, credits
            return None, "NO_VIDEO_URL"

        elif status == "FAILED":
            return None, data.get("error_message", "生成失败")

        elif status == "IN_PROGRESS":
            print(f"[Seedance] ⏳ 生成中... ({waited}s)")

    return None, "POLL_TIMEOUT"


def generate_seedance(image_path, output_path, prompt="", duration=5, fps=24):
    """
    调用 Seedance 2.0 API (seedanceapi.org v2)
    流程: 上传图片→提交任务→轮询→下载
    """
    cfg = CONFIG["seedance"]
    if not cfg["auth_key"]:
        print("[Seedance] ⚠️  未设置 SEEDANCE_API_KEY")
        return None, "NO_KEY"

    t0 = time.time()

    # Step 1: 上传图片到公网URL
    print(f"[Seedance] 📤 上传参考图片...")
    image_url = upload_image_to_url(image_path)
    if not image_url:
        return None, "UPLOAD_FAILED"

    # Step 2: 提交任务
    print(f"[Seedance] 🎬 提交视频生成任务...")
    task_id, error = _seedance_submit(prompt, image_url, cfg)
    if not task_id:
        print(f"[Seedance] ❌ 提交失败: {error}")
        return None, error

    print(f"[Seedance] 📋 Task: {task_id}")

    # Step 3: 轮询结果
    video_url, credits = _seedance_poll(task_id, cfg)
    if not video_url:
        print(f"[Seedance] ❌ 生成失败: {credits}")
        return None, credits

    # Step 4: 下载视频
    print(f"[Seedance] 📥 下载视频...")
    try:
        import urllib.request
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        req = urllib.request.Request(video_url)
        video_data = urllib.request.urlopen(req, timeout=120).read()
        with open(output_path, "wb") as f:
            f.write(video_data)

        elapsed = time.time() - t0
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        cost_usd = credits / 100
        print(f"[Seedance] ✅ {os.path.basename(output_path)} "
              f"({size_mb:.1f}MB, {elapsed:.0f}s, {credits}分≈${cost_usd:.2f})")
        return output_path, "success"
    except Exception as e:
        print(f"[Seedance] ❌ 下载失败: {e}")
        return None, str(e)[:50]


# ==================== 后端2: Kling/可灵 ====================
def _curl(method, url, headers=None, data=None, timeout=30):
    """用 curl 子进程发送 HTTP 请求（大 JSON 自动走临时文件）"""
    CURL = shutil.which("curl") or "/usr/bin/curl"
    cmd = [CURL, "-s", "-w", "\n%{http_code}", "--connect-timeout", str(timeout),
           "--max-time", str(timeout)]
    cmd += ["-X", method]
    if headers:
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
    if data:
        # 大 payload 写入临时文件避免命令行参数溢出
        if len(data) > 50000:
            fp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
            fp.write(data)
            fp.close()
            cmd += ["-d", f"@{fp.name}"]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
            finally:
                os.unlink(fp.name)
        else:
            cmd += ["-d", data]
    cmd.append(url)
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    output = result.stdout.strip()
    lines = output.rsplit("\n", 1)
    if len(lines) == 2 and lines[1].isdigit():
        return lines[0], int(lines[1])
    return output, 0


def generate_kling(image_path, output_path, prompt="", duration=5, fps=24):
    """调用可灵图生视频 API（异步：提交→轮询→下载）"""
    import base64

    cfg = CONFIG["kling"]
    if not cfg["api_key"]:
        return None, "NO_KEY"

    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    payload = json.dumps({
        "model": cfg["model"],
        "image_url": upload_image_to_url(image_path) or f"data:image/png;base64,{image_b64}",
        "prompt": prompt or "cinematic camera movement, smooth motion",
        "duration": str(int(duration)),
        "mode": "std",
    })

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }

    print(f"[Kling] 📤 提交任务...")
    t0 = time.time()

    try:
        body, code = _curl("POST", cfg["submit_url"], headers=headers, data=payload, timeout=30)
        if code != 200:
            print(f"[Kling] ❌ HTTP {code}: {body[:200]}")
            return None, f"HTTP_{code}"
        result = json.loads(body)
    except Exception as e:
        print(f"[Kling] ❌ 提交失败: {e}")
        return None, str(e)[:50]

    if result.get("code") != 0:
        msg = result.get("message", "未知错误")
        print(f"[Kling] ❌ code={result.get('code')}, msg={msg}")
        return None, msg

    task_id = result["data"]["task_id"]
    print(f"[Kling] 📋 任务ID: {task_id}")

    # 轮询
    query_url = f"{cfg['base_url']}/videos/{task_id}"
    query_headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    waited = 0
    while waited < cfg["poll_max_wait"]:
        time.sleep(cfg["poll_interval"])
        waited += cfg["poll_interval"]

        try:
            body, code = _curl("GET", query_url, headers=query_headers, timeout=10)
            if code != 200:
                continue
            status = json.loads(body)
        except Exception:
            continue

        task_status = status.get("data", {}).get("task_status", "")
        print(f"[Kling] ⏳ {task_status} ({waited}s)")

        if task_status == "succeed":
            videos = status.get("data", {}).get("task_result", {}).get("videos", [])
            if not videos:
                return None, "NO_VIDEO_URL"
            video_url = videos[0].get("url")
            if not video_url:
                return None, "NO_VIDEO_URL"

            print(f"[Kling] 📥 下载视频...")
            try:
                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                subprocess.run(
                    ["/usr/bin/curl", "-s", "-o", output_path, "--connect-timeout", "60",
                     "--max-time", "120", video_url],
                    check=True, timeout=120
                )
                elapsed = time.time() - t0
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                print(f"[Kling] ✅ {os.path.basename(output_path)} ({size_mb:.1f}MB, {elapsed:.0f}s)")
                return output_path, "success"
            except Exception as e:
                print(f"[Kling] ❌ 下载失败: {e}")
                return None, str(e)[:50]

        elif task_status == "failed":
            msg = status.get("data", {}).get("task_status_msg", "未知")
            print(f"[Kling] ❌ 生成失败: {msg}")
            return None, msg

    print(f"[Kling] ❌ 超时 ({cfg['poll_max_wait']}s)")
    return None, "TIMEOUT"


# ==================== 后端3: Ken Burns (OpenCV) ====================
def generate_ken_burns(image_path, output_path, duration=3, motion="zoom_in", fps=24):
    """用 OpenCV 模拟推拉摇移效果"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("[KenBurns] ❌ opencv-python 未安装")
        return None, "NO_OPENCV"

    img = cv2.imread(image_path)
    if img is None:
        print(f"[KenBurns] ❌ 无法读取: {image_path}")
        return None, "NO_IMAGE"

    h, w = img.shape[:2]
    total_frames = int(duration * fps)
    out_w, out_h = 1080, 1920

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    out = cv2.VideoWriter(output_path, fourcc, fps, (out_w, out_h))

    margin = 0.15
    crop_w = int(w * (1 - margin))
    crop_h = int(h * (1 - margin))

    t0 = time.time()

    for i in range(total_frames):
        t = i / total_frames

        if motion in ("zoom_in", "推", "推镜"):
            scale = 1.0 + t * (1.0 / (1 - margin) - 1.0)
            cur_w = int(w / scale)
            cur_h = int(h / scale)
            x, y = (w - cur_w) // 2, (h - cur_h) // 2
        elif motion in ("zoom_out", "拉", "拉镜"):
            scale = 1.0 / (1 - margin) - t * (1.0 / (1 - margin) - 1.0)
            cur_w = int(w / scale)
            cur_h = int(h / scale)
            x, y = (w - cur_w) // 2, (h - cur_h) // 2
        elif motion in ("pan_left", "左摇"):
            x = int((w - crop_w) * t)
            y = (h - crop_h) // 2
            cur_w, cur_h = crop_w, crop_h
        elif motion in ("pan_right", "右摇"):
            x = int((w - crop_w) * (1 - t))
            y = (h - crop_h) // 2
            cur_w, cur_h = crop_w, crop_h
        elif motion in ("pan_up", "上摇"):
            x = (w - crop_w) // 2
            y = int((h - crop_h) * (1 - t))
            cur_w, cur_h = crop_w, crop_h
        elif motion in ("pan_down", "下摇"):
            x = (w - crop_w) // 2
            y = int((h - crop_h) * t)
            cur_w, cur_h = crop_w, crop_h
        else:
            x, y = (w - crop_w) // 2, (h - crop_h) // 2
            cur_w, cur_h = crop_w, crop_h

        crop = img[y:y + cur_h, x:x + cur_w]
        resized = cv2.resize(crop, (out_w, out_h))
        out.write(resized)

    out.release()
    elapsed = time.time() - t0
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"[KenBurns] ✅ {os.path.basename(output_path)} ({size_mb:.1f}MB, {elapsed:.0f}s)")
    return output_path, "success"


# ==================== 静态视频兜底 ====================
def generate_static_video(image_path, output_path, duration=3, fps=24):
    """FFmpeg 图片转静态视频"""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or os.environ.get("FFMPEG", "/usr/local/bin/ffmpeg")
    cmd = [
        ffmpeg, "-y", "-loop", "1", "-i", image_path,
        "-t", str(duration), "-r", str(fps),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path,
    ]
    t0 = time.time()
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        elapsed = time.time() - t0
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"[Static] ✅ {os.path.basename(output_path)} ({size_mb:.1f}MB, {elapsed:.0f}s)")
        return output_path, "success"
    except Exception as e:
        print(f"[Static] ❌ {e}")
        return None, str(e)[:50]


# ==================== 主流程：智能路由 ====================
def generate_video(image_path, output_path, motion="zoom_in", prompt="", 
                   duration=5, fps=24, backend="auto", project_dir=None):
    """
    三后端智能路由核心函数

    降级链: Seedance → Kling → Ken Burns → 静态视频

    返回: (output_path, backend_used, tracker)
    """
    proj_dir = project_dir or os.path.dirname(output_path) or "."
    tracker = Tracker(proj_dir)
    shot_id = os.path.splitext(os.path.basename(output_path))[0]

    # === 指定后端 ===
    if backend == "seedance":
        result, status = generate_seedance(image_path, output_path, prompt, duration, fps)
        if result:
            tracker.record(shot_id, "seedance", "success", cost=CONFIG["seedance"]["cost_per_gen"])
            return result, "seedance", tracker
        print(f"[Router] Seedance 失败 ({status})，降级到 Ken Burns...")
        result, _ = generate_ken_burns(image_path, output_path, duration, motion, fps)
        tracker.record(shot_id, "kenburns(fallback)", "fallback", reason=status, cost=0)
        return result, "kenburns(fallback)", tracker

    if backend == "kling":
        result, status = generate_kling(image_path, output_path, prompt, duration, fps)
        if result:
            tracker.record(shot_id, "kling", "success", cost=CONFIG["kling"]["cost_per_gen"])
            return result, "kling", tracker
        print(f"[Router] Kling 失败 ({status})，降级到 Ken Burns...")
        result, _ = generate_ken_burns(image_path, output_path, duration, motion, fps)
        tracker.record(shot_id, "kenburns(fallback)", "fallback", reason=status, cost=0)
        return result, "kenburns(fallback)", tracker

    if backend == "kenburns":
        result, _ = generate_ken_burns(image_path, output_path, duration, motion, fps)
        tracker.record(shot_id, "kenburns", "success", cost=0)
        return result, "kenburns", tracker

    # === 智能路由 (auto) ===
    # 1. Seedance（有Key + 有余额 → 最高质量）
    if CONFIG["seedance"]["enabled"] and CONFIG["seedance"]["auth_key"]:
        print(f"[Router] 🥇 尝试: Seedance 2.0 (720p, ~$0.14/段)")
        result, status = generate_seedance(image_path, output_path, prompt, duration, fps)
        if result:
            tracker.record(shot_id, "seedance", "success",
                          cost=CONFIG["seedance"]["cost_per_gen"],
                          resolution=CONFIG["seedance"]["resolution"])
            return result, "seedance", tracker

        if status == "INVALID_KEY":
            tracker.record(shot_id, "seedance(skipped)", "skip", reason="Key无效", cost=0)
        elif status == "INSUFFICIENT_CREDITS":
            tracker.record(shot_id, "seedance(skipped)", "skip", reason="余额不足", cost=0)
        else:
            print(f"[Router] Seedance 失败: {status}")

    # 2. Kling
    if CONFIG["kling"]["enabled"] and CONFIG["kling"]["api_key"]:
        print(f"[Router] 🥈 尝试: Kling/可灵")
        result, status = generate_kling(image_path, output_path, prompt, duration, fps)
        if result:
            tracker.record(shot_id, "kling", "success", cost=CONFIG["kling"]["cost_per_gen"])
            return result, "kling", tracker
        print(f"[Router] Kling 失败: {status}")

    # 3. Ken Burns
    print(f"[Router] 🟢 兜底: Ken Burns (本地运镜)")
    result, status = generate_ken_burns(image_path, output_path, duration, motion, fps)
    if result:
        tracker.record(shot_id, "kenburns", "success", cost=0)
        return result, "kenburns", tracker

    # 4. 终极兜底
    print(f"[Router] 🔄 终极兜底: 静态视频")
    result, status = generate_static_video(image_path, output_path, duration, fps)
    tracker.record(shot_id, "static", "fallback", reason=status, cost=0)
    return result, "static", tracker


# ==================== CLI ====================
def main():
    parser = argparse.ArgumentParser(description="视频生成工具 - 三后端智能路由 | Animator Agent")
    parser.add_argument("--image", required=True, help="输入图片路径")
    parser.add_argument("--motion", default="zoom_in",
                        choices=["zoom_in", "zoom_out", "pan_left", "pan_right",
                                 "pan_up", "pan_down", "推", "拉", "左摇", "右摇", "上摇", "下摇"],
                        help="运镜方式 (Ken Burns用)")
    parser.add_argument("--prompt", default="", help="视频生成Prompt（Seedance/Kling用）")
    parser.add_argument("--output", required=True, help="输出视频路径")
    parser.add_argument("--duration", type=float, default=5, help="时长(秒)")
    parser.add_argument("--fps", type=int, default=24, help="帧率")
    parser.add_argument("--backend", default="auto",
                        choices=["auto", "seedance", "kling", "kenburns"],
                        help="生成后端: auto=智能选择")
    parser.add_argument("--project-dir", default=None, help="项目目录（追踪记录位置）")

    args = parser.parse_args()

    print(f"[Animator] ══════════════════════════")
    print(f"[Animator] 图片: {args.image}")
    print(f"[Animator] 运镜: {args.motion}")
    print(f"[Animator] 后端: {args.backend}")
    print(f"[Animator] 时长: {args.duration}s")
    print(f"[Animator] ══════════════════════════")

    if not os.path.exists(args.image):
        print(f"[Animator] ❌ 图片不存在: {args.image}")
        sys.exit(1)

    result, backend_used, tracker = generate_video(
        args.image, args.output, args.motion, args.prompt,
        args.duration, args.fps, args.backend, args.project_dir,
    )

    if result:
        print(f"\n[Animator] 🎬 完成! 后端: {backend_used}")
        print(f"[Animator] 📊 追踪: {tracker.summary()}")
        if tracker.log_path:
            print(f"[Animator] 📝 日志: {tracker.log_path}")
    else:
        print(f"\n[Animator] ❌ 所有后端均失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
