"""Saving what is on screen: the traces as PNG, the lap and its corners as CSV,
the whole debrief as PDF.

Every export reads the `CurrentView` the window recorded when it drew the lap,
never a fresh analysis, so a file always matches what the user was looking at
when they asked for it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from lmu_telemetry.application import pipeline
from lmu_telemetry.application.ports import Exporter
from lmu_telemetry.application.reporting import ReportContext
from lmu_telemetry.domain.models import parse_session_filename
from lmu_telemetry.presentation.session_browser import LapSelection
from lmu_telemetry.presentation.session_state import CurrentView
from lmu_telemetry.shared import strings
from lmu_telemetry.shared.errors import SessionNameError
from lmu_telemetry.shared.logging_config import get_logger

logger = get_logger(__name__)

#: `(path, excel)`: write the file. `excel` is the CSV dialect the user chose.
Render = Callable[[Path, bool], None]


class LapExporter(QtCore.QObject):
    """The four exports, and the dialog, naming and error handling they share."""

    #: A line for the status bar: exporting, saved, or why not.
    status = QtCore.Signal(str)

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        exporter: Exporter,
        current: Callable[[], CurrentView | None],
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._exporter = exporter
        #: Read at export time: the view on screen when the user asks.
        self._current = current

    def export_png(self) -> None:
        """Redraw the traces at print quality and save them."""
        def render(view: CurrentView, path: Path, _excel: bool) -> None:
            self._exporter.lap_charts(
                path, view.primary, view.primary_label,
                view.benchmark, view.benchmark_label, view.delta,
                view.primary.corners,
            )

        self._export(strings.DIALOG_EXPORT_PNG_TITLE, strings.DIALOG_PNG_FILTER,
                     ".png", render)

    def export_csv(self) -> None:
        """Every channel of the lap, one row per metre."""
        def render(view: CurrentView, path: Path, excel: bool) -> None:
            self._exporter.lap_table(path, view.primary, view.delta, excel=excel)

        self._export(strings.DIALOG_EXPORT_CSV_TITLE, strings.DIALOG_CSV_FILTER,
                     ".csv", render)

    def export_corners_csv(self) -> None:
        def render(view: CurrentView, path: Path, excel: bool) -> None:
            self._exporter.corner_table(path, view.corner_rows, excel=excel)

        self._export(strings.DIALOG_EXPORT_CORNERS_TITLE, strings.DIALOG_CSV_FILTER,
                     ".csv", render)

    def export_pdf(self) -> None:
        """The whole debrief, with its caveats, in one document."""
        def render(view: CurrentView, path: Path, _excel: bool) -> None:
            self._exporter.report(path, report_context(view))

        self._export(strings.DIALOG_EXPORT_PDF_TITLE, strings.DIALOG_PDF_FILTER,
                     ".pdf", render)

    def _export(self, title: str, file_filter: str, suffix: str, render) -> None:
        """Ask where to save, then render there.

        One place for the parts every export shares: refusing when there is
        nothing on screen, appending the extension the user left off, choosing
        the CSV dialect from the filter they picked, and turning a failure into
        a message instead of a traceback behind the window.
        """
        view = self._current()
        if view is None:
            self.status.emit(strings.ERR_EXPORT_NO_LAP)
            return

        path_text, chosen = QtWidgets.QFileDialog.getSaveFileName(
            self._parent, title, suggested_name(view.selection, suffix), file_filter
        )
        if not path_text:
            return

        path = Path(path_text)
        if not path.suffix:
            path = path.with_suffix(suffix)
        excel = chosen == strings.DIALOG_CSV_FILTER_EXCEL

        self.status.emit(strings.STATUS_EXPORTING)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            render(view, path, excel)
        except Exception as exc:  # noqa: BLE001 - a failed save is survivable
            logger.exception("Export to %s failed", path)
            message = strings.ERR_EXPORT_FAILED.format(detail=exc)
            self.status.emit(message)
            QtWidgets.QMessageBox.warning(self._parent, title, message)
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.status.emit(strings.STATUS_EXPORTED.format(path=path))


def suggested_name(selection: LapSelection, suffix: str) -> str:
    """A file name that says what is in it without being opened."""
    track = "".join(
        character for character in selection.track_name
        if character.isalnum() or character in " -_"
    ).strip().replace(" ", "-")
    return f"{track}-volta{selection.lap_number}{suffix}"


def report_context(view: CurrentView) -> ReportContext:
    """Gather everything the PDF needs from what is currently drawn."""
    selection = view.selection

    gps, _integrated = pipeline.track_paths(view.primary)
    track_path = None if gps is None or not len(gps.x_m) else (gps.x_m, gps.y_m)

    # The map is coloured the same way it is on screen: by where time moved
    # when there is a comparison, by pedal state when there is not.
    map_classes = map_scheme = None
    if track_path is not None:
        if view.delta is not None:
            map_classes = pipeline.loss_classes_on(view.primary.grid_m, view.delta)
            map_scheme = "loss"
        else:
            map_classes = pipeline.pedal_states(view.primary)
            map_scheme = "pedal"

    return ReportContext(
        track_name=selection.track_name,
        car_name=selection.car_name or "?",
        session_label=strings.session_type_label(session_code(selection) or "?"),
        session_date=selection.session_started_at,
        lap_number=selection.lap_number,
        primary=view.primary,
        primary_label=view.primary_label,
        benchmark=view.benchmark,
        benchmark_label=view.benchmark_label,
        benchmark_summary=view.benchmark_summary,
        delta=view.delta,
        corner_rows=view.corner_rows,
        ideal=view.ideal,
        consistency=view.consistency,
        envelope=pipeline.friction_envelope(view.primary),
        transition_quality=pipeline.transition_quality(view.primary),
        track_path=track_path,
        map_classes=map_classes,
        map_scheme=map_scheme,
    )


def session_code(selection: LapSelection) -> str | None:
    """The session type letter: the one the selection carries, which the catalog
    took from the file name, or - for a selection built without it - the file
    name itself."""
    if selection.session_type_code:
        return selection.session_type_code
    try:
        _track, code, _when = parse_session_filename(Path(selection.source_path))
    except SessionNameError:
        return None
    return code
