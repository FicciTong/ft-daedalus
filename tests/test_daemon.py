from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_wechat_bridge.config import BridgeConfig
from codex_wechat_bridge.daemon import BridgeDaemon
from codex_wechat_bridge.state import BridgeState


class _FakeWeChat:
    pass


class _FakeRunner:
    def try_live_session(self, state: BridgeState):
        return None


class DaemonTests(unittest.TestCase):
    def _make_config(self, state_dir: Path, allowed_users: frozenset[str]) -> BridgeConfig:
        return BridgeConfig(
            codex_bin="codex",
            account_file=state_dir / "account.json",
            state_dir=state_dir,
            default_cwd=Path("/tmp"),
            openclaw_profile="codex-wechat-bridge",
            canonical_tmux_session="codex",
            allowed_users=allowed_users,
        )

    def test_authorized_sender_allowed_when_allowlist_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = BridgeDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            self.assertTrue(daemon._is_authorized_sender("any-user"))

    def test_authorized_sender_respects_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = BridgeDaemon(
                config=self._make_config(
                    Path(tmpdir), frozenset({"allowed-user@im.wechat"})
                ),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            self.assertTrue(daemon._is_authorized_sender("allowed-user@im.wechat"))
            self.assertFalse(daemon._is_authorized_sender("other-user@im.wechat"))


if __name__ == "__main__":
    unittest.main()
