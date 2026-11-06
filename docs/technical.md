# Technical reference

Working documentation for picking the project back up: how it is put together,
where each responsibility lives, what the data looks like at every stage, and
what is known to be rough. It complements two existing documents rather than
repeating them:

- **[README.md](../README.md)** — what the tool does, the evidence behind the
  findings about the game's file format, how to run it.
- **[methodology.md](methodology.md)** — every formula, its assumptions and
  where it breaks down.

This file is the map. Written against commit `0608ded` (all ten phases done);
the package layout was later reorganised into Clean Architecture layers
(`shared`, `domain`, `application`, `infrastructure`, `presentation`), and the
text below follows the new layout. Section 12 is a historical audit and keeps
the old module names.
Section 12 records what an audit found and what was done about it, and what is
still open.

---

## 1. Overview

A desktop application (PySide6) that reads Le Mans Ultimate's native DuckDB
telemetry files and produces a post-session debrief: delta-t against a reference
lap, a corner-by-corner table, a theoretical ideal lap, per-corner consistency
across a stint, a track map, a g-g diagram, and PNG/CSV/PDF export.

| | |
|---|---|
| Language | Python 3.11+ (developed on 3.14; CI runs 3.13 and 3.14) |
| UI | PySide6 6.11 + pyqtgraph 0.14 (on-screen), matplotlib + reportlab (export) |
| Data | DuckDB 1.5 (game files read-only; app catalog), numpy / scipy / pandas |
| Size | ~12.7 k lines in the package, ~1.8 k in scripts, ~6.6 k in tests |
| Language of the UI | Portuguese. Code, identifiers, docs: English |
| Network | None. The application makes no network calls |

Out of scope by design: live telemetry, HUD/overlay, 3D, tyre-degradation
modelling, fuel strategy.

---

## 2. Setup, running, testing

```powershell
uv venv                                   # or: python -m venv .venv
uv pip install -r requirements.txt
.venv\Scripts\Activate.ps1
pytest -q                                 # headless; Qt runs on the offscreen platform
.venv\Scripts\python.exe main.py          # the GUI
```

`main.py` checks that PySide6 imports and, if not, prints the venv interpreter
to use instead of a bare `ModuleNotFoundError` (running with the system Python is
the common mistake on this machine).

Try it without the game — an anonymised Fuji race ships in `data/demo/`:

```powershell
python scripts/import_session.py data/demo/
python main.py
```

### Environment variables

| Variable | Effect |
|---|---|
| `LMU_TELEMETRY_DATA_DIR` | Where the app keeps its catalog, cache and log. Default `~/.lmu-telemetry` |
| `LMU_TELEMETRY_CONFIG` | A TOML file of overrides, instead of `config.toml` in the data directory |
| `LMU_TELEMETRY_DIR` | A folder with real `.duckdb` sessions, for the tests that need one |
| `QT_QPA_PLATFORM` | `tests/test_ui.py` sets `offscreen` itself via `setdefault` |

### Scripts

All scripts put the project root on `sys.path` themselves and run headless
(nothing but `test_ui` and the GUI imports Qt).

| Script | Purpose |
|---|---|
| `inspect_schema.py` | Verify a file's schema against the documented one; `--json` for a machine-readable summary. Phase-1 deliverable |
| `list_laps.py` | Run the full ingestion path and print the lap table, with the `Lap Dist` cross-check |
| `analyse_session.py` | Run the analysis layer and print corners, ideal lap, consistency |
| `import_session.py` | Import files/folders into the catalog; `--show`, `--clear-cache` |
| `export_session.py` | PNG + two CSV dialects + PDF for one lap, without the GUI |
| `make_demo_dataset.py` | Produce the anonymised demo file (never modifies the source) |
| `expected_schema.py` | The *hypothesis* the schema report compares against. Imported by nothing in the package (enforced by a test) |

### Tests

507 test cases in `tests/` (22 modules, many parametrised). Most build a synthetic DuckDB file or a
synthetic lap (`tests/synthetic.py`, a rectangular circuit with known
properties) and run anywhere. Five modules use a real session when one is found
(`conftest.find_real_session`, which looks at `LMU_TELEMETRY_DIR`, then
`D:\SteamLibrary\...` and `C:\Program Files (x86)\Steam\...`) and skip otherwise.
`pytest.ini` turns every warning into an error except `DeprecationWarning`.

CI (`.github/workflows/tests.yml`): ubuntu, Python 3.13 and 3.14, `pytest -q`.

---

## 3. Repository map

