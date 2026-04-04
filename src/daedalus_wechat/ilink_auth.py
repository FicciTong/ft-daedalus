from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .wechat_api import DEFAULT_CDN_BASE_URL

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_ILINK_BOT_TYPE = "3"


@dataclass(frozen=True)
class ILinkQRCode:
    qrcode: str
    qrcode_url: str


@dataclass(frozen=True)
class ILinkLoginResult:
    token: str
    account_id: str
    base_url: str
    user_id: str | None


def _http_json(
    *,
    method: str,
    endpoint: str,
    base_url: str = ILINK_BASE_URL,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 35.0,
) -> dict[str, Any]:
    url = urljoin(base_url.rstrip("/") + "/", endpoint)
    payload = None
    request_headers = dict(headers or {})
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    req = Request(url, data=payload, headers=request_headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"iLink HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"iLink connection failed: {exc}") from exc


def start_ilink_login(*, bot_type: str = DEFAULT_ILINK_BOT_TYPE) -> ILinkQRCode:
    query = urlencode({"bot_type": bot_type})
    payload = _http_json(
        method="GET",
        endpoint=f"ilink/bot/get_bot_qrcode?{query}",
        timeout=10.0,
    )
    qrcode = str(payload.get("qrcode", "")).strip()
    qrcode_url = str(payload.get("qrcode_img_content", "")).strip()
    if not qrcode or not qrcode_url:
        raise RuntimeError("iLink QR response missing qrcode or qrcode_img_content")
    return ILinkQRCode(qrcode=qrcode, qrcode_url=qrcode_url)


def poll_ilink_login(
    *,
    qrcode: str,
    timeout_seconds: float = 480.0,
) -> ILinkLoginResult:
    deadline = time.monotonic() + max(timeout_seconds, 1.0)
    current_base_url = ILINK_BASE_URL
    while time.monotonic() < deadline:
        query = urlencode({"qrcode": qrcode})
        payload = _http_json(
            method="GET",
            endpoint=f"ilink/bot/get_qrcode_status?{query}",
            base_url=current_base_url,
            timeout=35.0,
        )
        status = str(payload.get("status", "")).strip()
        if status in {"wait", "scaned"}:
            time.sleep(1.0)
            continue
        if status == "scaned_but_redirect":
            redirect_host = str(payload.get("redirect_host", "")).strip()
            if redirect_host:
                current_base_url = f"https://{redirect_host}"
            time.sleep(1.0)
            continue
        if status == "expired":
            raise RuntimeError(
                "iLink QR code expired; rerun auth-ilink to get a fresh QR code"
            )
        if status == "confirmed":
            token = str(payload.get("bot_token", "")).strip()
            account_id = str(payload.get("ilink_bot_id", "")).strip()
            base_url = str(payload.get("baseurl", "")).strip() or current_base_url
            user_id = str(payload.get("ilink_user_id", "")).strip() or None
            if not token or not account_id:
                raise RuntimeError(
                    "iLink confirmed response missing bot_token or ilink_bot_id"
                )
            return ILinkLoginResult(
                token=token,
                account_id=account_id,
                base_url=base_url,
                user_id=user_id,
            )
        raise RuntimeError(f"Unexpected iLink login status: {status or 'unknown'}")
    raise RuntimeError("Timed out waiting for iLink QR confirmation")


def write_bridge_account(*, account_file: Path, result: ILinkLoginResult) -> None:
    account_file.parent.mkdir(parents=True, exist_ok=True)
    account_file.write_text(
        json.dumps(
            {
                "token": result.token,
                "baseUrl": result.base_url,
                "cdnBaseUrl": DEFAULT_CDN_BASE_URL,
                "accountId": result.account_id,
                "userId": result.user_id,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
