from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.ilink_auth import (
    ILinkLoginResult,
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
        ):
            qr = start_ilink_login()

        self.assertEqual(qr.qrcode, "qr-token")
        self.assertEqual(qr.qrcode_url, "https://example.com/qr.png")

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


if __name__ == "__main__":
    unittest.main()
