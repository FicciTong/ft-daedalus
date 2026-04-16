from __future__ import annotations

import base64
import mimetypes
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 100 * 1024 * 1024
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
    media_source: str = ""
    media_keys: tuple[str, ...] = ()
    thumb_media_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class SavedIncomingImage:
    index: int
    path: Path
    source_url: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True)
class IncomingFileRef:
    index: int
    file_name: str = ""
    media_encrypt_query_param: str = ""
    media_aes_key: str = ""
    media_full_url: str = ""
    media_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class SavedIncomingFile:
    index: int
    path: Path
    source_url: str
    content_type: str
    size_bytes: int
    file_name: str


@dataclass(frozen=True)
class IncomingVideoRef:
    index: int
    media_encrypt_query_param: str = ""
    media_aes_key: str = ""
    media_full_url: str = ""
    media_keys: tuple[str, ...] = ()
    thumb_media_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class SavedIncomingVideo:
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


def _parse_aes_key_bytes(*, hex_key: str = "", base64_key: str = "") -> bytes | None:
    if hex_key:
        return bytes.fromhex(hex_key)
    if not base64_key:
        return None
    decoded = base64.b64decode(base64_key)
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


def _build_cdn_download_url(
    *, encrypt_query_param: str, media_full_url: str, cdn_base_url: str
) -> str:
    if media_full_url:
        return media_full_url
    if not cdn_base_url:
        raise RuntimeError("encrypted media requires cdn_base_url")
    return (
        cdn_base_url.rstrip("/")
        + "/download?encrypted_query_param="
        + quote(encrypt_query_param, safe="")
    )


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


def _download_encrypted_media(
    *,
    encrypt_query_param: str,
    media_full_url: str,
    media_aes_key: str,
    cdn_base_url: str,
    max_bytes: int,
) -> tuple[bytes, str, str]:
    source_url = _build_cdn_download_url(
        encrypt_query_param=encrypt_query_param,
        media_full_url=media_full_url,
        cdn_base_url=cdn_base_url,
    )
    encrypted_payload, content_type = _download_bytes(source_url, max_bytes=max_bytes)
    key_bytes = _parse_aes_key_bytes(base64_key=media_aes_key)
    if key_bytes is None:
        raise RuntimeError("encrypted media is missing aes key")
    payload = _decrypt_aes_128_ecb(encrypted_payload, key_bytes=key_bytes)
    return payload, source_url, content_type


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
        source_url = _build_cdn_download_url(
            encrypt_query_param=image.media_encrypt_query_param,
            media_full_url="",
            cdn_base_url=cdn_base_url,
        )
        encrypted_payload, content_type = _download_bytes(source_url, max_bytes=max_bytes)
        key_bytes = _parse_aes_key_bytes(
            hex_key=image.aes_key,
            base64_key=image.media_aes_key,
        )
        if key_bytes is None:
            payload = encrypted_payload
        else:
            payload = _decrypt_aes_128_ecb(
                encrypted_payload,
                key_bytes=key_bytes,
            )
            content_type = ""
    else:
        raise RuntimeError("image_item has no direct url or encrypted media query")
    suffix = _suffix_for_image(content_type=content_type, url=source_url)
    if suffix == ".img":
        suffix = _sniff_image_suffix(payload)
    stem = _safe_token(message_id, fallback="message")
    ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{ts}_{stem}_{image.index + 1}{suffix}"
    with path.open("wb") as fh:
        fh.write(payload)
    return SavedIncomingImage(
        index=image.index,
        path=path,
        source_url=source_url,
        content_type=content_type,
        size_bytes=len(payload),
    )


def _suffix_for_file(*, file_name: str, content_type: str, url: str) -> str:
    parsed_name = Path(file_name)
    if parsed_name.suffix.strip():
        return parsed_name.suffix
    lowered = content_type.split(";", 1)[0].strip().lower()
    if lowered:
        guessed = mimetypes.guess_extension(lowered)
        if guessed:
            return guessed
    parsed_url = urlparse(url)
    url_suffix = Path(parsed_url.path).suffix.strip()
    if url_suffix:
        return url_suffix
    return ".bin"


def _suffix_for_video(*, content_type: str, url: str) -> str:
    lowered = content_type.split(";", 1)[0].strip().lower()
    if lowered:
        guessed = mimetypes.guess_extension(lowered)
        if guessed:
            return guessed
    parsed_url = urlparse(url)
    url_suffix = Path(parsed_url.path).suffix.strip()
    if url_suffix:
        return url_suffix
    return ".mp4"


def download_incoming_file(
    file_ref: IncomingFileRef,
    *,
    target_dir: Path,
    message_id: str,
    cdn_base_url: str,
    max_bytes: int = MAX_FILE_BYTES,
) -> SavedIncomingFile:
    if not file_ref.media_encrypt_query_param and not file_ref.media_full_url:
        raise RuntimeError("file_item has no encrypted media query or full url")
    if not file_ref.media_aes_key:
        raise RuntimeError("file_item is missing aes key")
    payload, source_url, content_type = _download_encrypted_media(
        encrypt_query_param=file_ref.media_encrypt_query_param,
        media_full_url=file_ref.media_full_url,
        media_aes_key=file_ref.media_aes_key,
        cdn_base_url=cdn_base_url,
        max_bytes=max_bytes,
    )
    suffix = _suffix_for_file(
        file_name=file_ref.file_name,
        content_type=content_type,
        url=source_url,
    )
    safe_name = _safe_token(Path(file_ref.file_name).stem, fallback=f"file_{file_ref.index + 1}")
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    stem = _safe_token(message_id, fallback="message")
    ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{ts}_{stem}_{file_ref.index + 1}_{safe_name}{safe_suffix}"
    with path.open("wb") as fh:
        fh.write(payload)
    return SavedIncomingFile(
        index=file_ref.index,
        path=path,
        source_url=source_url,
        content_type=content_type,
        size_bytes=len(payload),
        file_name=file_ref.file_name,
    )


def download_incoming_video(
    video_ref: IncomingVideoRef,
    *,
    target_dir: Path,
    message_id: str,
    cdn_base_url: str,
    max_bytes: int = MAX_FILE_BYTES,
) -> SavedIncomingVideo:
    if not video_ref.media_encrypt_query_param and not video_ref.media_full_url:
        raise RuntimeError("video_item has no encrypted media query or full url")
    if not video_ref.media_aes_key:
        raise RuntimeError("video_item is missing aes key")
    payload, source_url, content_type = _download_encrypted_media(
        encrypt_query_param=video_ref.media_encrypt_query_param,
        media_full_url=video_ref.media_full_url,
        media_aes_key=video_ref.media_aes_key,
        cdn_base_url=cdn_base_url,
        max_bytes=max_bytes,
    )
    suffix = _suffix_for_video(content_type=content_type, url=source_url)
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    stem = _safe_token(message_id, fallback="message")
    ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{ts}_{stem}_{video_ref.index + 1}{safe_suffix}"
    with path.open("wb") as fh:
        fh.write(payload)
    return SavedIncomingVideo(
        index=video_ref.index,
        path=path,
        source_url=source_url,
        content_type=content_type or "video/mp4",
        size_bytes=len(payload),
    )
