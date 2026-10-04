import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256 * 1024 * 1024)
    return f"scrypt${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        parts = encoded.split("$")
        if parts[0] != "scrypt":
            return False
        if len(parts) == 3:
            _, salt_b64, expected_b64 = parts
            # First try calibrated production parameter N=2^17 (131072, r=8, p=1, 128MB RAM)
            actual = hashlib.scrypt(password.encode(), salt=_unb64(salt_b64), n=2**17, r=8, p=1, maxmem=256 * 1024 * 1024)
            if hmac.compare_digest(actual, _unb64(expected_b64)):
                return True
            # Backward-compatible fallback for legacy demo fixtures created with N=2^14
            legacy = hashlib.scrypt(password.encode(), salt=_unb64(salt_b64), n=2**14, r=8, p=1, maxmem=256 * 1024 * 1024)
            return hmac.compare_digest(legacy, _unb64(expected_b64))
        return False
    except (ValueError, TypeError):
        return False


def create_access_token(claims: dict[str, Any], secret: str, expires_in: int = 1800) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = dict(claims)
    body["exp"] = int(time.time()) + expires_in
    payload = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    signature = _b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    try:
        header, payload, signature = token.split(".")
        expected = _b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        claims = json.loads(_unb64(payload))
        if int(claims.get("exp", 0)) < int(time.time()):
            raise ValueError("token expired")
        return claims
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid access token") from exc