```
main.py                     entry point: logging → QApplication → theme → MainWindow
config/defaults.toml        every numeric threshold of ingest/analysis
lmu_telemetry/
  shared/                   cross-cutting kernel; imports nothing from the project
    strings.py                every user-visible string (pure data)
    errors.py                 TelemetryError hierarchy
    config.py                 Config (dotted-path access), load_config (lru_cache'd)
    logging_config.py         setup_logging, get_logger
    formatting.py             format_lap_time, format_gap, format_value
  domain/                   numpy/scipy/stdlib only
    models.py                 SessionInfo, Lap, LapFlag, Corner, Stint, filename parser, SHA-256
    units.py                  unit conversion driven by the file's own `unit` column
    records.py                SessionRow, LapRow, CornerReference (catalog rows)
    resampling.py             resample_to_grid, step_interpolate (pure numpy)
    analysis/                 numpy in, numbers out
      distance.py  resample.py  delta.py  corners.py  ideal_lap.py
      consistency.py  friction.py  trackmap.py
  application/              joins the two; knows no file format, database or GUI
    pipeline.py               the seam: session → analysis; what UI and export call
    ports.py                  SessionData, and the gateways the UI works through
    reporting.py              ReportContext: what a PDF report is built from
  composition.py            composition root: builds the gateways; nothing imports it
  infrastructure/           implements what the inner layers need
    adapters.py               DuckDbCatalog, FileSessionLoader, DuckDbSessionImporter,
                              FileExporter, build_gateways()
    ingest/                   the only layer that knows the file format
      duckdb_reader.py          read-only connection, quote_ident, column reads
      channel_registry.py       layout detection (A/B/C/D), ChannelInfo, read_channel
      time_base.py              implicit clock, GPS Time validation/correction
      events.py                 EventSeries (step series from layouts C/D)
      lap_splitter.py           lap boundaries, official times, sectors, flags
      corrections.py            the swapped/negated G-force channels
      session_loader.py         Session aggregate + load_session()  ← the ingestion entry point
    storage/                  paths.py, catalog.py (DuckDB), cache.py (JSON manifest), importer.py
    export/                   charts.py (matplotlib), tables.py (CSV), report.py (PDF), anonymise.py
  presentation/             PySide6
    main_window, session_state, import_worker, session_browser, chart_panel,
    track_map, gg_panel, corner_table, consistency_panel, theme
scripts/                    CLI tools (section 2)
tests/                      pytest suite + synthetic data builders
data/demo/                  one anonymised session, the only .duckdb tracked in git
docs/                       methodology.md, this file, screenshots
docs-site/                  Astro site: the front-end redesign plan
```

---

## 4. Architecture

### Layering

Clean Architecture; dependencies point inward only.

```
   presentation ──┐
   (PySide6)      │
                  ├──▶ application ──▶ domain ──▶ shared
   infrastructure ┘    (pipeline,      (models,     (strings, errors,
   (DuckDB, storage,    ports)          analysis)    config, logging)
    export)
```

Enforced rules, all in `tests/test_architecture.py` (AST-based; the inner layers
are checked **transitively**):

1. `shared` imports nothing from the project.
2. `domain` may import only `shared`; `application` only `domain` and `shared`.
3. `domain` and `application` may not reach duckdb, pandas, Qt, pyqtgraph,
   matplotlib, reportlab or pyarrow — directly or through any chain of imports.
4. `infrastructure` and `presentation` may import the three inner layers, never
   each other. The interface gets storage, ingestion and export through the
   gateways in `application.ports`.
