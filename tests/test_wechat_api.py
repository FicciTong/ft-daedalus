from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from daedalus_wechat.wechat_api import (
    DEFAULT_CDN_BASE_URL,
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


if __name__ == "__main__":
    unittest.main()
