from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.config import (
    _parse_allowed_users,
    default_codex_state_db,
    load_config,
)


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
            self.assertTrue(str(config.codex_state_db).endswith(".sqlite"))
            self.assertEqual(config.codex_state_db_source, "default_resolved")

    def test_load_config_marks_explicit_codex_state_db_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bridge.env"
            env_file.write_text(
                "DAEDALUS_WECHAT_CODEX_STATE_DB=/tmp/custom-state.sqlite\n"
            )
            with patch.dict(
                os.environ,
                {"DAEDALUS_WECHAT_ENV_FILE": str(env_file)},
                clear=False,
            ):
                config = load_config()
            self.assertEqual(config.codex_state_db, Path("/tmp/custom-state.sqlite"))
            self.assertEqual(config.codex_state_db_source, "env_file_explicit")

    def test_load_config_defaults_progress_updates_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bridge.env"
            env_file.write_text("")
            with patch.dict(
                os.environ,
                {"DAEDALUS_WECHAT_ENV_FILE": str(env_file)},
                clear=False,
            ):
                config = load_config()
            self.assertFalse(config.progress_updates_default)
            self.assertEqual(config.outbox_retry_interval_seconds, 1.0)

    def test_default_codex_state_db_prefers_canonical_state_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_root = Path(tmpdir) / ".codex"
            codex_root.mkdir(parents=True, exist_ok=True)
            canonical = codex_root / "state.sqlite"
            canonical.write_text("", encoding="utf-8")
            (codex_root / "state_5.sqlite").write_text("", encoding="utf-8")
            with patch("daedalus_wechat.config.Path.home", return_value=Path(tmpdir)):
                resolved = default_codex_state_db()
            self.assertEqual(resolved, canonical)

    def test_default_codex_state_db_falls_back_to_newest_numbered_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_root = Path(tmpdir) / ".codex"
            codex_root.mkdir(parents=True, exist_ok=True)
            older = codex_root / "state_3.sqlite"
            newer = codex_root / "state_7.sqlite"
            older.write_text("", encoding="utf-8")
            newer.write_text("", encoding="utf-8")
            os.utime(older, (1, 1))
            os.utime(newer, None)
            with patch("daedalus_wechat.config.Path.home", return_value=Path(tmpdir)):
                resolved = default_codex_state_db()
            self.assertEqual(resolved, newer)


if __name__ == "__main__":
    unittest.main()
