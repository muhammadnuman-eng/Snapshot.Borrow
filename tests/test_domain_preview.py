from datetime import UTC, datetime, timedelta

from lumenstage.domain.preview_checker import PreviewHoldChecker
from lumenstage.models.preview_hold import PreviewHold


def test_preview_hold_lifted() -> None:
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert PreviewHoldChecker().is_lifted(
        PreviewHold.create("Night preview_hold", "night", metadata={"lift_at": past})
    )
