"""LMU Telemetry Analyzer - post-session telemetry analysis for Le Mans Ultimate.

Layering (dependencies point strictly downward):

    ui / export  ->  analysis  ->  core
    ingest       ->  core

`analysis` must never import from `ingest`, `ui`, `storage` or Qt. It takes
numpy arrays in and returns numbers out, which is what makes it testable
without the game installed and what would let a live data source replace the
file reader later without touching a single formula.
"""

__version__ = "0.1.0"
