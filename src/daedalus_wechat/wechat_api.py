from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"

# iLink getuploadurl media_type enum (distinct from item_list type codes).
MEDIA_TYPE_IMAGE = 1
MEDIA_TYPE_VIDEO = 2
MEDIA_TYPE_FILE = 3
MEDIA_TYPE_VOICE = 4


def _random_wechat_uin() -> str:
    value = secrets.randbelow(2**32)
    return base64.b64encode(str(value).encode()).decode()


def _generate_client_id() -> str:
    return f"daedalus-wechat:{secrets.token_hex(8)}"


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
    cdn_base_url: str
    account_id: str
    user_id: str | None

    @classmethod
    def load(cls, path: Path) -> WeChatAccount:
        obj = json.loads(path.read_text())
        token = obj.get("token", "").strip()
        base_url = obj.get("baseUrl", "").strip()
        cdn_base_url = obj.get("cdnBaseUrl", "").strip() or DEFAULT_CDN_BASE_URL
        account_id = obj.get("accountId", "").strip() or _derive_account_id(token, path)
        user_id = obj.get("userId")
        if not token or not base_url or not account_id:
            raise RuntimeError(f"Incomplete WeChat account file: {path}")
        return cls(
            token=token,
            base_url=base_url,
            cdn_base_url=cdn_base_url,
            account_id=account_id,
            user_id=user_id,
        )


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

    def get_config(self, *, ilink_user_id: str) -> dict[str, Any]:
        """Fetch bot config including typing_ticket used by sendtyping.
        The ilink_user_id scopes the config to a specific user chat."""
        return self._post(
            "ilink/bot/getconfig",
            {
                "ilink_user_id": ilink_user_id,
                "base_info": {"channel_version": "1.0.0"},
            },
            timeout=20.0,
        )

    def send_typing(
        self,
        *,
        to_user_id: str,
        typing_ticket: str,
        status: int = 1,
    ) -> dict[str, Any]:
        """Send a typing indicator to the given user. `status=1` starts the
        "typing" signal, `status=2` cancels it. Protocol level this endpoint
        does not require a context_token; it uses typing_ticket obtained via
        get_config()."""
        return self._post(
            "ilink/bot/sendtyping",
            {
                "ilink_user_id": to_user_id,
                "typing_ticket": typing_ticket,
                "status": int(status),
                "base_info": {"channel_version": "1.0.0"},
            },
            timeout=15.0,
        )

    def send_text(self, *, to_user_id: str, context_token: str | None, text: str) -> dict[str, Any]:
        with self._send_lock:
            now = time.monotonic()
            remaining = self.min_send_interval_seconds - (now - self._last_send_at)
            if remaining > 0:
                time.sleep(remaining)
            self._last_send_at = time.monotonic()

            msg: dict[str, Any] = {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": _generate_client_id(),
                "message_type": 2,
                "message_state": 2,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            }
            # Only include context_token when truthy. The official WeChat
            # server treats `"context_token": null` as an invalid token and
            # returns `ret=-2`, which would otherwise leave desktop-mirror
            # traffic (which deliberately sends tokenless) permanently stuck
            # in the bridge's pending_outbox.
            if context_token:
                msg["context_token"] = context_token
            payload = {"msg": msg, "base_info": {}}
            response = self._post("ilink/bot/sendmessage", payload, timeout=20.0)
            errcode = response.get("errcode")
            ret = response.get("ret")
            if errcode in (None, 0) and ret in (None, 0):
                return response
            # Official WeChat chat contexts can expire even when the user/chat
            # binding is still valid. Retry once without the context token so
            # delivery can continue instead of forcing a manual rebind.
            if ret == -2 and context_token:
                retry_msg = {k: v for k, v in msg.items() if k != "context_token"}
                retry_msg["client_id"] = _generate_client_id()
                retry_payload = {"msg": retry_msg, "base_info": {}}
                response = self._post("ilink/bot/sendmessage", retry_payload, timeout=20.0)
                errcode = response.get("errcode")
                ret = response.get("ret")
                if errcode in (None, 0) and ret in (None, 0):
                    return response
            raise RuntimeError(
                f"WeChat send failed: ret={ret} errcode={errcode} errmsg={response.get('errmsg')}"
            )


    # ------------------------------------------------------------------
    # Outbound media (image / file / video) — iLink bot protocol
    #
    # Flow per-send:
    #   1. read bytes, compute raw MD5 + random AES-128 key
    #   2. AES-128-ECB + PKCS7 encrypt → ciphertext
    #   3. POST /ilink/bot/getuploadurl → upload_param
    #   4. PUT ciphertext to CDN upload URL → response header
    #      `x-encrypted-param` (this is the sendmessage encrypt_query_param)
    #   5. POST /ilink/bot/sendmessage with the matching item_list entry
    #
    # The same AES key + encrypt_query_param are echoed in sendmessage so the
    # receiving WeChat client can pull and decrypt from the CDN.
    # ------------------------------------------------------------------

    def send_file(
        self,
        *,
        to_user_id: str,
        context_token: str | None,
        file_path: Path,
        file_name: str | None = None,
    ) -> dict[str, Any]:
        path = Path(file_path)
        raw = path.read_bytes()
        name = str(file_name or path.name).strip() or path.name
        ref = self._upload_media_bytes(
            to_user_id=to_user_id,
            raw=raw,
            media_type=MEDIA_TYPE_FILE,
            no_need_thumb=True,
        )
        item = {
            "type": 4,
            "file_item": {
                "media": {
                    "encrypt_query_param": ref.encrypt_query_param,
                    "aes_key": ref.aes_key_b64,
                    "encrypt_type": 1,
                },
                "file_name": name,
                "md5": ref.raw_md5_hex,
                "len": str(len(raw)),
            },
        }
        return self._send_message_with_items(
            to_user_id=to_user_id,
            context_token=context_token,
            item_list=[item],
        )

    def send_image(
        self,
        *,
        to_user_id: str,
        context_token: str | None,
        image_path: Path,
    ) -> dict[str, Any]:
        path = Path(image_path)
        raw = path.read_bytes()
        ref = self._upload_media_bytes(
            to_user_id=to_user_id,
            raw=raw,
            media_type=MEDIA_TYPE_IMAGE,
            no_need_thumb=True,
        )
        item = {
            "type": 2,
            "image_item": {
                "media": {
                    "encrypt_query_param": ref.encrypt_query_param,
                    "aes_key": ref.aes_key_b64,
                    "encrypt_type": 1,
                },
                "aeskey": ref.aes_key_hex,
                "mid_size": ref.encrypted_size,
            },
        }
        return self._send_message_with_items(
            to_user_id=to_user_id,
            context_token=context_token,
            item_list=[item],
        )

    def send_video(
        self,
        *,
        to_user_id: str,
        context_token: str | None,
        video_path: Path,
    ) -> dict[str, Any]:
        path = Path(video_path)
        raw = path.read_bytes()
        play_length_ms = _probe_video_duration_ms(path)
        thumb_bytes = _probe_video_thumb_jpeg(path)
        video_ref = self._upload_media_bytes(
            to_user_id=to_user_id,
            raw=raw,
            media_type=MEDIA_TYPE_VIDEO,
            no_need_thumb=False,
        )
        thumb_ref = self._upload_media_bytes(
            to_user_id=to_user_id,
            raw=thumb_bytes,
            media_type=MEDIA_TYPE_IMAGE,
            no_need_thumb=True,
        )
        item = {
            "type": 5,
            "video_item": {
                "media": {
                    "encrypt_query_param": video_ref.encrypt_query_param,
                    "aes_key": video_ref.aes_key_b64,
                    "encrypt_type": 1,
                },
                "video_size": video_ref.encrypted_size,
                "play_length": play_length_ms,
                "video_md5": video_ref.raw_md5_hex,
                "thumb_media": {
                    "encrypt_query_param": thumb_ref.encrypt_query_param,
                    "aes_key": thumb_ref.aes_key_b64,
                    "encrypt_type": 1,
                },
                "thumb_size": thumb_ref.encrypted_size,
            },
        }
        return self._send_message_with_items(
            to_user_id=to_user_id,
            context_token=context_token,
            item_list=[item],
        )

    # ---- internal helpers (media) -----------------------------------

    def _send_message_with_items(
        self,
        *,
        to_user_id: str,
        context_token: str | None,
        item_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": _generate_client_id(),
            "message_type": 2,
            "message_state": 2,
            "item_list": item_list,
        }
        if context_token:
            msg["context_token"] = context_token
        response = self._post(
            "ilink/bot/sendmessage",
            {"msg": msg, "base_info": {}},
            timeout=30.0,
        )
        errcode = response.get("errcode")
        ret = response.get("ret")
        if errcode in (None, 0) and ret in (None, 0):
            return response
        if ret == -2 and context_token:
            retry_msg = {k: v for k, v in msg.items() if k != "context_token"}
            retry_msg["client_id"] = _generate_client_id()
            response = self._post(
                "ilink/bot/sendmessage",
                {"msg": retry_msg, "base_info": {}},
                timeout=30.0,
            )
            errcode = response.get("errcode")
            ret = response.get("ret")
            if errcode in (None, 0) and ret in (None, 0):
                return response
        raise RuntimeError(
            f"WeChat media send failed: ret={ret} errcode={errcode} "
            f"errmsg={response.get('errmsg')}"
        )

    def _upload_media_bytes(
        self,
        *,
        to_user_id: str,
        raw: bytes,
        media_type: int,
        no_need_thumb: bool,
    ) -> _UploadedMediaRef:
        if not raw:
            raise RuntimeError("cannot upload empty media payload")
        aes_key_bytes = secrets.token_bytes(16)
        aes_key_hex = aes_key_bytes.hex()
        aes_key_b64 = base64.b64encode(aes_key_hex.encode("ascii")).decode("ascii")
        raw_md5 = hashlib.md5(raw, usedforsecurity=False).hexdigest()
        raw_size = len(raw)
        encrypted = _aes_128_ecb_encrypt(raw, key_bytes=aes_key_bytes)
        encrypted_size = len(encrypted)
        filekey = secrets.token_hex(16)

        upload_req = {
            "filekey": filekey,
            "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": raw_size,
            "rawfilemd5": raw_md5,
            "filesize": encrypted_size,
            "no_need_thumb": bool(no_need_thumb),
            "aeskey": aes_key_hex,
            "base_info": {"channel_version": "1.0.0"},
        }
        upload_resp = self._post(
            "ilink/bot/getuploadurl",
            upload_req,
            timeout=30.0,
        )
        errcode = upload_resp.get("errcode")
        ret = upload_resp.get("ret")
        if errcode not in (None, 0) or ret not in (None, 0):
            raise RuntimeError(
                f"WeChat getuploadurl failed: ret={ret} errcode={errcode} "
                f"errmsg={upload_resp.get('errmsg')}"
            )
        upload_param = str(upload_resp.get("upload_param") or "").strip()
        if not upload_param:
            raise RuntimeError("WeChat getuploadurl returned empty upload_param")
        encrypt_query_param = self._cdn_upload_encrypted(
            upload_param=upload_param,
            filekey=filekey,
            encrypted=encrypted,
        )
        return _UploadedMediaRef(
            aes_key_hex=aes_key_hex,
            aes_key_b64=aes_key_b64,
            raw_md5_hex=raw_md5,
            encrypted_size=encrypted_size,
            encrypt_query_param=encrypt_query_param,
        )

    def _cdn_upload_encrypted(
        self, *, upload_param: str, filekey: str, encrypted: bytes
    ) -> str:
        # iLink CDN protocol: POST (not PUT) with the encrypted blob as the
        # body, encrypted_query_param carrying the upload_param from
        # getuploadurl, and the same filekey we sent earlier. No auth
        # headers — the upload_param itself is the presigned credential.
        cdn = self.account.cdn_base_url.rstrip("/")
        url = (
            f"{cdn}/upload"
            f"?encrypted_query_param={quote(upload_param, safe='')}"
            f"&filekey={quote(filekey, safe='')}"
        )
        req = Request(
            url,
            data=encrypted,
            headers={"Content-Type": "application/octet-stream"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=60.0) as resp:
                header = resp.headers.get("x-encrypted-param", "").strip()
                if not header:
                    raise RuntimeError(
                        "CDN upload did not return x-encrypted-param header"
                    )
                return header
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"CDN upload HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"CDN upload failed: {exc}") from exc


@dataclass(frozen=True)
class _UploadedMediaRef:
    aes_key_hex: str
    aes_key_b64: str
    raw_md5_hex: str
    encrypted_size: int
    encrypt_query_param: str


def _aes_128_ecb_encrypt(raw: bytes, *, key_bytes: bytes) -> bytes:
    """Encrypt `raw` with AES-128-ECB + PKCS7 padding via the openssl CLI.
    Mirrors the decrypt path in incoming_media.py so outbound and inbound
    share the same crypto dependency surface.
    """
    proc = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-128-ecb",
            "-nosalt",
            "-K",
            key_bytes.hex(),
        ],
        input=raw,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"openssl encrypt failed: {proc.stderr.decode(errors='replace').strip()}"
        )
    return proc.stdout


def _probe_video_duration_ms(path: Path) -> int:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed for {path}: {proc.stderr.decode(errors='replace').strip()}"
        )
    try:
        seconds = float(proc.stdout.decode().strip())
    except ValueError as exc:
        raise RuntimeError(f"ffprobe returned unparseable duration: {exc}") from exc
    return max(int(round(seconds * 1000.0)), 1)


def _probe_video_thumb_jpeg(path: Path) -> bytes:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-q:v",
            "4",
            "-f",
            "image2",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(
            f"ffmpeg thumb extract failed for {path}: "
            f"{proc.stderr.decode(errors='replace').strip()}"
        )
    return proc.stdout


def _guess_mime_for_path(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


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
