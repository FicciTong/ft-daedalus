from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import secrets
from pathlib import Path
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def _random_wechat_uin() -> str:
    value = secrets.randbelow(2**32)
    return base64.b64encode(str(value).encode()).decode()


def _generate_client_id() -> str:
    return f"codex-wechat-bridge:{secrets.token_hex(8)}"


def _derive_account_id(token: str, path: Path) -> str:
    token_prefix = token.split(":", 1)[0].strip()
    if token_prefix:
        return (
            token_prefix.replace("@", "-")
            .replace(".", "-")
            .replace("/", "-")
            .replace("\\", "-")
        )
    return path.stem


@dataclass(frozen=True)
class WeChatAccount:
    token: str
    base_url: str
    account_id: str
    user_id: str | None

    @classmethod
    def load(cls, path: Path) -> "WeChatAccount":
        obj = json.loads(path.read_text())
        token = obj.get("token", "").strip()
        base_url = obj.get("baseUrl", "").strip()
        account_id = obj.get("accountId", "").strip() or _derive_account_id(token, path)
        user_id = obj.get("userId")
        if not token or not base_url or not account_id:
            raise RuntimeError(f"Incomplete WeChat account file: {path}")
        return cls(token=token, base_url=base_url, account_id=account_id, user_id=user_id)


class WeChatClient:
    def __init__(
        self,
        account: WeChatAccount,
        *,
        min_send_interval_seconds: float = 0.5,
    ) -> None:
        self.account = account
        self.min_send_interval_seconds = max(0.0, float(min_send_interval_seconds))
        self._send_lock = threading.Lock()
        self._last_send_at = 0.0

    def _post(self, endpoint: str, payload: dict[str, Any], timeout: float = 40.0) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        req = Request(
            urljoin(self.account.base_url.rstrip("/") + "/", endpoint),
            data=body,
            headers={
                "Content-Type": "application/json",
                "AuthorizationType": "ilink_bot_token",
                "Authorization": f"Bearer {self.account.token}",
                "X-WECHAT-UIN": _random_wechat_uin(),
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"WeChat HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"WeChat connection failed: {exc}") from exc

    def get_updates(self, get_updates_buf: str) -> dict[str, Any]:
        return self._post(
            "ilink/bot/getupdates",
            {"get_updates_buf": get_updates_buf, "base_info": {}},
            timeout=40.0,
        )

    def send_text(self, *, to_user_id: str, context_token: str | None, text: str) -> dict[str, Any]:
        with self._send_lock:
            now = time.monotonic()
            remaining = self.min_send_interval_seconds - (now - self._last_send_at)
            if remaining > 0:
                time.sleep(remaining)
            self._last_send_at = time.monotonic()

            payload = {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": _generate_client_id(),
                    "message_type": 2,
                    "message_state": 2,
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                    "context_token": context_token,
                },
                "base_info": {},
            }
            response = self._post("ilink/bot/sendmessage", payload, timeout=20.0)
            errcode = response.get("errcode")
            ret = response.get("ret")
            if errcode in (None, 0) and ret in (None, 0):
                return response
            # Official WeChat chat contexts can expire even when the user/chat binding is
            # still valid. Retry once without the context token so delivery can continue
            # instead of forcing a manual rebind.
            if ret == -2 and context_token:
                retry_payload = {
                    "msg": {
                        **payload["msg"],
                        "context_token": None,
                    },
                    "base_info": payload["base_info"],
                }
                response = self._post("ilink/bot/sendmessage", retry_payload, timeout=20.0)
                errcode = response.get("errcode")
                ret = response.get("ret")
                if errcode in (None, 0) and ret in (None, 0):
                    return response
            raise RuntimeError(
                f"WeChat send failed: ret={ret} errcode={errcode} errmsg={response.get('errmsg')}"
            )


def body_from_item_list(item_list: list[dict[str, Any]] | None) -> str:
    if not item_list:
        return ""
    for item in item_list:
        if item.get("type") == 1:
            return str(item.get("text_item", {}).get("text", ""))
        if item.get("type") == 3:
            text = item.get("voice_item", {}).get("text")
            if text:
                return str(text)
    return ""
