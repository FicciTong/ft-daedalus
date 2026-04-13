from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.delivery_ledger import _last_seq, append_delivery
from daedalus_wechat.state import BridgeState


class DeliveryLedgerTests(unittest.TestCase):
    def test_last_seq_reads_tail_without_path_read_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "deliveries.jsonl"
            payload = [
                {
                    "seq": 1,
                    "ts": "2026-04-13T00:00:00+00:00",
                    "to": "user",
                    "status": "sent",
                    "kind": "relay",
                    "origin": "bridge",
                    "text": "first",
                },
                {
                    "seq": 9,
                    "ts": "2026-04-13T00:01:00+00:00",
                    "to": "user",
                    "status": "sent",
                    "kind": "relay",
                    "origin": "bridge",
                    "text": "latest",
                },
            ]
            ledger_file.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in payload) + "\n",
                encoding="utf-8",
            )

            with patch.object(Path, "read_text", side_effect=AssertionError("read_text not allowed")):
                self.assertEqual(_last_seq(ledger_file), 9)

    def test_append_delivery_advances_seq_without_full_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "deliveries.jsonl"
            ledger_file.write_text(
                json.dumps(
                    {
                        "seq": 5,
                        "ts": "2026-04-13T00:00:00+00:00",
                        "to": "user",
                        "status": "sent",
                        "kind": "relay",
                        "origin": "bridge",
                        "text": "older",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            state = BridgeState(delivery_seq=1)

            with patch.object(Path, "read_text", side_effect=AssertionError("read_text not allowed")):
                seq = append_delivery(
                    state=state,
                    state_file=None,
                    ledger_file=ledger_file,
                    to_user_id="user",
                    text="newer",
                    status="sent",
                    kind="relay",
                    origin="bridge",
                )

            self.assertEqual(seq, 6)
            latest = json.loads(ledger_file.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(latest["seq"], 6)
            self.assertEqual(latest["text"], "newer")


if __name__ == "__main__":
    unittest.main()
