"""Importing session files off the interface thread: the worker that imports,
and the runner that gives it a thread."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore

from lmu_telemetry.application.ports import SessionImporter
from lmu_telemetry.shared.errors import TelemetryError
from lmu_telemetry.shared.logging_config import get_logger

logger = get_logger(__name__)


class ImportWorker(QtCore.QObject):
    """Imports session files off the interface thread.

    Importing a folder hashes and opens every file, which takes seconds per
    dozen sessions. Done on the interface thread it freezes the window, and the
    wait cursor is the only sign it is not hung.

    The worker opens its own catalog connection: a DuckDB connection is not to
    be shared between threads, and nothing else touches the catalog while an
    import runs - the interface refuses to start a second one and reloads the
    browser only once this one is done.
    """

    #: `(done, total, file name)` after each file.
    progress = QtCore.Signal(int, int, str)
    #: `(imported, failures)` when the run ends, however it ends.
    finished = QtCore.Signal(int, list)

    def __init__(self, paths: list[Path], importer: SessionImporter) -> None:
        super().__init__()
        self._paths = paths
        self._importer = importer
        self._cancelled = False

    def cancel(self) -> None:
        """Stop after the file being imported. A plain flag: it is only ever
        set to True, so no lock is needed."""
        self._cancelled = True

    @QtCore.Slot()
    def run(self) -> None:
        imported, failures = 0, []
        try:
            with self._importer.open() as batch:
                for done, path in enumerate(self._paths, start=1):
                    if self._cancelled:
                        break
                    try:
                        batch.import_file(path)
                        imported += 1
                    except TelemetryError as exc:
                        logger.error("Import failed for %s: %s", path.name, exc)
                        failures.append(f"{path.name}: {exc}")
                    except Exception as exc:  # noqa: BLE001 - must reach the user
                        # An unexpected failure on a worker thread would end the
                        # thread without a word. Report it like any other.
                        logger.exception("Import crashed on %s", path.name)
                        failures.append(f"{path.name}: {exc}")
                    self.progress.emit(done, len(self._paths), path.name)
        except Exception as exc:  # noqa: BLE001 - e.g. the catalog cannot be opened
            logger.exception("Import could not run")
            failures.append(str(exc))
        finally:
            self.finished.emit(imported, failures)


class ImportRunner(QtCore.QObject):
    """Runs one import at a time on its own thread.

    The thread bookkeeping - start, refuse a second run, release both objects
    when the run ends, stop cleanly when the window closes - in one place, so
    the window only hears that an import started, progressed and finished.
    """

    #: `(done, total, file name)` after each file.
    progress = QtCore.Signal(int, int, str)
    #: `(imported, failures)` when the run ends.
    finished = QtCore.Signal(int, list)
    #: True when a run starts, False when it ends: for disabling the actions
    #: that would start another.
    busy_changed = QtCore.Signal(bool)

    def __init__(self, importer: SessionImporter, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._importer = importer
        self._thread: QtCore.QThread | None = None
        self._worker: ImportWorker | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start(self, paths: list[Path]) -> bool:
        """Import `paths` in the background.

        Returns:
            False, and does nothing, while another import is running.
        """
        if self._thread is not None:
            return False

        thread = QtCore.QThread(self)
        worker = ImportWorker(paths, self._importer)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)

        self._thread, self._worker = thread, worker
        self.busy_changed.emit(True)
        thread.start()
        return True

    def stop(self) -> None:
        """Let the file being imported finish, then stop and wait.

        An import in flight owns a catalog connection and a file; killing the
        thread would leave both half-written.
        """
        if self._thread is not None and self._worker is not None:
            self._worker.cancel()
            self._thread.quit()
            self._thread.wait()

    def _on_finished(self, imported: int, failures: list) -> None:
        self._thread = self._worker = None
        self.busy_changed.emit(False)
        self.finished.emit(imported, failures)
