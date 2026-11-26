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

### Packaging (`LMU Telemetry.exe`)

`scripts/build_exe.ps1` installs `requirements-build.txt` (PyInstaller, pinned),
runs `packaging/lmu_telemetry.spec` and smoke-tests the output; `-Shortcut` adds
a desktop shortcut. Output: `dist/LMU Telemetry/` - a one-folder, windowed build
(~310 MB), the .exe beside `_internal/`. `build/` and `dist/` are git-ignored.

- **Bundled data:** `config/defaults.toml` → `_internal/config/` (where
  `config.DEFAULT_CONFIG_PATH`, two levels above the package, resolves inside the
  .exe) and `assets/app.ico` → `_internal/assets/` (found through
  `main.RESOURCE_ROOT` = `sys._MEIPASS` when frozen). User data stays in
  `%USERPROFILE%\.lmu-telemetry`, outside the build.
- **Excluded:** tkinter, PyQt5/6, PySide2, IPython, pytest, pyqtgraph.opengl and
  unused Qt modules (WebEngine, 3D, Multimedia, Quick/QML, Pdf).
- **`main.py --smoke-test [png]`** builds the window, lets it open the default lap,
  optionally saves a screenshot, logs "Smoke test passed" and exits 0. The build
  script runs it on the .exe against the demo session imported into a throwaway
  `LMU_TELEMETRY_DATA_DIR` and fails unless the log shows the lap loaded;
  `tests/test_packaging.py` runs it on the source, and checks every file the spec
  bundles exists where the code looks for it.
- **Icon:** `scripts/make_icon.py` draws `assets/app.ico` (seven sizes, each drawn
  at its size) from the theme's surface and accent.
- PyInstaller warns `Hidden import "scipy.special._cdflib" not found`: a hook
  for a module newer SciPy no longer has; harmless.

---

## 3. Repository map

