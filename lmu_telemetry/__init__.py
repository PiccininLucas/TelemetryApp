"""LMU Telemetry Analyzer - post-session telemetry analysis for Le Mans Ultimate.

Clean Architecture - dependencies point strictly inward:

    presentation  --                     >-->  application  -->  domain  -->  shared
    infrastructure --/

`shared` is the cross-cutting kernel (strings, errors, config, logging).
`domain` holds the models and every formula in `domain.analysis`; it takes numpy
arrays in and returns numbers out, which is what makes it testable without the
game installed and what would let a live data source replace the file reader
later without touching a single formula. `application` is the pipeline and the
ports it reads through; `infrastructure` is DuckDB ingestion, storage and
export; `presentation` is the PySide6 interface.

The rule is enforced by `tests/test_architecture.py`.
"""

__version__ = "0.1.0"
