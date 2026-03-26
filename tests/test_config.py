from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.config import _parse_allowed_users, load_config


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
                "DAEDALUS_WECHAT_ALLOWED_USERS=user-a@im.wechat,user-b@im.wechat\n"
                "DAEDALUS_WECHAT_TMUX_SESSION=my-tmux\n"
                "DAEDALUS_WECHAT_PROGRESS_UPDATES=on\n"
                "DAEDALUS_WECHAT_OUTBOX_RETRY_INTERVAL_SECONDS=0.75\n"
            )
            with patch.dict(
                os.environ,
                {"DAEDALUS_WECHAT_ENV_FILE": str(env_file)},
                clear=False,
            ):
                config = load_config()
            self.assertEqual(
                config.allowed_users,
                frozenset({"user-a@im.wechat", "user-b@im.wechat"}),
            )
            self.assertEqual(config.canonical_tmux_session, "my-tmux")
            self.assertTrue(config.progress_updates_default)
            self.assertEqual(config.outbox_retry_interval_seconds, 0.75)

    def test_load_config_defaults_progress_updates_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bridge.env"
            env_file.write_text("")
            with patch.dict(
                os.environ,
                {"DAEDALUS_WECHAT_ENV_FILE": str(env_file)},
                clear=False,
            ):
                config = load_config()
            self.assertTrue(config.progress_updates_default)
            self.assertEqual(config.outbox_retry_interval_seconds, 1.0)


if __name__ == "__main__":
    unittest.main()
