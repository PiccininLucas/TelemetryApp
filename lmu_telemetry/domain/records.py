"""Records read back from the catalog.

Plain value objects: what the session browser and the corner naming need to know
about what was imported earlier. They live in the domain so that the interface
can name them without importing the storage code that produces them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SessionRow:
    """One row of the sessions table, as read back."""

    session_id: str
    source_path: Path
    track_id: str
    track_name: str
    car_name: str | None
    car_class: str | None
    session_type: str | None
    started_at: datetime
    weather: str | None
    n_laps: int


@dataclass(frozen=True, slots=True)
class LapRow:
    """One row of the laps table, as the session browser needs it."""

    lap_id: str
    session_id: str
    lap_index: int
    lap_number: int
    time_s: float | None
    flags: tuple[str, ...]
    is_comparable: bool

    @property
    def flag_labels(self) -> list[str]:
        """Portuguese labels for this lap's flags."""
        from lmu_telemetry.shared import strings

        return [strings.LAP_FLAG_LABEL.get(flag, flag) for flag in self.flags]


@dataclass(frozen=True, slots=True)
class CornerReference:
    """A corner the user has named, and where it is.

    The distance is what makes the name durable. Corner *indices* shift the
    moment the detector finds one more or one fewer corner on a lap - a wet lap,
    a lap with a spin - and a name pinned to an index would then move to the
    wrong corner. Pinned to a distance from the line, it stays put.
    """

    corner_index: int
    name: str | None
    reference_distance_m: float | None