5. `domain.analysis` may not import any `strings` module (it returns numbers;
   text is the caller's job).
6. Nothing in the package may import `scripts/expected_schema.py`.
7. Every module under `lmu_telemetry/` belongs to one of the five layers, apart
   from `composition.py`, which nothing inside the package may import.

`shared.strings` is reachable from every layer. That is allowed because it is
pure data; `test_strings_module_is_a_leaf` fails if it ever imports anything from
the project.

**The interface reaches the outside only through gateways.** `application/ports.py`
defines `CatalogGateway`, `SessionLoader`, `SessionImporter` and `Exporter`,
gathered in `Gateways`. `infrastructure/adapters.py` implements them by forwarding
to the storage, ingestion and export modules, and `composition.py` — the one
module allowed to import every layer — builds them. `main.py` (and the scripts and
tests) call `build_gateways()` and hand the result to `MainWindow`. The test
forbids anything inside the package from importing `composition`, and anything but
`composition` from importing `infrastructure.adapters`.

### Why `Session` lives in `infrastructure/ingest/session_loader.py`

`Session` holds an open DuckDB connection and aggregates a `TimeBase` and the
channel registry, all ingestion artifacts, so it belongs to infrastructure.
`domain/models.py` keeps only the pure value objects. The pipeline never imports
`Session`: it reads through the `SessionData` protocol in `application/ports.py`,
which `Session` satisfies structurally.

### The pipeline seam

`application/pipeline.py` is the only place that reads a session (through
`SessionData`) *and* calls `domain.analysis`. Presentation and export go through
it and never reach into the analysis for inputs.

Public surface:

| Function | Returns |
|---|---|
| `analyse_lap(session, lap, track_length_m)` | `LapAnalysis` — one lap on a 1 m grid, corners, accelerations |
| `analyse_session(session, …, corner_references)` | `SessionAnalysis` — all comparable laps + ideal lap + consistency + stints |
| `delta_between(reference, lap)` / `delta_against_ideal(ideal, lap)` | `delta.DeltaResult` |
| `corner_rows(analysis, benchmark, ideal)` | `list[CornerRow]` for the table and CSV |
| `friction_envelope`, `transition_quality` | g-g results |
| `track_paths`, `align_paths`, `compare_track_paths` | GPS and integrated paths |
| `pedal_states`, `loss_classes_on` | per-metre class arrays that colour the map |
| `name_corners` | attach user names to corners by distance |

---

## 5. Ingestion (`infrastructure/ingest/`)

### 5.1 The file format in one page

No telemetry table: **one table per channel**, in four column layouts
(`channel_registry.ChannelFormat`):

| | columns | meaning |
|---|---|---|
| A | `value` | continuous, single |
| B | `value1..value4` | continuous, per wheel (FL, FR, RL, RR) |
| C | `ts`, `value` | event, single (written on change only) |
| D | `ts`, `value1..value4` | event, per wheel |

Plus `channelsList` (name, frequency INTEGER, unit), `eventsList`, `metadata`
(key/value; includes `CarSetup` JSON and `DriverName`). Layout is always derived
from the file's own `DESCRIBE`, never from a hard-coded channel list. A table
matching no layout exactly is `UNKNOWN` and skipped with a warning.

**Continuous channels have no timestamps.** Time is implicit in the row index.
That single fact drives `time_base.py`.

### 5.2 `load_session` — order matters

```
open_session (read-only)  →  read_metadata  →  build_registry  →  build_time_base
                                                                      │
                          Session(info, time_base, registry, laps, …) ← split_laps
```

Failure types (`shared/errors.py`): `SessionFileError` (cannot open),
`SchemaError` (catalog table missing), `ChannelNotFoundError` (expected, used to
disable one feature), `TimeBaseError` (no usable clock), `SessionNameError`.
All derive from `TelemetryError`; the UI and importer catch that one type.

`Session` is a context manager holding the open connection. Its useful API:
`has(*names)`, `channel(name, convert=True)`, `channel_times(name)`,
`acceleration("lateral"|"longitudinal"|"vertical")`, `acceleration_times`,
`try_channel`, `laps`, `comparable_laps`, `best_lap`, `warnings`.

### 5.3 Time base (`time_base.py`)

- The declared `frequency` is an INTEGER column, so non-integer rates are
  truncated (7 Hz declared, 7.017 real). Sample times are therefore
  `t[i] = t0 + i·span/(n−1)`, i.e. the *empirical* rate, not the declared one.
- `GPS Time` (100 Hz real clock) validates the implicit time. Max drift above
  `ingest.time_base.max_drift_s` (0.05 s) → `GPS_CORRECTED`: sample times are read
  from the clock, and a Portuguese warning is attached (shown as the amber
  banner). No usable `GPS Time` → `UNVALIDATED` + warning.
- Event channels (C/D) use their own `ts`; applying the uniform grid to them was
  a real bug fixed in phase 6 (see README).
- `resample_to_grid` interpolates continuous channels and forward-fills discrete
  ones (`step_interpolate`; NaN before the first sample).
- Discreteness is decided from the column **type** (`DISCRETE_SQL_TYPES`), not the
  layout: `TC`/`OverheatingState` are BOOLEAN in layout A, `SurfaceTypes` is
  UTINYINT in layout B.

### 5.4 Laps (`lap_splitter.py`)

- `Lap` event = start/finish crossing with the new number. Lap *k* spans its event
  to the next. The recording tail after the last crossing becomes a final lap
  flagged `PARTIAL`.
- `Lap Time` (same instant, lap just ended) is matched to a boundary within 0.01 s
  and is *not* forward-filled. **Exactly 0.0 means invalidated** by the game.
- `Last Sector1/2` are cumulative: S1, S2−S1, LapTime−S2. Zero = unset → `None`.
- Flags (`LapFlag`): `VALID`, `PARTIAL` (no official time, or |measured − official|
  > `laps.max_time_mismatch_s` = 0.5 s), `INVALIDATED`, `OUT_LAP`, `IN_LAP`,
  `IN_PITS` (from the `In Pits` event), `OFF_TRACK` (informational only).
- `Lap.is_comparable` = `VALID` and none of PARTIAL/INVALIDATED/OUT/IN/IN_PITS.
  Everything downstream (analysis, ideal lap, consistency, best-lap view) is built
  from comparable laps only.
- A constant `In Pits` is normal in a race without a stop: not a warning, one stint.

### 5.5 Known file defects handled in `corrections.py`

`G Force Lat` actually carries longitudinal acceleration and `G Force Long`
carries lateral, **both negated**. Always read accelerations through
`Session.acceleration(...)`; the raw channels stay available by file name.
`tests/test_physical_validation.py` re-derives the evidence on every run (when a
real session is present), so a game update that fixes the labels fails the suite
instead of silently flipping every sign.

Other things the code relies on: `Ground Speed` is km/h while `GPS Speed` is m/s;
pedals and `Steering Pos` are percent (converted to 0–1 by `units.py` through the
`unit` column); wheel order FL, FR, RL, RR; surface codes in
`config [surfaces]`.

### 5.6 Units (`domain/units.py`)

Conversion is table-driven from the file's `unit` string (normalised through
`_ALIASES`). Canonical: m/s, m, s, deg, 0–1, g, °C, kPa, rpm. An **unknown unit
is passed through unchanged with a warning** — never guessed.

