from __future__ import annotations

import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.incoming_media import (
    IncomingFileRef,
    IncomingImageRef,
    IncomingVideoRef,
    download_incoming_file,
    download_incoming_image,
    download_incoming_video,
)


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

    def test_download_incoming_image_decrypts_media_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image = IncomingImageRef(
                index=0,
                media_encrypt_query_param="encrypted-query",
                aes_key="00112233445566778899aabbccddeeff",
                has_media_info=True,
            )
            encrypted_body = b"encrypted-body"
            with patch(
                "daedalus_wechat.incoming_media._download_bytes",
                return_value=(encrypted_body, "application/octet-stream"),
            ), patch(
                "daedalus_wechat.incoming_media._decrypt_aes_128_ecb",
                return_value=b"\x89PNG\r\n\x1a\nplaintext",
            ):
                saved = download_incoming_image(
                    image,
                    target_dir=Path(tmpdir),
                    message_id="msg-enc",
                    cdn_base_url="https://ilinkai.weixin.qq.com",
                )
            self.assertEqual(saved.path.suffix, ".png")
            self.assertTrue(
                saved.source_url.startswith(
                    "https://ilinkai.weixin.qq.com/download?encrypted_query_param="
                )
            )

    def test_download_incoming_image_allows_plain_cdn_fallback_without_aes_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image = IncomingImageRef(
                index=0,
                media_encrypt_query_param="encrypted-query",
                has_media_info=True,
            )
            plain_body = b"\x89PNG\r\n\x1a\nplaintext"
            with patch(
                "daedalus_wechat.incoming_media._download_bytes",
                return_value=(plain_body, "image/png"),
            ), patch(
                "daedalus_wechat.incoming_media._decrypt_aes_128_ecb"
            ) as decrypt_mock:
                saved = download_incoming_image(
                    image,
                    target_dir=Path(tmpdir),
                    message_id="msg-plain",
                    cdn_base_url="https://ilinkai.weixin.qq.com",
                )
            decrypt_mock.assert_not_called()
            self.assertEqual(saved.path.suffix, ".png")
            self.assertEqual(saved.path.read_bytes(), plain_body)

    def test_download_incoming_file_decrypts_media_query_and_preserves_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_ref = IncomingFileRef(
                index=0,
                file_name="report.pdf",
                media_encrypt_query_param="encrypted-query",
                media_aes_key="MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
            )
            encrypted_body = b"encrypted-body"
            with patch(
                "daedalus_wechat.incoming_media._download_bytes",
                return_value=(encrypted_body, "application/octet-stream"),
            ), patch(
                "daedalus_wechat.incoming_media._decrypt_aes_128_ecb",
                return_value=b"%PDF-1.7\nfake-pdf",
            ):
                saved = download_incoming_file(
                    file_ref,
                    target_dir=Path(tmpdir),
                    message_id="msg-file",
                    cdn_base_url="https://ilinkai.weixin.qq.com",
                )
            self.assertEqual(saved.path.suffix, ".pdf")
            self.assertEqual(saved.file_name, "report.pdf")
            self.assertEqual(saved.path.read_bytes(), b"%PDF-1.7\nfake-pdf")

    def test_download_incoming_file_requires_aes_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_ref = IncomingFileRef(
                index=0,
                file_name="report.pdf",
                media_encrypt_query_param="encrypted-query",
            )
            with self.assertRaisesRegex(RuntimeError, "missing aes key"):
                download_incoming_file(
                    file_ref,
                    target_dir=Path(tmpdir),
                    message_id="msg-file",
                    cdn_base_url="https://ilinkai.weixin.qq.com",
                )

    def test_download_incoming_video_decrypts_media_query_and_defaults_mp4(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_ref = IncomingVideoRef(
                index=0,
                media_encrypt_query_param="encrypted-query",
                media_aes_key="MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
            )
            encrypted_body = b"encrypted-body"
            with patch(
                "daedalus_wechat.incoming_media._download_bytes",
                return_value=(encrypted_body, "video/mp4"),
            ), patch(
                "daedalus_wechat.incoming_media._decrypt_aes_128_ecb",
                return_value=b"\x00\x00\x00\x18ftypmp42fake-video",
            ):
                saved = download_incoming_video(
                    video_ref,
                    target_dir=Path(tmpdir),
                    message_id="msg-video",
                    cdn_base_url="https://ilinkai.weixin.qq.com",
                )
            self.assertEqual(saved.path.suffix, ".mp4")
            self.assertEqual(saved.path.read_bytes(), b"\x00\x00\x00\x18ftypmp42fake-video")

    def test_download_incoming_video_requires_aes_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_ref = IncomingVideoRef(
                index=0,
                media_encrypt_query_param="encrypted-query",
            )
            with self.assertRaisesRegex(RuntimeError, "missing aes key"):
                download_incoming_video(
                    video_ref,
                    target_dir=Path(tmpdir),
                    message_id="msg-video",
                    cdn_base_url="https://ilinkai.weixin.qq.com",
                )
