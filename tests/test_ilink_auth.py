from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.ilink_auth import (
    ILinkLoginResult,
    load_local_bot_tokens,
    poll_ilink_login,
    start_ilink_login,
    write_bridge_account,
)


class ILinkAuthTests(unittest.TestCase):
    def test_start_ilink_login_reads_qr_fields(self) -> None:
        with patch(
            "daedalus_wechat.ilink_auth._http_json",
            return_value={
                "qrcode": "qr-token",
                "qrcode_img_content": "https://example.com/qr.png",
            },
        ) as http:
            qr = start_ilink_login(local_tokens=[" tok-a ", "", "tok-b"])

        self.assertEqual(qr.qrcode, "qr-token")
        self.assertEqual(qr.qrcode_url, "https://example.com/qr.png")
        self.assertEqual(http.call_args.kwargs["method"], "POST")
        self.assertEqual(
            http.call_args.kwargs["body"],
            {"local_token_list": ["tok-a", "tok-b"]},
        )

    def test_start_ilink_login_falls_back_to_get_when_post_is_rejected(
        self,
    ) -> None:
        with patch(
            "daedalus_wechat.ilink_auth._http_json",
            side_effect=[
                RuntimeError("iLink HTTP 405: method not allowed"),
                {
                    "qrcode": "qr-token",
                    "qrcode_img_content": "https://example.com/qr.png",
                },
            ],
        ) as http:
            qr = start_ilink_login(local_tokens=["tok-a"])

        self.assertEqual(qr.qrcode, "qr-token")
        self.assertEqual(http.call_args_list[0].kwargs["method"], "POST")
        self.assertEqual(http.call_args_list[1].kwargs["method"], "GET")

    def test_poll_ilink_login_returns_confirmed_result(self) -> None:
        with patch(
            "daedalus_wechat.ilink_auth._http_json",
            side_effect=[
                {"status": "wait"},
                {
                    "status": "confirmed",
                    "bot_token": "bot-token",
                    "ilink_bot_id": "bot@im.bot",
                    "baseurl": "https://ilinkai.weixin.qq.com",
                    "ilink_user_id": "user@im.wechat",
                },
            ],
        ):
            result = poll_ilink_login(qrcode="qr-token", timeout_seconds=2)

        self.assertEqual(result.token, "bot-token")
        self.assertEqual(result.account_id, "bot@im.bot")
        self.assertEqual(result.base_url, "https://ilinkai.weixin.qq.com")
        self.assertEqual(result.user_id, "user@im.wechat")
        self.assertFalse(result.already_connected)

    def test_poll_ilink_login_returns_already_connected_on_binded_redirect(
        self,
    ) -> None:
        with patch(
            "daedalus_wechat.ilink_auth._http_json",
            return_value={"status": "binded_redirect"},
        ):
            result = poll_ilink_login(qrcode="qr-token", timeout_seconds=2)

        self.assertTrue(result.already_connected)
        self.assertEqual(result.token, "")

    def test_load_local_bot_tokens_reads_existing_account_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            account_file = tmp_path / "account.json"
            account_file.write_text('{"token":"tok-main"}\n', encoding="utf-8")
            older = tmp_path / "older.json"
            older.write_text('{"token":"tok-old"}\n', encoding="utf-8")
            bad = tmp_path / "bad.json"
            bad.write_text("{not-json", encoding="utf-8")

            tokens = load_local_bot_tokens(account_file=account_file)

        self.assertEqual(tokens[0], "tok-main")
        self.assertIn("tok-old", tokens)

    def test_write_bridge_account_writes_daedalus_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            account_file = Path(tmpdir) / "account.json"
            write_bridge_account(
                account_file=account_file,
                result=ILinkLoginResult(
                    token="bot-token",
                    account_id="bot@im.bot",
                    base_url="https://ilinkai.weixin.qq.com",
                    user_id="user@im.wechat",
                ),
            )
            payload = json.loads(account_file.read_text(encoding="utf-8"))

        self.assertEqual(payload["token"], "bot-token")
        self.assertEqual(payload["accountId"], "bot@im.bot")
        self.assertEqual(payload["baseUrl"], "https://ilinkai.weixin.qq.com")
        self.assertEqual(payload["userId"], "user@im.wechat")
        self.assertEqual(payload["cdnBaseUrl"], "https://novac2c.cdn.weixin.qq.com/c2c")

    def test_write_bridge_account_rejects_already_connected_without_new_token(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(RuntimeError, "already connected"):
                write_bridge_account(
                    account_file=Path(tmpdir) / "account.json",
                    result=ILinkLoginResult(
                        token="",
                        account_id="",
                        base_url="https://ilinkai.weixin.qq.com",
                        user_id=None,
                        already_connected=True,
                    ),
                )


if __name__ == "__main__":
    unittest.main()
