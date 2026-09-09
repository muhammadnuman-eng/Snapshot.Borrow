"""Runtime configuration for LumenStage."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path("data"))
    default_showbook_slug: str = "main"
    max_page_size: int = 100
    enable_licensing: bool = True
    enable_box_office: bool = True
    preview_hold_grace_minutes: int = 15
    staging_review_stages: tuple[str, ...] = ("draft", "copyedit", "legal", "published")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    data = os.environ.get("LUMENSTAGE_DATA_DIR")
    return Settings(
        data_dir=Path(data) if data else Path("data"),
        default_showbook_slug=os.environ.get("LUMENSTAGE_SHOWBOOK", "main"),
        max_page_size=int(os.environ.get("LUMENSTAGE_PAGE_SIZE", "100")),
        enable_licensing=os.environ.get("LUMENSTAGE_LICENSING", "1") == "1",
        enable_box_office=os.environ.get("LUMENSTAGE_BOX_OFFICE", "1") == "1",
        preview_hold_grace_minutes=int(os.environ.get("LUMENSTAGE_PREVIEW_HOLD_GRACE", "15")),
    )