---

## 6. The per-lap pipeline (`pipeline.analyse_lap`)

```
lap window (t_start..t_end)
  → 100 Hz time grid                                   _lap_time_grid
  → 9 channels resampled onto it (linear / held)       _channels_on
       Ground Speed, Brake Pos, Throttle Pos, Steering Pos, Engine RPM,
       Lap Dist, GPS Latitude, GPS Longitude  |  Gear (held)
  → reference length: catalog track length, else max(Lap Dist) of this lap
  → distance.reconstruct: trapezoid ∫v dt, rescaled to close on the length
       (refused if scale outside [0.9, 1.1] → raw integral kept)
  → resample everything onto a 1 m distance grid       resample.resample
  → elapsed_time(distance) , lateral/longitudinal g    delta.elapsed_time, _accelerations_on
  → corners.detect_corners(speed, brake, throttle)
  → LapAnalysis
```

`LapAnalysis`: `lap`, `grid_m`, `channels` (name → array on the grid), `elapsed_s`,
`reconstruction`, `corners`, `lateral_g`, `longitudinal_g`; properties `speed_ms`,
`length_m`, `time_s`. Everything lap-to-lap happens on this distance grid and
nowhere else.

`analyse_session` runs `analyse_lap` for each comparable lap, picks the
best (`min time_s`), uses *its* corners as the reference set, then builds the ideal
lap, the whole-session consistency report and one report **per stint**
(`consistency.detect_stints` splits at pit laps).

---

## 7. Analysis modules (`domain/analysis/`)

All pure, all take arrays. Behaviour and reasoning are in `methodology.md`; this
is the index.

| Module | Core functions | Notes |
|---|---|---|
| `distance.py` | `cumulative_distance`, `reconstruct`, `lap_length_from_channel` | Returns both raw and corrected distance, so the correction can be audited |
| `resample.py` | `distance_grid`, `make_monotonic`, `resample` | Running-max repair for non-monotonic distance; `discrete=True` holds instead of interpolating |
| `delta.py` | `elapsed_time`, `delta_time`, `delta_against_reference_curve`, `smoothed_gain_rate`, `loss_classes`, `DeltaResult` | Delta is **slope**-coloured (Savitzky–Golay derivative, 25 m window); classes −2..+2 |
| `corners.py` | `detect_corners`, `smooth_speed`, `find_speed_minima`, `measure_corner`, `apply_names_by_distance`, `match_corners` | Corner = contiguous slow stretch (< 85 % of max speed), split at internal peaks, apex = centre of the flat minimum; windows split midway between apexes |
| `ideal_lap.py` | `segment_boundaries`, `build_ideal_lap`, `significant_discontinuities` | Segment cuts midway between apexes; stitched speed seams are reported, not smoothed; uses each winner's own elapsed profile |
| `consistency.py` | `select_laps`, `analyse`, `detect_stints`, `time_lost_from_segment_times` | Lap filter = min(median·1.05, median+2 s); loss = mean(t) − min(t) through the corner; drift test = Spearman ρ ≥ 0.7 |
| `friction.py` | `compute_envelope`, `transition_quality`, `envelope_for_window` | Convex hull via Qhull; fill fraction vs ellipse of the observed extremes |
| `trackmap.py` | `project_gps`, `reconstruct_from_lateral_g`, `align_paths`, `compare_paths`, `pedal_state` | Equirectangular GPS projection + ω = a_y/V cross-check |

Frozen, slotted dataclasses are the result type everywhere
(`DistanceReconstruction`, `DeltaResult`, `IdealLap`, `Segment`,
`ConsistencyReport`, `FrictionEnvelope`, `TrackPath`, …). `Corner` lives in
`domain/models.py` because both `analysis` and the UI need it.

Corner measurements (`Corner`): apex distance, minimum speed, entry speed and
braking point (start of the last sustained brake run before the apex), throttle resumption,
coasting time, trail-braking length, window start/end, optional name.

---

## 8. Storage (`infrastructure/storage/`)

Everything lives under `LMU_TELEMETRY_DATA_DIR` (default `~/.lmu-telemetry`):

```
~/.lmu-telemetry/
  catalog.duckdb                 historical catalog
  lmu-telemetry.log              DEBUG+ log written by main.py
  config.toml                    optional user overrides (section 11)
  cache/<session_id>/manifest.json
```

`session_id` = SHA-256 of the source file (content-addressed). A lap id is
`<session_id>:<lap_index>`. Both are natural keys, so re-importing is idempotent.
Game files are only ever opened read-only; nothing is written next to them.

