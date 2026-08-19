"""Capability states used across environment/toolchain inspection.

Phase 1 requires every detected capability to be classified rather than
reported as a bare boolean, because "missing" and "broken" and "not
needed here" call for very different operator responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CapabilityState(StrEnum):
    #: Present and usable.
    AVAILABLE = "AVAILABLE"
    #: Genuinely absent. Whether this matters depends on the stage.
    NOT_AVAILABLE = "NOT_AVAILABLE"
    #: Absent, and that is fine — nothing required depends on it.
    OPTIONAL = "OPTIONAL"
    #: Present but at a version/configuration that must not be used.
    INCOMPATIBLE = "INCOMPATIBLE"
    #: Could not be determined (probe failed, ambiguous, not probeable here).
    UNKNOWN = "UNKNOWN"


#: States that must never be treated as "ready to run".
BLOCKING_STATES = frozenset({CapabilityState.NOT_AVAILABLE, CapabilityState.INCOMPATIBLE})


@dataclass(frozen=True)
class Capability:
    """One inspected capability and why it landed in its state."""

    name: str
    state: CapabilityState
    detail: str = ""
    version: str | None = None

    @property
    def ok(self) -> bool:
        return self.state in (CapabilityState.AVAILABLE, CapabilityState.OPTIONAL)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "state": self.state.value,
            "detail": self.detail,
            "version": self.version,
        }

    def format_line(self) -> str:
        version = f" ({self.version})" if self.version else ""
        detail = f" — {self.detail}" if self.detail else ""
        return f"[{self.state.value:<14}] {self.name}{version}{detail}"
