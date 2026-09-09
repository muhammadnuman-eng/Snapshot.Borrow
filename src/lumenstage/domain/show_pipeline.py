"""High-level content pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lumenstage.domain.preview_checker import PreviewHoldChecker
from lumenstage.domain.workflow_engine import WorkflowDefinition, WorkflowEngine
from lumenstage.errors import WorkflowError
from lumenstage.models.preview_hold import PreviewHold
from lumenstage.models.production import Production


@dataclass(slots=True)
class PipelineResult:
    production_id: str
    stage: str
    publishable: bool
    notes: list[str] = field(default_factory=list)


class ContentPipeline:
    def __init__(self, workflow: WorkflowDefinition, *, grace_minutes: int = 15) -> None:
        self.engine = WorkflowEngine(workflow)
        self.preview_holds = PreviewHoldChecker(grace_minutes)

    def evaluate(
        self,
        production: Production,
        *,
        completed_stages: list[str],
        preview_holds: list[PreviewHold],
    ) -> PipelineResult:
        notes: list[str] = []
        stage = str(production.metadata.get("stage", "draft"))
        publishable = self.engine.is_complete(completed_stages)
        try:
            self.preview_holds.assert_publishable(preview_holds)
        except WorkflowError as exc:
            publishable = False
            notes.append(str(exc))
        if production.status != "active":
            publishable = False
            notes.append("production is not active")
        return PipelineResult(production.id, stage, publishable, notes)

    def advance(self, production: Production, completed_stages: list[str]) -> dict[str, Any]:
        stage = str(production.metadata.get("stage", "draft"))
        nxt = self.engine.next_stage(stage)
        if not nxt:
            raise WorkflowError("already at final stage")
        self.engine.validate_transition(stage, nxt)
        production.merge_metadata({"stage": nxt})
        return {"from": stage, "to": nxt, "completed": completed_stages}