### Catalog schema (`catalog.py`, `SCHEMA_VERSION = 1`)

| Table | Key | Notes |
|---|---|---|
| `schema_info` | — | single row, version; `initialise` applies `catalog.MIGRATIONS` in order (none yet) |
| `tracks` | `track_id` (slug of the name) | `length_m` measured from `Lap Dist`; kept on conflict when the new value is NULL |
| `sessions` | `session_id` | identity, car, class, type, `started_at` (naive UTC), `n_laps` |
| `laps` | `lap_id` | all laps incl. flags (comma-joined), `is_comparable`, sector times |
| `corners` | `(track_id, corner_index)` | the user's corner names + `reference_distance_m` anchor |
| `best_laps` | *view* | `QUALIFY row_number() … PARTITION BY track_id, car_name`; a view, not a table, so it cannot go stale |

Import replaces a session's lap set wholesale (delete + insert). Timestamps are
stored as naive UTC to avoid the `pytz` dependency that `TIMESTAMPTZ` would force.

### Cache (`cache.py`)

Only a **manifest** is cached: identity, time base, channel registry, lap table
(a few KB per session; ~1.2 MB for 64 sessions). Raw channel data is *not*
cached: measured, a parquet copy saves ~1 ms per read and costs ~2× the disk.
`CACHE_FORMAT_VERSION` mismatch or a damaged file → silently ignored and rebuilt.
A corrected time base's `reference_times` is deliberately not stored.

### Importer (`importer.py`)

`import_session_file` hashes → reads the manifest (unless `force`) → on a hit just
re-records into the catalog; on a miss loads the session, computes the track
length (median over comparable laps of `Lap Dist` extrapolated to the crossing
time), writes the manifest and the catalog rows. A cache hit still re-reads the
source if the catalog has no length for that track. `import_folder` opens the catalog once and keeps
going past a bad file, returning `(results, failures)`.

---

## 9. UI (`presentation/`)

### Window composition (`MainWindow`)

The traces are the window's centre; everything else is a `QDockWidget`, so each
panel can be hidden, moved, tabbed with another or floated.

```
┌ menu bar ──────────────────────────────────────────────────────────────────────┐
├ toolbar: import · refresh │ comparison · pin │ axis │ export PNG · PDF ─────────┤
├────────────────┬─────────────────────────────────────┬─────────────────────────┤
│ dock_sessions  │ warning banner (amber)              │ dock_map   (TrackMap)   │
│ SessionBrowser │ ChartStack (centre widget)          ├─────────────────────────┤
│ track▸car▸     ├─────────────────────────────────────┤ dock_gg    (g-g)        │
│ session▸lap    │ dock_corners: CornerTable |         │                         │
│                │               ConsistencyPanel      │                         │
├────────────────┴─────────────────────────────────────┴─────────────────────────┤
│ status bar                                                                     │
└────────────────────────────────────────────────────────────────────────────────┘
```

The side docks run the full height (`setCorner`), so the corner tables sit under
the traces they are read against. The arrangement is saved to `QSettings` when the
window closes and restored on the next run; `Painéis ▸ Restaurar layout padrão`
(`MainWindow.reset_layout`) puts everything back. A saved state is applied only if
it was written under the current `LAYOUT_STATE_VERSION` and `restoreState`
accepts it; otherwise the default is used. Bump the version when a dock is added,
removed or renamed — the dock object names (`dock_sessions`, `dock_corners`,
`dock_map`, `dock_gg`) are what saved layouts are keyed on.

The toolbar reuses the menu's `QAction` objects, so checked and enabled state is
shared. It shows each action's `iconText` — a short wording — while the menu keeps
the full text and the tooltip carries it too.

The window takes its collaborators as arguments: `MainWindow(gateways, settings=None)`.
`settings` is injectable so tests never touch the user's real settings.

### State objects (`session_state.py`; `ImportWorker` in `import_worker.py`)

- **`SessionPool`** — LRU of at most **2** open `Session`s (enough for a
  comparison against a pinned lap from another file). Evicting closes the DuckDB
  connection.
- **`OpenSession`** — one session + a per-lap `LapAnalysis` cache + a lazily built
  `SessionAnalysis` + the track's `corner_references` from the catalog.
- **`CurrentView`** — what is on screen right now (selection, primary, benchmark,
  delta, ideal, corner rows, consistency). **Exports read from this**, never
  recompute, so a file always matches what the user was looking at.
- **`ImportWorker`** — imports files on a `QThread` with its own catalog
  connection; emits `progress` and `finished`. Everything else in the window still
  runs on the interface thread.
- **`ComparisonMode`** — `NONE`, `SESSION_BEST` (default), `PINNED`, `IDEAL`.

### Interaction flow

`SessionBrowser.lap_selected(LapSelection)` → `MainWindow.show_lap` → open session
→ `analysis_for(lap)` → `session_analysis()` (ideal lap) → choose benchmark →
`pipeline.delta_*` → fill chart, markers, corner table, consistency, map,
g-g → warnings → status line with timing.

