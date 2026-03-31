from __future__ import annotations

import tempfile
from pathlib import Path

from daedalus_wechat.state import BridgeState


def test_state_round_trip_persists_outbox_waiting_for_bind_since() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"
        state = BridgeState(
            outbox_waiting_for_bind=True,
            outbox_waiting_for_bind_since="2026-03-31T12:00:00+00:00",
        )

        state.save(state_file)
        reloaded = BridgeState.load(state_file)

        assert reloaded.outbox_waiting_for_bind is True
        assert (
            reloaded.outbox_waiting_for_bind_since
            == "2026-03-31T12:00:00+00:00"
        )
