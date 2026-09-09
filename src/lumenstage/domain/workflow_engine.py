"""Production staging_review workflow engine."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from lumenstage.errors import WorkflowError
from lumenstage.models.staging_review import StagingReview


@dataclass(slots=True)
class WorkflowStage:
    name: str
    required: bool = True
    approvers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkflowDefinition:
    name: str
    stages: list[WorkflowStage]

    def stage_names(self) -> list[str]:
        return [s.name for s in self.stages]


class WorkflowEngine:
    def __init__(self, definition: WorkflowDefinition) -> None:
        self.definition = definition

    def validate_transition(self, current: str, target: str) -> None:
        names = self.definition.stage_names()
        if current not in names:
            raise WorkflowError(f"unknown stage: {current}")
        if target not in names:
            raise WorkflowError(f"unknown target stage: {target}")
        if names.index(target) < names.index(current):
            raise WorkflowError("cannot move workflow backwards without override")

    def next_stage(self, current: str) -> str | None:
        names = self.definition.stage_names()
        idx = names.index(current)
        return None if idx + 1 >= len(names) else names[idx + 1]

    def record_staging_review(
        self,
        staging_reviews: Iterable[StagingReview],
        stage: str,
        staging_reviewer: str,
        approved: bool,
    ) -> StagingReview:
        status = "approved" if approved else "rejected"
        return StagingReview.create(
            f"{stage}-{staging_reviewer}",
            f"{stage}-{staging_reviewer}".lower(),
            metadata={"stage": stage, "staging_reviewer": staging_reviewer, "status": status},
        )

    def pending_stages(self, completed: Iterable[str]) -> list[str]:
        done = set(completed)
        return [s.name for s in self.definition.stages if s.name not in done]

    def is_complete(self, completed: Iterable[str]) -> bool:
        required = {s.name for s in self.definition.stages if s.required}
        return required.issubset(set(completed))