**One cursor for the whole window:** `chart.cursor_moved`, `track_map.distance_picked`,
`corner_table.corner_selected` and `consistency.corner_selected` all feed
`_on_cursor_moved(distance_m)`, which moves the cursor in every panel.

Corner rename: `CornerTable.corner_renamed(index, distance, name)` →
`MainWindow.rename_corner` → `CatalogGateway.set_corner_name` → every open session
re-applies names and drops its `SessionAnalysis` → `show_lap` again.

### Rules baked into the UI

- Two laps are only ever compared on the **distance axis**; the time axis action
  is disabled while a comparison is drawn.
- A reference from a **different track** is refused with a banner; a different
  **car** is allowed with a warning.
- The ideal lap chart shows **speed only** — it has no pedal/steering trace
  because nobody drove it.
- Dimmed (not hidden) laps in the browser: partial/invalidated/pit laps.

### Other UI facts

- `chart_panel.ROW_SPECS` is the single description of the stacked rows (speed,
  pedals, steering, gear, RPM, delta); `DEFAULT_ROWS` = speed, pedals, delta.
  Scales (m/s→km/h, fraction→%) are applied at this edge only.
- `chart_panel`, `track_map` and `gg_panel` take numpy arrays and labels, not
  sessions, so they are testable with tiny arrays.
- `theme.apply` must run **before** any widget is built (pyqtgraph reads its
  globals at construction). Fixed left-axis width keeps stacked rows aligned.
- **All user-visible text is in `shared/strings.py`** (~620 lines). The one-way
  rule: strings is a leaf. Adding UI text means adding a constant there.
- `formatting.py`: `format_lap_time`, `format_gap`, `format_value`.

---

## 10. Export (`infrastructure/export/`)

No Qt imports (matplotlib is forced to Agg), so it runs in CI or over SSH.

| Module | Output |
|---|---|
| `charts.py` | `export_lap_charts` (speed/pedals/delta PNG), `export_track_map`, `export_friction`; light palette at print resolution |
| `tables.py` | `write_lap` (one row/metre), `write_corners`, `write_consistency`; two CSV dialects: `STANDARD` (`,` and `.`) and `EXCEL_PT_BR` (`;` and `,`) |
| `report.py` | `write_report(path, ReportContext)` → A4 PDF with the caveats printed in the document |
| `anonymise.py` | copy-then-edit scrubber + `verify()`; replaces `DriverName`, `SteamID`, then sweeps every VARCHAR column for residue |

The exports **redraw** with matplotlib instead of screenshotting pyqtgraph, so the
unit conversions must stay shared to keep exported numbers equal to on-screen ones.
`ReportContext` holds the analysis objects as `object` (to avoid importing
`pipeline` types into `export`); it is assembled by `MainWindow._report_context`
or by `scripts/export_session.py`.

---

## 11. Configuration, logging, conventions

### `config/defaults.toml`

The rule is "every numeric threshold lives here". Sections: `ingest`,
`ingest.time_base`, `laps`, `analysis.{distance,resample,corners,delta,
ideal_lap,consistency,friction,trackmap}`, `surfaces`. Access:
`load_config().get("analysis.corners.brake_threshold")` — a missing key raises
`KeyError` rather than returning `None`.

**User overrides.** `~/.lmu-telemetry/config.toml` (or the file named by
`LMU_TELEMETRY_CONFIG`) is merged over the defaults and holds only what changed:

```toml
[analysis.consistency]
drift_correlation_threshold = 0.8
```

A key that does not exist in the defaults is a `ConfigError` (shown at startup),
not a silent no-op. Edits are picked up without restarting. `load_config(path)`
with an explicit path ignores the user file.

**Adding a key to `[analysis.corners]`** also needs a field of the same name on
`CornerDetectionSettings` (`from_config` says which key is missing if not; a test
checks the shipped file).

### Logging

`shared.logging_config.setup_logging` configures the root logger once: console at INFO,
and — from `main.py` only — `lmu-telemetry.log` at DEBUG. It also reconfigures
stdout/stderr to UTF-8 (the Windows console cannot print `ã`/`ç` otherwise).
The project uses `logging`, not `print`, apart from script output.

### Code conventions observed

- `from __future__ import annotations` everywhere; frozen `slots=True` dataclasses
  for results; type hints on public functions.
- Comments explain *why*, usually with the measured evidence that forced the
  decision. Keep doing this — it is the project's main asset.
- Degrade, don't crash: a missing channel disables one feature
  (`ChannelNotFoundError`, `try_*` helpers, warnings list).
- User-facing messages: Portuguese, in `strings.py`. Logs and docs: English.
- A formula never silently guesses: unknown units pass through, scale factors are
  bounded, partial laps are flagged rather than dropped.

---

## 12. Issues found, and what became of them

An audit at commit `0608ded` listed the items below. Everything marked **fixed**
was changed and is covered by a test that fails on the old code; what is left
open is under "Still open".

