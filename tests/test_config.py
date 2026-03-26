from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_wechat_bridge.config import _parse_allowed_users, load_config


class ConfigTests(unittest.TestCase):
    def test_parse_allowed_users_empty(self) -> None:
        self.assertEqual(_parse_allowed_users(""), frozenset())

    def test_parse_allowed_users_csv(self) -> None:
        self.assertEqual(
            _parse_allowed_users(" user-a ,user-b,user-a "),
            frozenset({"user-a", "user-b"}),
        )

    def test_load_config_reads_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bridge.env"
            env_file.write_text(
                "CODEX_WECHAT_BRIDGE_ALLOWED_USERS=user-a@im.wechat,user-b@im.wechat\n"
                "CODEX_WECHAT_BRIDGE_TMUX_SESSION=my-tmux\n"
                "CODEX_WECHAT_BRIDGE_PROGRESS_UPDATES=on\n"
            )
            with patch.dict(
                os.environ,
                {"CODEX_WECHAT_BRIDGE_ENV_FILE": str(env_file)},
                clear=False,
            ):
                config = load_config()
            self.assertEqual(
                config.allowed_users,
                frozenset({"user-a@im.wechat", "user-b@im.wechat"}),
            )
            self.assertEqual(config.canonical_tmux_session, "my-tmux")
            self.assertTrue(config.progress_updates_default)


if __name__ == "__main__":
    unittest.main()
