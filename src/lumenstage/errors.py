"""LumenStage exception hierarchy."""

from __future__ import annotations


class LumenStageError(Exception):
    """Base error for LumenStage."""


class ValidationError(LumenStageError):
    """Raised when input fails validation."""


class NotFoundError(LumenStageError):
    """Raised when a requested resource does not exist."""


class ConflictError(LumenStageError):
    """Raised when an operation conflicts with current state."""


class StorageError(LumenStageError):
    """Raised when persistence fails."""


class WorkflowError(LumenStageError):
    """Raised when production workflow rules are violated."""
