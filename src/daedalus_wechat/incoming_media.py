from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
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


def download_incoming_image(
    image: IncomingImageRef,
    *,
    target_dir: Path,
    message_id: str,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> SavedIncomingImage:
    if not image.url:
        raise RuntimeError("image_item has no direct url")
    request = Request(
        image.url,
        headers={"User-Agent": "daedalus-wechat/1.0"},
        method="GET",
    )
    with urlopen(request, timeout=30.0) as response:
        content_type = str(response.headers.get("Content-Type", "")).strip()
        suffix = _suffix_for_image(content_type=content_type, url=image.url)
        stem = _safe_token(message_id, fallback="message")
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{stem}_{image.index + 1}{suffix}"
        total = 0
        with path.open("wb") as fh:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    path.unlink(missing_ok=True)
                    raise RuntimeError(f"image exceeds max_bytes={max_bytes}")
                fh.write(chunk)
    return SavedIncomingImage(
        index=image.index,
        path=path,
        source_url=image.url,
        content_type=content_type,
        size_bytes=total,
    )
