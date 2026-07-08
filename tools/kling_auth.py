#!/usr/bin/env python3
"""
Kling JWT Token 生成工具（纯Python实现，无需外部库）

用法:
  python3 tools/kling_auth.py --ak "你的AccessKey" --sk "你的SecretKey"
  export KLING_API_TOKEN=$(python3 tools/kling_auth.py --ak xxx --sk yyy)
"""

import argparse
import base64
import hashlib
import hmac
import json
import time


def base64url_encode(data):
    """Base64URL 编码（无填充）"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_kling_token(access_key, secret_key, ttl=3600):
    """
    生成可灵 JWT Token (HS256)
    完全标准 JWT 实现，无需任何外部库
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "iss": access_key,
        "exp": now + ttl,
        "nbf": now - 5,
    }

    # 编码 Header 和 Payload
    header_b64 = base64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = base64url_encode(json.dumps(payload, separators=(",", ":")).encode())

    # 签名
    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        secret_key.encode(),
        signing_input.encode(),
        hashlib.sha256,
    ).digest()
    sig_b64 = base64url_encode(signature)

    return f"{signing_input}.{sig_b64}"


def main():
    parser = argparse.ArgumentParser(description="Kling JWT Token 生成 (纯Python)")
    parser.add_argument("--ak", required=True, help="Access Key")
    parser.add_argument("--sk", required=True, help="Secret Key")
    parser.add_argument("--ttl", type=int, default=3600, help="Token有效期(秒)，默认3600")
    args = parser.parse_args()

    token = generate_kling_token(args.ak, args.sk, args.ttl)
    print(token, end="")

    # 提示信息输出到 stderr
    import sys
    print(f"\n# Token 有效期: {args.ttl}s", file=sys.stderr)
    print(f"# export KLING_API_TOKEN=\"{token}\"", file=sys.stderr)


if __name__ == "__main__":
    main()