```
main.py                     entry point: logging → QApplication → theme → MainWindow (also of the .exe)
config/defaults.toml        every numeric threshold of ingest/analysis
assets/app.ico              application icon (scripts/make_icon.py)
packaging/                  lmu_telemetry.spec - the PyInstaller build (scripts/build_exe.ps1)
lmu_telemetry/
  shared/                   cross-cutting kernel; imports nothing from the project
    strings.py                every user-visible string (pure data)
    errors.py                 TelemetryError hierarchy
    config.py                 Config (dotted-path access), load_config (lru_cache'd)
    logging_config.py         setup_logging, get_logger
    formatting.py             every number on screen: lap/sector time, seconds, gap,
                              speed (m/s in, km/h out), distance, channel value
  domain/                   numpy/scipy/stdlib only
    models.py                 SessionInfo, Lap, LapFlag, Corner, Stint, filename parser, SHA-256
    units.py                  unit conversion driven by the file's own `unit` column
    records.py                SessionRow, LapRow, CornerReference (catalog rows)
    official_tracks.py        official turn numbers/names per LMU circuit (LMU wiki), `find_track`
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
    main_window (composition only), lap_view, window_actions, exporting,
    session_state, import_worker, status_line, notice_banner, session_browser,
    plotting, chart_widgets, chart_panel, track_map, gg_panel, corner_table,
    grouped_header, consistency_panel, chip_group, theme,
    session_header, lap_list, corner_detail
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
  → corners: official turns (corners_at_anchors) when the circuit is known and
    calibrated, else corners.detect_corners(speed, brake, throttle)
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

Official turns (`official_tracks.py`, `corners.corners_at_anchors`): the speed-based
detector cannot see a turn taken flat out (Fuji has 16 turns, the detector finds 7).
For a circuit in `official_tracks.TRACKS` whose listed turns all have an `anchor_m`
(distance of the apex from the line) and whose length matches the lap
(`OfficialTrack.fits_lap`, 5 %), `pipeline._detect_corners` measures one corner per turn
and labels it `T<n> <name>`. Numbers and names come from the LMU wiki Track Guides;
where the wiki is silent the field is `None`, never a guess. The wiki gives no
distances, so anchors were read off a recorded lap's GPS heading and cross-checked on
other sessions: every speed minimum the old detector finds lies within ~45 m of an
anchor. Calibrated: Fuji, Monza, Spa, Le Mans, COTA, Interlagos, Portimão, Bahrain
(5.4 km layout only), Imola. Not calibrated, so they keep the speed-based `C<n>`
corners: Silverstone (no session with a complete lap), Sebring, Paul Ricard, Qatar.
Confidence is lowest for turns taken flat out in a continuous arc (Imola 1/8/10/13/16/19,
Interlagos 9/10 and 13-15, the COTA esses). A user's own corner name (catalog, by
distance) still overrides the official label.

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

**Sessions whose file was deleted leave the catalog.**
`catalog.forget_missing_sessions` (through `CatalogGateway.forget_missing_sessions`,
which also clears their cache) drops every session whose source file is gone
*while its folder still exists*; a missing folder is taken for a drive not
mounted, and those sessions are kept. Corner names are per track and survive.
The window runs it on every catalog reload (status: *"n sessão(ões) removida(s)
da lista"*) and when opening a session fails with `SessionFileMissingError` (a
`SessionFileError` subclass raised by `duckdb_reader.open_session`), in which case
the session leaves the list with a warning instead of an error, and a pinned
reference from it is released.

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

A summary strip across the top, the traces in the centre, and everything else a
`QDockWidget`, so each panel can be hidden, moved, tabbed with another or floated.

```
┌ menu bar ──────────────────────────────────────────────────────────────────────┐
├ toolbar: import · refresh │ comparison · pin │ axis │ export PNG · PDF ─────────┤
├ toolbar_header (SessionHeader): track · car │ lap · reference · Δ │ S1 S2 S3 │  ┤
│                                  best of session · ideal lap                   │
├────────────────┬─────────────────────────────────────┬─────────────────────────┤
│ dock_sessions  │ NoticeBanner (amber / red)          │ dock_map   (TrackMap,   │
│ SessionBrowser │ ChartStack (centre widget)          │   corners T1..Tn)       │
├────────────────┤                                     ├─────────────────────────┤
│ dock_laps      │                                     │ dock_gg    (g-g)        │
│ LapList        │                                     │                         │
├────────────────┴──────────────┬──────────────────┬───┴─────────────────────────┤
│ dock_corners (CornerTable)    │ dock_detail      │ dock_consistency            │
│                               │ (CornerDetail)   │ (ConsistencyPanel)          │
├───────────────────────────────┴──────────────────┴─────────────────────────────┤
│ status bar                                                                     │
└────────────────────────────────────────────────────────────────────────────────┘
```

- **`SessionHeader`** (`session_header.py`) — a non-movable toolbar on its own row
  (`addToolBarBreak`), so it spans the window above the side columns. Fed a
  `SessionSummary` the window assembles in `_session_summary`. Session-best sectors
  are drawn in the `BEST` tone; the delta is green/red *and* signed. Its figures sit
  in a horizontal `QScrollArea`, so the header never sets the window's minimum width.
- **`LapList`** (`lap_list.py`) — every lap of the open session in driving order:
  time, S1–S3, gap to the best, status. Best lap and best sectors are computed among
  **comparable** laps only (`best_lap`, `best_sectors`); non-comparable laps are
  listed but dimmed; the reference lap is tagged `ref`. Picking a row calls
  `SessionBrowser.select_lap`, so a lap is always opened through the browser and
  the two never disagree.
- **`SessionBrowser`** (`session_browser.py`) — *which session*; the lap list
  answers *which lap of it*. Search (every word, any order, case- and
  accent-insensitive, over track, car, class, type, date, weather) and three
  filter combos (track; car, narrowed to the chosen track; session type) over a
  list grouped by **track · car** — the unit laps are comparable in — groups and
  sessions newest first. A session row: date · type, best comparable lap in the
  `BEST` tone, lap count; dimmed when no lap is comparable; tagged `ref` when it
  holds the pinned reference (`mark_reference`). Choosing a session opens its best
  comparable lap (or its first lap when none is comparable); coming back to the
  open session keeps the lap on screen. Empty catalog → *Importar sessão…* /
  *Importar pasta…* buttons (`import_requested`, `import_folder_requested`); no
  match → *Limpar filtros*. Keyboard: Ctrl+F (`commands.find_session`, reopens the
  dock) → search; Down/Enter → list (opening the first match); Esc clears; arrows
  skip group headings (`_SessionList.moveCursor`). Matching is the pure
  `session_matches(SessionRow, BrowserFilter)`.
- **`CornerTable`** (`corner_table.py`) — one row per corner, **always in lap
  order** (`setSortingEnabled(False)` on purpose; a ranking would destroy the
  reading). Three column groups, each under a band in the header
  (`GroupedHeader`, below): *Nesta volta* (apex, min/entry speed, braking, trail,
  coasting), *Contra a referência* (`COMPARISON_COLUMNS`: ΔV mín, Δt) and *Contra
  a volta ideal* (`IDEAL_COLUMNS`: best lap, gain); the last two are hidden as a
  block when there is nothing to compare. The name column is editable and has no
  group; a rename emits `corner_renamed(index, apex_m, name)`. **The costliest
  corner** - `pipeline.costliest_corner(rows)`, below - is marked without moving:
  a `WARNING` bar at the row's left edge (`theme.standout_brush`,
  `STANDOUT_BAR_WIDTH`), every cell in `theme.emphasised` weight, and "▸" before
  the name. Bar and mark are drawn by `_MarkDelegate` (`initStyleOption`,
  `paint`, `sizeHint`), never written into the text, so the editor and the
  catalog never see them. The deciding figure keeps its meaning: "A ganhar" in
  `WARNING`, or Δt in `LOSS`. No tint behind the row: `LOSS` text is 4.6:1 on a
  panel and fell to 3.7:1 on a 12% warm tint. Coasting ≥ `COASTING_WARNING_S`
  (0.25 s) is `WARNING` (`coasting_tone`, shared with the card). The ideal-lap
  summary line above the table wraps, so it never sets the dock's width.
- **`GroupedHeader`** (`grouped_header.py`) — Qt has no grouped header. One
  `QHeaderView` a band taller (`band_height`, 16 px at the caption size): each
  section paints its label in the lower part (`paintSection` with a shifted
  rect), and `paintEvent` paints the group labels (`ColumnGroup(label,
  columns)`) over the top, **computed from the sections' geometry on every
  paint** (`group_span`), so scrolling, resizing and hidden columns need no
  syncing; a fully hidden group draws nothing. Labels are centred and elided to
  their columns, never widening them; the band's tooltip and each column's
  tooltip name the group. Font and colours from `theme.header_band()`.
- **Costliest corner** — `pipeline.costliest_corner(rows) → CostliestCorner |
  None` (`position`, `seconds`, `basis: CostBasis`). With any `gain_s` present
  (an ideal lap), the largest positive gain; else with any `delta_s` (a
  comparison), the largest positive delta; else none. The ideal lap decides as
  soon as it exists - no fallback to the comparison when nothing is left to gain;
  non-finite values skipped; ties to the first corner. Pure, no Qt; the table and
  the card both call it on the same rows, so they cannot disagree.
- **`CornerDetail`** (`corner_detail.py`) — the corner under the cursor, figures
  labelled in words: this lap, against the reference, against the ideal lap (the
  section titles are the table's group labels). Picks the corner by nearest
  apex, the same rule as `CornerTable.select_corner_at`. On the costliest corner
  it shows `costliest_flag` ("▸ A curva que mais custa · 0.262 s a ganhar contra
  a volta ideal", `WARNING`, emphasised; `shows_costliest`), and the gain is
  `WARNING` there only. A missing figure is "--", never "-- km/h". Scrolls
  rather than imposing its height on the bottom row.
- **`ConsistencyPanel`** (`consistency_panel.py`) — per stint: the ranking (worst
  first, from the analysis; not re-sortable; name column sized to content, spare
  width to the last), and the selected corner lap by lap with mean and ±1σ band.
  Warning cut-offs from `ui.consistency.*`. One row of controls: **stint chips**
  on the left, shown only with more than one stint (`stint_changed(index)`), and
  **measure chips** on the right (`METRICS`: chip text with unit, e.g. "V mín
  (km/h)"; full name with unit for the axis, tooltip and accessible name; the
  plot title carries the unit). The measure survives a change of stint and of
  lap. The summary has a line of its own and wraps. A stint too short to measure
  shows the placeholder but keeps the stint chips (`show_report` →
  `_clear_report`); `clear()` hides them too.
- **`ChipGroup`** (`chip_group.py`) — exclusive chips (`QToolButton`,
  `role="chip"`, in an exclusive `QButtonGroup`): `set_options(labels,
  descriptions, current)`, `current_index`, `set_current_index` (silent),
  `chosen(index)` for the user's picks only. Keyboard as radio buttons (Qt's
  own for exclusive groups): Tab stops on the chosen chip, arrows move the
  choice. Laid out by `FlowLayout`, which wraps instead of widening: its minimum
  width is the widest chip, its height follows its width.
- **Corner numbers** — the map (`TrackMap.set_corner_labels`) and the traces show
  the short form of a corner's label (`_short_label`: "T6 Hairpin" → "T6"; a user's
  own name or a detector "C4" stays whole).

The bottom row runs the full width (`setCorner` gives both bottom corners to the
bottom area) because the corner table has eleven columns. Default sizes are
fractions of the window (`_arrange_docks`), and the initial size is capped to the
screen (`_initial_size`). The arrangement is saved to `QSettings` when the window
closes and restored on the next run; `Painéis ▸ Restaurar layout padrão`
(`MainWindow.reset_layout`) puts everything back, header included. A saved state is
applied only if it was written under the current `LAYOUT_STATE_VERSION` (now **2**)
and `restoreState` accepts it; otherwise the default is used. Bump the version when
a dock is added, removed or renamed — the object names (`dock_sessions`,
`dock_laps`, `dock_corners`, `dock_detail`, `dock_consistency`, `dock_map`,
`dock_gg`, `toolbar_main`, `toolbar_header`) are what saved layouts are keyed on.

The toolbar reuses the menu's `QAction` objects, so checked and enabled state is
shared. It shows each action's `iconText` — a short wording — while the menu keeps
the full text and the tooltip carries it too.

The window takes its collaborators as arguments: `MainWindow(gateways, settings=None)`.
`settings` is injectable so tests never touch the user's real settings.

**`main_window.py` only builds and connects** (docks, layout persistence, and
`_connect`, where every signal is wired). It does not import `pipeline` — a test
holds that. The work it used to do lives beside it:

| Module | Role |
| --- | --- |
| `lap_view.py` | `compose(sessions, selection, mode, pinned) → LapView`: the benchmark choice and its refusals, delta, ideal lap, corner rows, stint, map and g-g figures, header summary and status line, all as plain values. No widgets; testable without a window. `LapView.figures` is `None` when the lap cannot be analysed. |
| `window_actions.py` | `WindowActions` (`window.commands`): every `QAction`, the menus, the main toolbar. Parameterised choices are typed signals (`comparison_chosen`, `axis_chosen`, `channel_toggled`, `map_colour_chosen`); `offer_*` / `allow_time_axis` keep the actions honest. |
| `exporting.py` | `LapExporter` (`window.exporter`): the four exports sharing one dialog/suffix/dialect/error path, reporting through its `status` signal; `suggested_name`, `report_context(CurrentView)`. |
| `import_worker.py` | `ImportWorker` (the work) and `ImportRunner` (`window.importer`: one run at a time on a `QThread`, `busy_changed`, `stop()` on close). |
| `status_line.py` | `StatusLine` (below). |
| `notice_banner.py` | `NoticeBanner` (below). |

**Status line.** A *resting line* describes the lap on screen (`rest`); a
*notice* — exported, pinned, layout restored — interrupts it for 6 s (`notify`)
and the resting line comes back, so the bar never keeps describing something that
is gone. Progress that will end with its own message is `notify(..., sticky=True)`.
The analysis time sits apart as a permanent, muted label on the right
(`set_timing`), not in the lap's line.

**Notice banner.** One note per line (bulleted when there are several), two
severities — `WARNING` (amber: drawn, with a caveat) and `ERROR` (red: nothing to
trust, e.g. the session file cannot be opened) — styled by the theme through the
frame's `severity` property, and a dismiss button that hides it until the next lap
brings notes of its own.

### State objects (`session_state.py`; `ImportWorker`/`ImportRunner` in `import_worker.py`)

- **`SessionPool`** — LRU of at most **2** open `Session`s (enough for a
  comparison against a pinned lap from another file). Evicting closes the DuckDB
  connection.
- **`OpenSession`** — one session + a per-lap `LapAnalysis` cache + a lazily built
  `SessionAnalysis` + the track's `corner_references` from the catalog.
- **`CurrentView`** — what is on screen right now (selection, primary, benchmark,
  delta, ideal, corner rows, consistency). **Exports read from this**, never
  recompute, so a file always matches what the user was looking at.
- **`ImportWorker`** — imports files on a `QThread` with its own catalog
  connection; emits `progress` and `finished`. **`ImportRunner`** owns the thread:
  refuses a second run, emits `busy_changed`, and `stop()` lets the current file
  finish. Everything else in the window still runs on the interface thread.
- **`ComparisonMode`** — `NONE`, `SESSION_BEST` (default), `PINNED`, `IDEAL`.

### Interaction flow

`SessionBrowser.lap_selected(LapSelection)` → `MainWindow.show_lap` →
`lap_view.compose` (open session → `analysis_for(lap)` → `session_analysis()` →
choose benchmark → `pipeline.delta_*` → figures) → `MainWindow._show` hands each
panel its part → notices → resting status line; timing on the right.

**One cursor for the whole window:** `chart.cursor_moved`, `track_map.distance_picked`,
`corner_table.corner_selected` and `consistency.corner_selected` all feed
`_on_cursor_moved(distance_m)`, which moves the cursor in every panel.

Corner rename: `CornerTable.corner_renamed(index, distance, name)` →
`MainWindow.rename_corner` → `CatalogGateway.set_corner_name` → every open session
re-applies names and drops its `SessionAnalysis` → `show_lap` again.

### Theme (`presentation/theme.py`)

Two layers: a `Palette` (four surface steps, three text steps, one accent, the
corner radius, the type families and a `TypeScale`) and semantic roles read from it
(`BACKGROUND`, `SURFACE`, `SURFACE_RAISED`, `BORDER`, `TEXT*`, `ACCENT`,
`PLOT_BACKGROUND`, `TYPE`). Panels use the roles, never a hex literal.

**Type scale** (`TYPE`, pixels): `micro` 10 (turn numbers on the map), `caption` 11,
`label` 12 (headers, dock and plot titles), `body` 13, `stat` 15, `title` 17. Every
`font-size` in the style sheet is a step; text pyqtgraph draws uses
`PLOT_TEXT_SIZE` or `theme.font(step)`.

**Tones** say what a coloured figure *means*: `Tone.GAIN`, `LOSS`, `BEST`,
`WARNING`, `DIM` (`TONE_COLOURS`). `theme.verdict(value, higher_is_better=...)` is
the single gain/loss rule shared by the corner table, the corner card, the header
and the trace readout. On a `QLabel` a tone is a dynamic property the style sheet
selects on (`theme.set_tone`, which re-polishes); on a table or tree item, which no
style sheet reaches, it is a foreground (`theme.tone_colour`). Other helpers:
`theme.emphasised(font)` (the one emphasis weight), `theme.figures(font)`
(tabular digits), `theme.standout_brush()` / `STANDOUT_BAR_WIDTH` (the bar
beside the one row that stands out), `theme.header_band()` (font and colours of
a hand-painted header band - no style sheet reaches it), and `theme.set_series(label, key)` - a figure coloured as the
chart series it was read from (`SERIES_COLOURS`: primary, comparison, ideal,
throttle, brake), again a style-sheet property. No panel builds HTML. Widgets are transparent by default; only the window,
the panels (docks and the `#central` card) and the widgets Qt paints itself name a
surface, which is what lets a panel be a card without every label carrying a
background.

