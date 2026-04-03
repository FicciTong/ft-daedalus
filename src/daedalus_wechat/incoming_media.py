from __future__ import annotations

import base64
import mimetypes
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

MAX_IMAGE_BYTES = 20 * 1024 * 1024
_SAFE_TOKEN_RE = re.compile(r"[^A-Za-z0-9._-]+")
_CONTENT_TYPE_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


@dataclass(frozen=True)
class IncomingImageRef:
    index: int
    url: str = ""
    has_media_info: bool = False
    aes_key: str = ""
    media_encrypt_query_param: str = ""
    media_aes_key: str = ""


@dataclass(frozen=True)
class SavedIncomingImage:
    index: int
    path: Path
    source_url: str
    content_type: str
    size_bytes: int


def _safe_token(value: str, *, fallback: str) -> str:
    normalized = _SAFE_TOKEN_RE.sub("_", value.strip())
    normalized = normalized.strip("._")
    return normalized or fallback


def _suffix_for_image(*, content_type: str, url: str) -> str:
    lowered = content_type.split(";", 1)[0].strip().lower()
    if lowered in _CONTENT_TYPE_SUFFIXES:
        return _CONTENT_TYPE_SUFFIXES[lowered]
    guessed = mimetypes.guess_extension(lowered)
    if guessed:
        return ".jpg" if guessed == ".jpe" else guessed
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.strip()
    if suffix:
        return suffix
    return ".img"


def _sniff_image_suffix(payload: bytes) -> str:
    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if payload.startswith(b"GIF87a") or payload.startswith(b"GIF89a"):
        return ".gif"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return ".webp"
    if payload.startswith(b"BM"):
        return ".bmp"
    if payload.startswith(b"II*\x00") or payload.startswith(b"MM\x00*"):
        return ".tiff"
    return ".img"


def _parse_aes_key_bytes(image: IncomingImageRef) -> bytes:
    if image.aes_key:
        return bytes.fromhex(image.aes_key)
    if not image.media_aes_key:
        raise RuntimeError("encrypted image has no aes key")
    decoded = base64.b64decode(image.media_aes_key)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32 and re.fullmatch(rb"[0-9a-fA-F]{32}", decoded):
        return bytes.fromhex(decoded.decode("ascii"))
    raise RuntimeError(
        f"unexpected aes key length after base64 decode: {len(decoded)}"
    )


def _decrypt_aes_128_ecb(ciphertext: bytes, *, key_bytes: bytes) -> bytes:
    proc = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-128-ecb",
            "-d",
            "-nosalt",
            "-K",
            key_bytes.hex(),
        ],
        input=ciphertext,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"openssl decrypt failed: {proc.stderr.decode(errors='replace').strip()}"
        )
    return proc.stdout


def _download_bytes(url: str, *, max_bytes: int) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={"User-Agent": "daedalus-wechat/1.0"},
        method="GET",
    )
    with urlopen(request, timeout=30.0) as response:
        content_type = str(response.headers.get("Content-Type", "")).strip()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError(f"image exceeds max_bytes={max_bytes}")
            chunks.append(chunk)
    return b"".join(chunks), content_type


def download_incoming_image(
    image: IncomingImageRef,
    *,
    target_dir: Path,
    message_id: str,
    cdn_base_url: str = "",
    max_bytes: int = MAX_IMAGE_BYTES,
) -> SavedIncomingImage:
    source_url = image.url
    if image.url:
        payload, content_type = _download_bytes(image.url, max_bytes=max_bytes)
    elif image.media_encrypt_query_param:
        if not cdn_base_url:
            raise RuntimeError("encrypted image requires cdn_base_url")
        source_url = (
            cdn_base_url.rstrip("/")
            + "/download?encrypted_query_param="
            + quote(image.media_encrypt_query_param, safe="")
        )
        encrypted_payload, _ = _download_bytes(source_url, max_bytes=max_bytes)
        payload = _decrypt_aes_128_ecb(
            encrypted_payload,
            key_bytes=_parse_aes_key_bytes(image),
        )
        content_type = ""
    else:
        raise RuntimeError("image_item has no direct url or encrypted media query")
    suffix = _suffix_for_image(content_type=content_type, url=source_url)
    if suffix == ".img":
        suffix = _sniff_image_suffix(payload)
    stem = _safe_token(message_id, fallback="message")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{stem}_{image.index + 1}{suffix}"
    with path.open("wb") as fh:
        fh.write(payload)
    return SavedIncomingImage(
        index=image.index,
        path=path,
        source_url=source_url,
        content_type=content_type,
        size_bytes=len(payload),
    )
