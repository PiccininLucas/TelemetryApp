"""What a report needs, gathered by the caller.

Lives in the application layer because it is made of pipeline results: the
interface and the scripts assemble it, and `infrastructure.export.report`
renders it. Neither side has to import the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from lmu_telemetry.application import pipeline
    from lmu_telemetry.domain.analysis.consistency import ConsistencyReport
    from lmu_telemetry.domain.analysis.delta import DeltaResult
    from lmu_telemetry.domain.analysis.friction import FrictionEnvelope
    from lmu_telemetry.domain.analysis.ideal_lap import IdealLap

#: The map palettes a report can use.
MAP_SCHEMES = ("loss", "pedal")


@dataclass(frozen=True, slots=True)
class ReportContext:
    """Everything a report needs, gathered by the caller.

    Assembled by whoever has access to the session - the interface or a script -
    so this module stays a renderer and never opens a file of its own.

    Attributes:
        track_name: Circuit.
        car_name: Car.
        session_label: "Corrida", "Treino livre" and so on.
        session_date: When it was recorded.
        lap_number: The lap being reported.
        primary: Its `pipeline.LapAnalysis`.
        primary_label: How to name it in the legend.
        benchmark: The comparison lap's analysis, if any.
        benchmark_label: How to name it in the chart legend, where the gap is
            useful because nothing else on the image states it.
        benchmark_summary: How to name it in the prose line, which supplies the
            gap itself. Separate from the legend label so the sentence does not
            come out as "Referência: referência: volta 4 … · diferença …".
        delta: The delta between them.
        corner_rows: `pipeline.CornerRow` objects.
        ideal: The session's `IdealLap`, if built.
        consistency: The stint's `ConsistencyReport`, if measurable.
        envelope: The lap's `FrictionEnvelope`, if available.
        transition_quality: Fraction of working time with both axes loaded.
        track_path: `(x_m, y_m)` of the circuit, if GPS was recorded.
        map_classes: Per-metre integer classes colouring the map - pedal state
            when there is no comparison, gain and loss when there is.
        map_scheme: Which palette those classes index: `"loss"` (gain and loss
            against a benchmark) or `"pedal"`. A name rather than the colours,
            so whoever builds the context need not know the renderer.
    """

    track_name: str
    car_name: str
    session_label: str
    session_date: datetime | None
    lap_number: int
    primary: pipeline.LapAnalysis
    primary_label: str
    benchmark: pipeline.LapAnalysis | None = None
    benchmark_label: str = ""
    benchmark_summary: str = ""
    delta: DeltaResult | None = None
    corner_rows: list[pipeline.CornerRow] | None = None
    ideal: IdealLap | None = None
    consistency: ConsistencyReport | None = None
    envelope: FrictionEnvelope | None = None
    transition_quality: float = 0.0
    track_path: tuple[np.ndarray, np.ndarray] | None = None
    map_classes: np.ndarray | None = None
    map_scheme: str | None = None
