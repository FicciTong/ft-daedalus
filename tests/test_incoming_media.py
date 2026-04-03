from __future__ import annotations

import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.incoming_media import IncomingImageRef, download_incoming_image


class _FakeHTTPResponse:
    def __init__(self, body: bytes, *, content_type: str) -> None:
        self._body = body
        self._offset = 0
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class IncomingMediaTests(unittest.TestCase):
    def test_download_incoming_image_persists_file_with_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image = IncomingImageRef(index=0, url="https://example.com/raw-image")
            body = b"fake-image-bytes"
            with patch(
                "daedalus_wechat.incoming_media.urlopen",
                return_value=_FakeHTTPResponse(body, content_type="image/png"),
            ):
                saved = download_incoming_image(
                    image,
                    target_dir=Path(tmpdir),
                    message_id="msg-123",
                )
            self.assertEqual(saved.path.suffix, ".png")
            self.assertEqual(saved.path.read_bytes(), body)
            self.assertEqual(saved.size_bytes, len(body))

    def test_download_incoming_image_requires_direct_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image = IncomingImageRef(index=0, url="")
            with self.assertRaisesRegex(RuntimeError, "no direct url"):
                download_incoming_image(
                    image,
                    target_dir=Path(tmpdir),
                    message_id="msg-123",
                )
