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


def test_state_round_trip_persists_pending_media_batches() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"
        state = BridgeState()
        state.add_pending_media_batch(
            batch_id="batch-1",
            from_user_id="user@im.wechat",
            message_id="msg-1",
            image_paths=["/tmp/a.jpg", "/tmp/b.jpg"],
            created_at="2026-04-10T00:00:00+00:00",
        )

        state.save(state_file)
        reloaded = BridgeState.load(state_file)

        assert len(reloaded.pending_media_batches) == 1
        batch = reloaded.pending_media_batches[0]
        assert batch.batch_id == "batch-1"
        assert batch.from_user_id == "user@im.wechat"
        assert batch.message_id == "msg-1"
        assert batch.image_paths == ["/tmp/a.jpg", "/tmp/b.jpg"]