### Fixed — behaviour

**B1 — Renaming a corner could overwrite another corner's name.** `corners` is
keyed `(track_id, corner_index)` but names are anchored by *distance*, and
`set_corner_name` upserted on the index, so renaming from a lap whose detector
numbered the corners differently took over another corner's row and anchor. Now,
given a distance, it updates the row anchored nearest within
`analysis.corners.name_match_tolerance_m` (`catalog.name_match_tolerance_m()`),
whatever its index; otherwise it inserts, using the requested index if free and
the next unused one if not. Without a distance it keeps the old by-index
behaviour. `OpenSession.rename_corner` applies the same nearest-within-tolerance
rule in memory instead of requiring an exact float match. Schema unchanged. A
rename moves the anchor to the newly given apex, so repeated renames could drift
it, in steps within the tolerance.

**B2 — The braking point was the first brake run in the window.** The window
reaches back midway to the previous corner, so a sustained tap on the straight
became the braking point. `measure_corner` now uses the start of the **last**
sustained run before the apex (`_sustained_run_start(..., last=True)`; the old
`reverse` option also returned a point *inside* the run rather than its start).
Unchanged for a single braking zone. Limits: two-stage braking (brake, release,
brake) reports the second stage; a corner taken on a lift, with only a tap far
earlier, still reports that tap. A guard such as "speed must fall over the run"
would be the next refinement.

**B3 — `AnonymisationReport.is_clean` was always `True`.** `anonymise_session`
now re-opens the file it wrote, runs `verify`, and stores the result in
`findings`; `is_clean` is `not findings`. `make_demo_dataset.py` uses it.

**B4 — Track length lost when the catalog was rebuilt under a surviving cache.**
A cache hit now re-reads the source when the catalog has no length for the track
(and the session has a comparable lap).

