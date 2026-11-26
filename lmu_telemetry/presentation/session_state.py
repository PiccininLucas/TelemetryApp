"""What the window remembers: the open sessions and what is on screen.

Plain Python and no widgets, so the rules about which session stays open, what
a comparison is drawn against and what an export reads can be reasoned about
without a window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from lmu_telemetry.application import pipeline
from lmu_telemetry.application.ports import CatalogGateway, OpenedSession, SessionLoader
from lmu_telemetry.domain.analysis.consistency import ConsistencyReport
from lmu_telemetry.domain.analysis.delta import DeltaResult
from lmu_telemetry.domain.analysis.ideal_lap import IdealLap
from lmu_telemetry.domain.models import Lap
from lmu_telemetry.presentation.session_browser import LapSelection


class ComparisonMode(str, Enum):
    """What the selected lap is drawn against."""

    #: One lap on its own.
    NONE = "none"
    #: The fastest comparable lap of the same session. The default: it answers
    #: "where did this lap lose time against my own best" without any setup.
    SESSION_BEST = "session_best"
    #: A lap the user pinned, possibly from another session, so a whole
    #: afternoon can be measured against one benchmark.
    PINNED = "pinned"
    #: The theoretical ideal lap, stitched from the best segment of every lap
    #: of the session. A target, not a record - see `IdealLap.CAVEAT`.
    IDEAL = "ideal"


@dataclass(slots=True)
class CurrentView:
    """Everything currently on screen, kept so it can be exported.

    Rebuilding it at export time would mean re-deriving the comparison and the
    ideal lap, and any divergence between the two derivations would produce a
    file that does not match what the user was looking at when they asked for
    it. Recording what was drawn is the only way to guarantee they agree.
    """

    selection: LapSelection
    primary: pipeline.LapAnalysis
    primary_label: str
    benchmark: pipeline.LapAnalysis | None = None
    benchmark_label: str = ""
    #: The same lap without the gap, for prose that supplies the gap itself.
    benchmark_summary: str = ""
    delta: DeltaResult | None = None
    ideal: IdealLap | None = None
    corner_rows: list[pipeline.CornerRow] = field(default_factory=list)
    consistency: ConsistencyReport | None = None


class OpenSession:
    """One open session file and its analysed laps.

    Opening a session costs about 80 ms and each lap's analysis a few tens of
    milliseconds, so caching the analysed laps makes moving between laps of one
    session instant.
    """

    def __init__(
        self,
        session_id: str,
        session: OpenedSession,
        track_length_m: float | None,
        name_match_tolerance_m: float,
    ) -> None:
        self.session_id = session_id
        self.session = session
        self.track_length_m = track_length_m
        self._name_match_tolerance_m = name_match_tolerance_m
        self._laps: dict[int, pipeline.LapAnalysis | None] = {}
        self._session_analysis: pipeline.SessionAnalysis | None = None
        #: `(distance_m, name)` for every corner the user has named at this
        #: track, applied to each lap as it is analysed.
        self.corner_references: list[tuple[float, str]] = []

    def analysis_for(self, lap_index: int) -> pipeline.LapAnalysis | None:
        if lap_index not in self._laps:
            lap = self._lap(lap_index)
            self._laps[lap_index] = (
                pipeline.analyse_lap(self.session, lap, self.track_length_m)
                if lap is not None else None
            )
        analysis = self._laps[lap_index]
        if analysis is not None:
            pipeline.name_corners(analysis, self.corner_references)
        return analysis

    def rename_corner(self, distance_m: float, name: str) -> None:
        """Apply a new name immediately, without re-analysing the session."""
        # The corner being renamed is the nearest named one within tolerance -
        # the same rule the catalog applies - not one at exactly this distance:
        # the apex of the same corner sits a metre or two elsewhere on another
        # lap, and an exact match would leave two names competing for it.
        tolerance = self._name_match_tolerance_m
        nearest = min(
            (ref for ref in self.corner_references
             if abs(ref[0] - distance_m) <= tolerance),
            key=lambda ref: abs(ref[0] - distance_m),
            default=None,
        )
        self.corner_references = [
            ref for ref in self.corner_references if ref is not nearest
        ] + [(distance_m, name)]
        for analysis in self._laps.values():
            if analysis is not None:
                pipeline.name_corners(analysis, self.corner_references)
        # The ideal lap and the consistency report snapshot the labels, so they
        # have to be rebuilt rather than patched. Cheap: the laps themselves are
        # kept, and only the stitching and the statistics are redone.
        self._session_analysis = None

    def _lap(self, lap_index: int) -> Lap | None:
        return next((lap for lap in self.session.laps if lap.index == lap_index), None)

    def session_analysis(self) -> pipeline.SessionAnalysis:
        """Every comparable lap analysed, and the ideal lap built from them.

        Cached: it costs a few tens of milliseconds per lap, so a thirteen-lap
        race is about half a second. Paid once, on the first request, rather
        than on opening a session that the user may only want one lap of.
        """
        if self._session_analysis is None:
            self._session_analysis = pipeline.analyse_session(
                self.session, self.track_length_m,
                corner_references=self.corner_references,
                # Laps already analysed for display are not analysed twice, and
                # the ones analysed here are kept for the next lap shown.
                precomputed=self._laps,
            )
            for index, analysis in self._session_analysis.laps.items():
                self._laps.setdefault(index, analysis)
        return self._session_analysis

    def best_comparable_lap(self, exclude_index: int | None = None) -> Lap | None:
        """The session's fastest comparable lap, ignoring one index.

        Read from the lap list rather than from the analyses, so choosing the
        benchmark does not require analysing every lap of the session first.
        """
        candidates = [
            lap for lap in self.session.comparable_laps
            if lap.index != exclude_index and lap.time_s > 0
        ]
        return min(candidates, key=lambda lap: lap.time_s, default=None)

    def close(self) -> None:
        self.session.close()


class SessionPool:
    """The open session files, at most `capacity` of them.

    Two is enough: the interface never draws more than two laps at once, and a
    comparison against a pinned lap from another afternoon needs both files
    open. Beyond that, holding files open only leaks handles.
    """

    def __init__(
        self, loader: SessionLoader, catalog: CatalogGateway, capacity: int = 2
    ) -> None:
        self._loader = loader
        self._catalog = catalog
        self._capacity = capacity
        self._open: dict[str, OpenSession] = {}
        #: Session ids, least recently used first.
        self._order: list[str] = []

    def get(self, selection: LapSelection) -> OpenSession:
        """Open the selection's session, reusing it when it is already open.

        Raises:
            TelemetryError: When the file cannot be read.
        """
        session_id = selection.session_id
        if session_id in self._open:
            self._touch(session_id)
            return self._open[session_id]

        track_length = self._catalog.track_length(selection.track_name)
        references = [
            (reference.reference_distance_m, reference.name)
            for reference in self._catalog.corner_references(selection.track_name)
            if reference.reference_distance_m is not None and reference.name
        ]
        session = self._loader.load(selection.source_path)

        self._open[session_id] = OpenSession(
            session_id, session, track_length, self._catalog.name_match_tolerance_m()
        )
        self._open[session_id].corner_references = references
        self._touch(session_id)
        self._evict()
        return self._open[session_id]

    def _touch(self, session_id: str) -> None:
        if session_id in self._order:
            self._order.remove(session_id)
        self._order.append(session_id)

    def _evict(self) -> None:
        while len(self._order) > self._capacity:
            oldest = self._order.pop(0)
            self._open.pop(oldest).close()

    def all(self) -> list[OpenSession]:
        return list(self._open.values())

    def close_all(self) -> None:
        for opened in self._open.values():
            opened.close()
        self._open.clear()
        self._order.clear()

    def __len__(self) -> int:
        return len(self._open)
