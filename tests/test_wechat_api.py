from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.wechat_api import (
    DEFAULT_CDN_BASE_URL,
    MEDIA_TYPE_FILE,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    WeChatAccount,
    WeChatClient,
)


class _RetryClient(WeChatClient):
    def __init__(self) -> None:
        super().__init__(
            WeChatAccount(
                token="token",
                base_url="http://localhost",
                cdn_base_url="http://cdn.localhost",
                account_id="test-bot",
                user_id=None,
            )
        )
        self.payloads: list[dict] = []
        self._calls = 0

    def _post(self, endpoint: str, payload: dict, timeout: float = 40.0) -> dict:
        self.payloads.append(payload)
        self._calls += 1
        if self._calls == 1:
            return {"ret": -2}
        return {"ret": 0}


class WeChatApiTests(unittest.TestCase):
    def test_load_defaults_cdn_base_url_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "account.json"
            path.write_text(
                '{\n'
                '  "token": "tok",\n'
                '  "baseUrl": "https://ilinkai.weixin.qq.com",\n'
                '  "accountId": "bot",\n'
                '  "userId": "u@im.wechat"\n'
                '}\n',
                encoding="utf-8",
            )
            account = WeChatAccount.load(path)
            self.assertEqual(account.cdn_base_url, DEFAULT_CDN_BASE_URL)

    def test_send_text_retries_without_context_token_on_ret_minus_2(self) -> None:
        client = _RetryClient()
        response = client.send_text(
            to_user_id="user@im.wechat",
            context_token="ctx-1",
            text="HELLO",
        )
        self.assertEqual(response["ret"], 0)
        self.assertEqual(len(client.payloads), 2)
        self.assertEqual(client.payloads[0]["msg"]["context_token"], "ctx-1")
        self.assertNotIn("context_token", client.payloads[1]["msg"])
        self.assertNotEqual(
            client.payloads[0]["msg"]["client_id"],
            client.payloads[1]["msg"]["client_id"],
        )

    def test_send_text_omits_context_token_when_none(self) -> None:
        """Desktop-mirror traffic passes context_token=None. The first request
        must omit the field entirely instead of sending `null`, which WeChat
        treats as an invalid token (ret=-2) and would otherwise leave the
        pending outbox permanently stuck."""

        class _OkClient(WeChatClient):
            def __init__(self) -> None:
                super().__init__(
                    WeChatAccount(
                        token="token",
                        base_url="http://localhost",
                        cdn_base_url="http://cdn.localhost",
                        account_id="test-bot",
                        user_id=None,
                    )
                )
                self.payloads: list[dict] = []

            def _post(self, endpoint: str, payload: dict, timeout: float = 40.0) -> dict:
                self.payloads.append(payload)
                return {"ret": 0}

        client = _OkClient()
        response = client.send_text(
            to_user_id="user@im.wechat",
            context_token=None,
            text="HELLO",
        )
        self.assertEqual(response["ret"], 0)
        self.assertEqual(len(client.payloads), 1)
        self.assertNotIn("context_token", client.payloads[0]["msg"])

    def test_send_text_omits_context_token_when_empty_string(self) -> None:
        class _OkClient(WeChatClient):
            def __init__(self) -> None:
                super().__init__(
                    WeChatAccount(
                        token="token",
                        base_url="http://localhost",
                        cdn_base_url="http://cdn.localhost",
                        account_id="test-bot",
                        user_id=None,
                    )
                )
                self.payloads: list[dict] = []

            def _post(self, endpoint: str, payload: dict, timeout: float = 40.0) -> dict:
                self.payloads.append(payload)
                return {"ret": 0}

        client = _OkClient()
        client.send_text(to_user_id="user@im.wechat", context_token="", text="HELLO")
        self.assertNotIn("context_token", client.payloads[0]["msg"])


class _MediaCapturingClient(WeChatClient):
    """Captures sendmessage / getuploadurl POST payloads and mocks the CDN
    PUT so outbound-media tests can verify the iLink protocol shape without
    actually talking to Tencent."""

    def __init__(self) -> None:
        super().__init__(
            WeChatAccount(
                token="token",
                base_url="http://localhost",
                cdn_base_url="http://cdn.localhost",
                account_id="test-bot",
                user_id=None,
            )
        )
        self.posts: list[tuple[str, dict]] = []
        self.cdn_puts: list[tuple[str, int]] = []

    def _post(self, endpoint: str, payload: dict, timeout: float = 40.0) -> dict:
        self.posts.append((endpoint, payload))
        if endpoint == "ilink/bot/getuploadurl":
            return {"upload_param": f"UP_{len(self.posts)}"}
        return {"ret": 0}

    def _cdn_upload_encrypted(
        self, *, upload_param: str, filekey: str, encrypted: bytes
    ) -> str:
        self.cdn_puts.append((upload_param, len(encrypted)))
        return f"QP_{upload_param}"


class OutboundMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        # Stub out the openssl subprocess with a deterministic pad so the
        # tests don't depend on the host's openssl being installed.
        self._aes_patch = patch(
            "daedalus_wechat.wechat_api._aes_128_ecb_encrypt",
            side_effect=lambda raw, *, key_bytes: raw + b"\x00" * (
                16 - (len(raw) % 16 or 16)
            ),
        )
        self._aes_patch.start()

    def tearDown(self) -> None:
        self._aes_patch.stop()

    def test_send_file_emits_file_item_with_expected_protocol_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.pdf"
            path.write_bytes(b"PDF-BINARY-PAYLOAD")
            client = _MediaCapturingClient()
            client.send_file(
                to_user_id="user@im.wechat",
                context_token="ctx-1",
                file_path=path,
            )
        # getuploadurl then sendmessage
        self.assertEqual(client.posts[0][0], "ilink/bot/getuploadurl")
        upload_req = client.posts[0][1]
        self.assertEqual(upload_req["media_type"], MEDIA_TYPE_FILE)
        self.assertEqual(upload_req["to_user_id"], "user@im.wechat")
        self.assertEqual(upload_req["rawsize"], len(b"PDF-BINARY-PAYLOAD"))
        self.assertTrue(upload_req["no_need_thumb"])
        self.assertEqual(len(upload_req["aeskey"]), 32)  # 16 bytes = 32 hex
        # CDN PUT happened once with the encrypted blob
        self.assertEqual(len(client.cdn_puts), 1)
        # sendmessage
        self.assertEqual(client.posts[1][0], "ilink/bot/sendmessage")
        send_msg = client.posts[1][1]["msg"]
        item = send_msg["item_list"][0]
        self.assertEqual(item["type"], 4)
        file_item = item["file_item"]
        self.assertEqual(file_item["file_name"], "report.pdf")
        self.assertEqual(file_item["len"], str(len(b"PDF-BINARY-PAYLOAD")))
        self.assertEqual(file_item["media"]["encrypt_type"], 1)
        self.assertTrue(file_item["media"]["encrypt_query_param"].startswith("QP_"))

    def test_send_image_emits_image_item_with_no_need_thumb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "snap.jpg"
            path.write_bytes(b"\xff\xd8\xff" + b"A" * 1000)
            client = _MediaCapturingClient()
            client.send_image(
                to_user_id="user@im.wechat",
                context_token="ctx-1",
                image_path=path,
            )
        self.assertEqual(client.posts[0][0], "ilink/bot/getuploadurl")
        self.assertEqual(client.posts[0][1]["media_type"], MEDIA_TYPE_IMAGE)
        self.assertTrue(client.posts[0][1]["no_need_thumb"])
        self.assertEqual(client.posts[1][0], "ilink/bot/sendmessage")
        item = client.posts[1][1]["msg"]["item_list"][0]
        self.assertEqual(item["type"], 2)
        self.assertEqual(item["image_item"]["media"]["encrypt_type"], 1)
        self.assertEqual(len(item["image_item"]["aeskey"]), 32)

    def test_send_video_emits_video_item_with_thumb_and_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "clip.mp4"
            video_path.write_bytes(b"FAKE-VIDEO-BYTES" * 10)
            client = _MediaCapturingClient()
            with patch(
                "daedalus_wechat.wechat_api._probe_video_duration_ms",
                return_value=18320,
            ), patch(
                "daedalus_wechat.wechat_api._probe_video_thumb_jpeg",
                return_value=b"\xff\xd8\xffTHUMB",
            ):
                client.send_video(
                    to_user_id="user@im.wechat",
                    context_token="ctx-1",
                    video_path=video_path,
                )
        # Two getuploadurl (video + thumb) + one sendmessage
        endpoints = [ep for ep, _ in client.posts]
        self.assertEqual(
            endpoints,
            ["ilink/bot/getuploadurl", "ilink/bot/getuploadurl", "ilink/bot/sendmessage"],
        )
        self.assertEqual(client.posts[0][1]["media_type"], MEDIA_TYPE_VIDEO)
        self.assertFalse(client.posts[0][1]["no_need_thumb"])
        self.assertEqual(client.posts[1][1]["media_type"], MEDIA_TYPE_IMAGE)
        item = client.posts[2][1]["msg"]["item_list"][0]
        self.assertEqual(item["type"], 5)
        video_item = item["video_item"]
        self.assertEqual(video_item["play_length"], 18320)
        self.assertIn("thumb_media", video_item)
        self.assertEqual(video_item["thumb_media"]["encrypt_type"], 1)

    def test_send_file_retries_without_context_token_on_ret_minus_2(self) -> None:
        class _RetryMediaClient(_MediaCapturingClient):
            def __init__(self) -> None:
                super().__init__()
                self._send_calls = 0

            def _post(self, endpoint: str, payload: dict, timeout: float = 40.0) -> dict:
                self.posts.append((endpoint, payload))
                if endpoint == "ilink/bot/getuploadurl":
                    return {"upload_param": f"UP_{len(self.posts)}"}
                self._send_calls += 1
                if self._send_calls == 1:
                    return {"ret": -2}
                return {"ret": 0}

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "doc.txt"
            path.write_bytes(b"hello")
            client = _RetryMediaClient()
            client.send_file(
                to_user_id="user@im.wechat",
                context_token="ctx-1",
                file_path=path,
            )
        # Expect getuploadurl + sendmessage(fail) + sendmessage(retry without token)
        endpoints = [ep for ep, _ in client.posts]
        self.assertEqual(endpoints[0], "ilink/bot/getuploadurl")
        self.assertEqual(endpoints[1], "ilink/bot/sendmessage")
        self.assertEqual(endpoints[2], "ilink/bot/sendmessage")
        self.assertEqual(client.posts[1][1]["msg"].get("context_token"), "ctx-1")
        self.assertNotIn("context_token", client.posts[2][1]["msg"])


if __name__ == "__main__":
    unittest.main()