**B5 — The reference track length was short by up to a sample of travel.**
`importer._lap_length_at_crossing` extrapolates `Lap Dist` from its last two
samples to the exact crossing time (the lap's `t_end`). On the demo session the
raw last samples spread over 5.5 m between laps, the extrapolated values over
0.8 m. Falls back to the last sample when the gap is not a plausible fraction of
a sample. Existing catalogs keep their old (slightly short) length until a
session at that track is re-imported with `--force`.

### Fixed — performance and responsiveness

**P1 (partly) — Importing no longer freezes the window.** `MainWindow._import`
runs `ImportWorker` on a `QThread` with its own catalog connection, shows
progress in the status bar, refuses a second import while one runs, reports an
unexpected crash as a failure instead of losing it, and `closeEvent` cancels and
waits for it. See "Still open" for what stays synchronous.

**P2 — Laps analysed twice, channels re-read per lap.** `Session.series` /
`acceleration_series` cache each channel (converted, with its times) so a
session's channels are read once, not once per lap
(`test_analysing_a_session_reads_each_channel_once`). `analyse_session` takes
`precomputed=` and `OpenSession.session_analysis` passes its per-lap cache, so a
lap shown on screen is not analysed again. Cached arrays are shared: do not
modify them in place.

**P3 — Renaming a corner re-analysed the whole session.** Still rebuilds the
ideal lap and the consistency report (they snapshot labels), but the laps
themselves are now kept (P2), so it is the stitching and the statistics only.

### Fixed — documentation and code drift

- **D1** The cache is a JSON manifest, not parquet. Docstrings and the README
  corrected, the empty `cache/<id>/laps/` directory and `LAP_FRAMES_DIRNAME`
  removed, `pyarrow` dropped from `requirements.txt` (the suite passes without it).
- **D2** `channel_registry.WHEEL_ORDER` no longer points at a test that does not
  exist, and says the order was verified.
- **D3** README and methodology say `core` depends on nothing but `ui/strings.py`.
- **D4** `corners.apply_names` (by index, the pattern B1 was about) removed.
  The other unused functions were kept on purpose; see "Still open".

### Fixed — configuration

- **D5** Thresholds moved to `config/defaults.toml`:
  `laps.boundary_match_tolerance_s`, `analysis.corners.apex_plateau_fraction`,
  `analysis.corners.name_match_tolerance_m` (also used by the catalog, the
  consistency matching and the UI), `analysis.consistency.drift_correlation_threshold`,
  `analysis.friction.transition_min_magnitude_g` / `transition_blend_ratio`,
  `analysis.ideal_lap.seam_threshold_ms`, and a new `[ui.consistency]` section for
  the table's warning limits. `analysis` still never loads config itself: values
  arrive as parameters (`CornerDetectionSettings` fields, function arguments,
  `CornerConsistency.drift_threshold`).
- **D6** A user file is merged over the defaults: `config.toml` in the data
  directory, or the file named by `LMU_TELEMETRY_CONFIG`. It holds only what is
  changed. An unknown key, a section/value mix-up or invalid TOML raises
  `ConfigError`, which `main.py` shows in a dialog at startup. Edits take effect
  without restarting.
- **D7** `CornerDetectionSettings.from_config` names unknown keys instead of
  raising a bare `TypeError`; `loss_classes` is called with explicit keys. A test
  checks that every shipped `[analysis.corners]` key is a field.

### Fixed — smaller things

`CurrentView` and `ReportContext` carry real types (the latter through
`TYPE_CHECKING` imports, so `export` does not load `pipeline` at runtime);
`LapSelection.session_type_code` replaces re-parsing the file name;
`lap_splitter` imports `channel_registry` at module level; the catalog has
migration scaffolding (`catalog.MIGRATIONS`, applied in order by `initialise`; a
missing step leaves the catalog untouched with a warning; a newer catalog is left
alone); CI also runs on `windows-latest`.

### Still open

- **Session analysis is still synchronous on first lap view.** Only import moved
  to a worker. `show_lap` analyses every comparable lap of the session before
  drawing the first time (P2 made that cheaper, not asynchronous). A DuckDB
  connection must not be shared across threads, so doing it right means giving
  the worker its own `Session`, or analysing from a snapshot of the arrays.
- **Unused but tested utilities, kept deliberately:**
  `consistency.estimate_time_lost_from_speed` (fallback branch only),
  `resample.align_to_common_grid` / `resample_channels`,
  `friction.envelope_for_window` / `combined_magnitude`,
  `distance.speed_from_distance`, `time_base.common_grid`,
  `channel_registry.channels_by_format`, `catalog.forget_session` / `corner_names`,
  `importer.load_cached`, `corrections.reference_*_g`. Delete any when sure it
  will not be wired; there is no UI for forgetting a session yet.
- **A few constants remain in code:** `corrections.reference_lateral_g`'s track
  width (1.6 m, a parameter used only by tests). Everything else numeric is in the
  configuration.
- **No linter or type checker** (`ruff`, `mypy`) is configured; the typing added
  above is not checked by anything.
- **The B2 guard** and the corner-name anchor drift under B1 (above).
- `conftest.DEFAULT_TELEMETRY_DIRS` lists two Steam paths on this machine's
  layout; `LMU_TELEMETRY_DIR` already overrides them.
- A new Windows CI job has not run yet: the first push will show whether anything
  behaves differently there.

---

## 13. Test results

Baseline, 2026-11-06, a throwaway venv (Python 3.14.5, the pinned
`requirements.txt`, `QT_QPA_PLATFORM=offscreen`), no game installed:

```
501 passed in 47.7 s      before any change
```

Repeated after uninstalling `pyarrow`: 501 passed (the evidence for D1).

After the fixes above: **532 passed**. The tests for B1, B2 and P2 were run
against the old code and fail there. `pytest.ini` promotes warnings to errors, so a green run also means no new
warning from PySide6 6.11 / numpy 2.5 / pandas 3.0 / DuckDB 1.5 on 3.14.

## 14. Recipes for common adjustments

**Add a channel row to the chart.** Add the channel name to `pipeline.CONTINUOUS_CHANNELS`
(or `DISCRETE_CHANNELS`) so it is resampled onto the distance grid, add a
`RowSpec` to `chart_panel.ROW_SPECS` with its `Series` (scale/decimals), add the
label constants to `strings.py`. The View ▸ Channels menu is generated from
`ROW_SPECS`. Add the column to `tables.CHANNEL_COLUMNS` if it should reach the CSV.

**Add or change a threshold.** Add the key to `config/defaults.toml` with a comment
that says *why that value*. If it is in `[analysis.corners]` or `[analysis.delta]`,
add the matching field in the same commit. Read it in `application/pipeline.py` and pass it
down — `analysis` never loads config itself.

**Add a per-corner metric.** Add a field to `Corner` (`domain/models.py`), measure it
in `corners.measure_corner`, expose it in `CornerRow`/the table
(`presentation/corner_table.COLUMNS` + `strings.CORNERS_COLUMN_*`) and in
`tables.write_corners`. Test on the synthetic circuit first.

**Add a UI string.** Constant in `shared/strings.py` (Portuguese). Never inline text in
widgets or in `analysis`/`ingest` (except log messages).

**Change the catalog schema.** Bump `SCHEMA_VERSION`, add the step to
`catalog.MIGRATIONS[<old version>]`, and add a test that opens a file written by
the old version.

**Change what the cache stores.** Bump `CACHE_FORMAT_VERSION`; old manifests are
then ignored and rebuilt automatically.

**Support a new game build.** Run `scripts/inspect_schema.py` on a new file; it
reports divergences from `expected_schema.py`. The registry adapts to new/changed
channels on its own. Re-run `test_physical_validation.py` against a real session —
if the G-force labelling was fixed, it fails on purpose, and `corrections.py` must
change.

**Add a comparison mode.** Extend `ComparisonMode`, handle it in
`MainWindow._benchmark_selection`/`_show_lap`, add the menu action in
`_build_comparison_actions` and strings; delta arrays come from `pipeline`.
