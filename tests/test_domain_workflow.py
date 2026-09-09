from lumenstage.domain.workflow_engine import WorkflowDefinition, WorkflowEngine, WorkflowStage
from lumenstage.errors import WorkflowError


def test_workflow_progression() -> None:
    engine = WorkflowEngine(
        WorkflowDefinition(
            "standard",
            [WorkflowStage("draft"), WorkflowStage("copyedit"), WorkflowStage("published")],
        )
    )
    assert engine.next_stage("draft") == "copyedit"
    assert engine.is_complete(["draft", "copyedit", "published"])


def test_invalid_transition() -> None:
    engine = WorkflowEngine(
        WorkflowDefinition("standard", [WorkflowStage("draft"), WorkflowStage("published")])
    )
    try:
        engine.validate_transition("published", "draft")
        raise AssertionError("expected WorkflowError")
    except WorkflowError:
        pass
