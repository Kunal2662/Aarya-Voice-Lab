"""Real Voice Model Engine milestone — model lifecycle state machine.

A voice model artifact moves through a small, explicit set of states.
Transitions are validated here so that "did this model actually finish
training" and "is this model safe to expose in preview/generation" are
questions answered by code, not by convention.

This module holds no data of its own: `pipeline.model_artifact.ModelArtifact`
carries the current `ModelLifecycleState` as a field, and every state
change is expected to be persisted through that record's own registry
(append-only, mirroring every other history log in this project).
"""

from __future__ import annotations

from enum import StrEnum


class ModelLifecycleState(StrEnum):
    #: Registered, not yet trained.
    DRAFT = "DRAFT"
    #: A training job is in progress against this model id.
    TRAINING = "TRAINING"
    #: Training finished; automated/human evaluation is in progress.
    EVALUATING = "EVALUATING"
    #: Evaluation passed whatever criteria were configured.
    VALIDATED = "VALIDATED"
    #: Validated and eligible to be selected for use.
    AVAILABLE = "AVAILABLE"
    #: Currently the selected model for its model_type/profile.
    ACTIVE = "ACTIVE"
    #: Retired; kept for provenance, never selectable for new generation.
    ARCHIVED = "ARCHIVED"
    #: Training or evaluation failed; not usable.
    FAILED = "FAILED"


class InvalidModelTransitionError(ValueError):
    """Raised when a requested lifecycle transition is not permitted."""


#: The only transitions this milestone permits. Deliberately conservative:
#: a model can always be archived or fail, but can never skip evaluation,
#: and can never leave ARCHIVED/FAILED (a new model id is required instead
#: of reviving an old one, the same "append, never mutate history"
#: discipline every other registry in this project follows).
VALID_TRANSITIONS: dict[ModelLifecycleState, frozenset[ModelLifecycleState]] = {
    ModelLifecycleState.DRAFT: frozenset({ModelLifecycleState.TRAINING, ModelLifecycleState.FAILED}),
    ModelLifecycleState.TRAINING: frozenset({ModelLifecycleState.EVALUATING, ModelLifecycleState.FAILED}),
    ModelLifecycleState.EVALUATING: frozenset({ModelLifecycleState.VALIDATED, ModelLifecycleState.FAILED}),
    ModelLifecycleState.VALIDATED: frozenset({ModelLifecycleState.AVAILABLE, ModelLifecycleState.FAILED}),
    ModelLifecycleState.AVAILABLE: frozenset({ModelLifecycleState.ACTIVE, ModelLifecycleState.ARCHIVED}),
    ModelLifecycleState.ACTIVE: frozenset({ModelLifecycleState.ARCHIVED}),
    ModelLifecycleState.ARCHIVED: frozenset(),
    ModelLifecycleState.FAILED: frozenset(),
}


def can_transition(current: ModelLifecycleState, target: ModelLifecycleState) -> bool:
    return target in VALID_TRANSITIONS.get(current, frozenset())


def transition(current: ModelLifecycleState, target: ModelLifecycleState) -> ModelLifecycleState:
    """Return `target` if the move from `current` is permitted, else raise."""
    if not can_transition(current, target):
        allowed = sorted(s.value for s in VALID_TRANSITIONS.get(current, frozenset()))
        raise InvalidModelTransitionError(
            f"cannot transition model lifecycle from {current.value} to {target.value}; "
            f"allowed from {current.value}: {allowed}"
        )
    return target