**Data colours are not in the palette** (reference/comparison/ideal traces, pedal
states, `GAIN`/`LOSS` and their fills, the map's `LOSS_SCALE`): they mean the same
thing whatever the chrome looks like. The identity rests on one rule: **the accent
is never a data colour**.

`tests/test_theme.py` holds it (hue distance from every data colour), together with
AA contrast for text and accent, a style sheet that parses and uses only known
properties, font sizes drawn from the scale, a reference/comparison pair that stays
apart under simulated protanopia, deuteranopia and tritanopia (Machado 2009, CIE76
ΔE ≥ 40), and two guards over every other module in `presentation/`: **no colour
literal and no `setStyleSheet`**. The print palette in `infrastructure/export/`
(white paper) is separate by design. Dark only; there is no light theme.

### Rules baked into the UI

- Two laps are only ever compared on the **distance axis**; the time axis action
  is disabled while a comparison is drawn.
- A reference from a **different track** is refused with a banner; a different
  **car** is allowed with a warning.
- The ideal lap chart shows **speed only** — it has no pedal/steering trace
  because nobody drove it.
- Dimmed (not hidden): partial/invalidated/pit laps in the lap list, and sessions
  with no comparable lap in the browser.

### Other UI facts

- `chart_panel.ROW_SPECS` is the single description of the stacked rows (speed,
  pedals, steering, gear, RPM, delta); `DEFAULT_ROWS` = speed, pedals, delta.
  Scales (m/s→km/h, fraction→%) are applied at this edge only.
- **Every plot is made by `plotting.make_plot`**: themed background, quiet axes
  (line in `BORDER`, numbers `TEXT_MUTED`, no tick marks, caption-size tabular
  tick font, no SI prefix), grid, axis titles via `plotting.set_label`. The traces,
  map, g-g and consistency chart all use it.
- **Static layers are cached** (`plotting.freeze`, `DeviceCoordinateCache` on
  curves, fills, scatters and axes; never on the cursor). Two things keep the
  cache valid, and both are load-bearing: `plotting.reserve_cache` raises Qt's
  global `QPixmapCache` from 10 MB to 64–256 MB by screen size (at 10 MB the rows
  evicted each other and every move missed), and rows fit their Y range once per
  lap (`chart_panel._fit_y`) instead of leaving pyqtgraph's auto-range on, which
  re-applies the range on every paint and discards the caches. Pens are
  **cosmetic** (`LineStyle.pen`): widths are pixels, not data units. One
  visible effect, accepted: a cached axis draws its text with greyscale
  antialiasing, because a cache pixmap is transparent and subpixel (ClearType)
  needs an opaque surface. Dropping the axis cache to get ClearType back costs
  repaint 3 → 32 ms and pan 38 → 90 ms. `test_caching_does_not_change_a_pixel`
  compares with text aliased for that reason.
  `scripts/bench_charts.py` (13 600 m lap, 6 rows, 2 laps + delta): cursor move
  86 → 4 ms, repaint 95 → 3 ms, pan 115 → 38 ms, load 120 → 88 ms.
- **Colour is never the only cue.** The comparison lap is dashed in every row
  (`chart_panel.line_style`); its readout figure is italic. Map classes differ by
  width and dash as well as colour (`track_map.PEDAL_STYLES`, `LOSS_STYLES`:
  losing solid and wider with the rate, gaining dashed); a test holds that no
  two classes share a (width, dash) pair. Keys (`chart_widgets.LineKey`) draw
  each line as it is drawn.
- **Above the traces** (`ChartStack.chrome`, a strip that scrolls sideways when
  narrow): the key (`LapTrace.key` - "Volta 5", "Ref. · volta 3"; the full label
  is the tooltip), the channel chips (the window's `commands.channels` actions
  via `set_channel_actions`, short `RowSpec.chip` names), and the readout - one
  `ReadoutCell` per quantity with a minimum width from its widest figure
  (`Series.widest`), so the row holds still. `ChartStack.readout_at(x)` returns
  the figures as data.
- `chart_panel`, `track_map` and `gg_panel` take numpy arrays and labels, not
  sessions, so they are testable with tiny arrays.
- `theme.apply` must run **before** any widget is built (pyqtgraph reads its
  globals at construction). Fixed left-axis width keeps stacked rows aligned.
- **All user-visible text is in `shared/strings.py`** (~620 lines). The one-way
  rule: strings is a leaf. Adding UI text means adding a constant there.
- **`formatting.py` is the one place a number becomes text.** `format_lap_time`
  (m:ss.mmm), `format_sector_time`, `format_seconds(s, decimals=3)` (a time,
  unsigned), `format_gap(s, decimals=3)` (a difference, always signed),
  `format_speed(m_s, signed=False)` (m/s in, km/h to a tenth out - the only
  place that conversion is done for display), `format_distance(m, decimals=0)`,
  `format_value(v, decimals)` (a readout figure already in display units). Each
  returns the number without its unit (headers and `strings` templates carry
  it) and `MISSING` ("--") for None, NaN or ±inf. Signed forms round first, so
  a difference that shows as zero is "+0.000", never "-0.000". Templates in
  `strings.py` take the formatted text (`{std}`, not `{std:.3f}`).
  `tests/test_formatting.py` holds every helper against None, NaN, ±inf, zero,
  negatives and values that round to zero.

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
`pipeline` types into `export`); it is assembled by `exporting.report_context`
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

**P1 (partly) — Importing no longer freezes the window.** `ImportRunner`
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
  `channel_registry.channels_by_format`, `catalog.corner_names`,
  `importer.load_cached`, `corrections.reference_*_g`. Delete any when sure it
  will not be wired. (`catalog.forget_session` is now used, by
  `forget_missing_sessions`; there is still no UI to forget a session by hand.)
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
label constants to `strings.py` (axis title, readout caption, chip name). The
View ▸ Channels menu and the chips are generated from `ROW_SPECS`. Add the column to `tables.CHANNEL_COLUMNS` if it should reach the CSV.

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
`lap_view.benchmark_selection_for`/`compose`, add it to `COMPARISON_MODES` and the
labels in `window_actions.py` and strings; delta arrays come from `pipeline`.
