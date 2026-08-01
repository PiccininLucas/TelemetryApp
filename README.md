# LMU Telemetry Analyzer

Post-session telemetry analysis for [Le Mans Ultimate](https://www.lemansultimate.com/).
Reads the simulator's native DuckDB session files and turns them into the kind
of debrief a race engineer would hand a driver: corner-by-corner comparison
against a reference lap, a theoretical ideal lap, consistency ranking across a
stint, and a grip envelope.

Runs fully offline. The application makes no network calls of any kind.

> Interface is in Portuguese; code, identifiers and documentation are in English.

**Status: phase 4 of 10.** Ingestion, the historical catalog and the whole
analysis layer are done. See [Roadmap](#roadmap).

---

## Why this exists

I am a mechanical engineering student and I race in LMU. Two goals, equally
weighted: a tool I actually use to go faster, and a portfolio piece for
automotive engineering roles. That shapes the design - every formula that
involves physics is documented with its assumptions and with where it breaks
down, rather than being presented as a black box.

---

## The data format

Since version 1.2 the game writes telemetry natively to DuckDB, one file per
session, in `UserData/Telemetry`:

```
Circuit de la Sarthe_R_2026-07-30T20_44_16Z.duckdb
```

There is **no telemetry table**. There is one table per channel, in one of four
column layouts:

| Layout | Columns | Meaning | Example |
|---|---|---|---|
| A | `value` | continuous, single valued | `Engine RPM` |
| B | `value1..value4` | continuous, per wheel | `TyresPressure` |
| C | `ts`, `value` | event, single valued | `Gear` |
| D | `ts`, `value1..value4` | event, per wheel | `TyresCompound` |

Three catalog tables describe the rest: `channelsList` (name, frequency, unit),
`eventsList` (name, unit) and `metadata` (key/value).

### The part that matters

**Continuous channels carry no timestamp.** Time is implicit in the row index:

```
t[i] = i / frequency
```

That turns ingestion into index arithmetic instead of a temporal join. It also
means that if the game stalls mid-recording, index and time stop corresponding
and every downstream alignment lies with no error raised anywhere.

The correction is not a feature, it is a required part of ingestion:
`GPS Time` is a continuous channel carrying a real clock, recorded at 100 Hz.
Ingestion compares the index-derived time against it and, past a configurable
tolerance, rebuilds the time base from `GPS Time` and raises a visible warning.

---

## Verified schema

Schema verification is phase 1's deliverable, not an assumption. Run it against
your own files:

```bash
python scripts/inspect_schema.py "path/to/session.duckdb"
```

Pass several files to compare their schemas. `--json out.json` writes a
machine-readable summary.

List the laps of a session, which exercises the whole ingestion path:

```bash
python scripts/list_laps.py "path/to/session.duckdb"
```

```
  volta        tempo    medido       S1       S2       S3  situação
  --------------------------------------------------------------------
    0     2:01.920   229.468   47.954  38.928  35.038  parcial
    1        --      106.900   35.391      --      --  invalidada
    2     1:50.402   110.420   39.045  36.521  34.836  válida
    5     1:58.171   118.180   35.488  47.303  35.380  fora da pista, válida (3.4%)
    8 *   1:47.060   107.060   35.717  36.283  35.060  válida
```

It ends with an independent cross-check: `Lap Dist` resets to zero at every
start/finish crossing, so the reset must land on the reconstructed lap boundary.
It does, within one sample of a channel that was never involved in producing
those boundaries.

What inspecting three real sessions (Practice, Qualifying and Race; a GT3 and
an LMP3) established:

- **101 tables**: 98 channels + 3 catalog tables. Identical across all three
  session types and both cars.
- **Layout counts**: 42 × A, 16 × B, 38 × C, 2 × D. No unrecognised layouts.
- **Catalog is exact**: every channel has a table, every table has a catalog
  entry, 98 = 98.
- **The implicit time base holds.** `GPS Time` is monotonic with a step of
  exactly 0.010000 s (median, minimum *and* maximum), and its measured span
  matches `(n-1)/frequency` to within 0.0000 s. No stall in any session tested.

Three findings that changed the design:

1. **`channelsList.frequency` is an `INTEGER` column**, so a channel whose real
   rate is not a whole number is stored truncated. `Engine Oil Temp` and
   `Engine Water Temp` are declared at 7 Hz and actually run at 7.017 Hz -
   believing the declared value puts them 3.5 s out of position by the end of a
   24-minute session. Ingestion derives the rate empirically instead,
   `f = (n-1) / gps_time_span`.

2. **Some continuous-layout channels carry discrete values.** `TC` and
   `OverheatingState` are `BOOLEAN` in layout A, `SurfaceTypes` is `UTINYINT`
   in layout B. Interpolating them would invent a surface type halfway between
   asphalt and kerb. Discreteness is read from the column type, not from the
   layout.

3. **`metadata` identifies the car**, so importing never has to ask:
   `CarName`, `CarClass`, `TrackName`, `TrackLayout`, `WeatherConditions`,
   `SessionType`, plus a full `CarSetup` JSON blob.

### Units the files declare

Conversion is driven by the `unit` column, never by a hand-written per-channel
table. Canonical internal units: m/s, m, s, deg, 0-1 pedals, g, degC, kPa.

Two worth knowing about, because they are easy to get wrong:

- `Ground Speed` is in **km/h**, while `GPS Speed` and `Wheel Speed` are in m/s.
- Pedals and `Steering Pos` are in **percent**. Every analysis threshold is
  expressed as a fraction, so the 0-100 → 0-1 conversion is on the critical
  path. `Steering Pos` is percent of full lock, *not* degrees; converting it to
  an angle needs the steering lock from the `CarSetup` blob.

### Two channels are mislabelled

**`G Force Lat` holds longitudinal acceleration and `G Force Long` holds
lateral acceleration. Both are negated.**

Neither acceleration needs the G channels to be measured. Longitudinal is
`dV/dt` from `Ground Speed`; lateral is `V·ω` with `ω` from the wheel-speed
asymmetry and the track width. Correlating each channel against both references
over full race sessions at three tracks with two cars:

| channel | vs `dV/dt` | vs `V·ω` | is really |
|---|---|---|---|
| `G Force Lat` | **−0.997** | −0.075 | longitudinal, negated |
| `G Force Long` | −0.074 | **−0.987** | lateral, negated |
| `G Force Vert` | +0.058 | +0.164 | vertical, correct |

A 0.5 s moving average moves the correlations by less than 0.01, so it is not a
noise artefact. Two independent checks agree: through a sustained 70 km/h corner
at constant speed `G Force Lat` stays near zero and `G Force Long` holds −1.5 g,
and under heavy straight-line braking `G Force Long` averages −0.02 g.

This is not cosmetic. The g-g diagram would plot longitudinal acceleration on
its lateral axis, and the track-map reconstruction from `ω = a_y / V` would
integrate the wrong channel entirely.

Use `session.acceleration("lateral" | "longitudinal" | "vertical")`, which
returns correctly labelled values in g — positive longitudinal under
acceleration, positive lateral in a right-hand corner (SAE convention). The raw
channels remain reachable under their file names via `session.channel(...)`.
`tests/test_physical_validation.py` re-derives the whole result on every run, so
a game update that fixes the labelling fails the suite instead of silently
inverting every sign.

### Wheel order is FL, FR, RL, RR — verified, not assumed

Nothing in the file says which of `value1`..`value4` is which wheel. Two
independent physical checks settle it:

- **Front/rear** from brake temperature: the front brakes do most of the work,
  and wheels 1,2 run 60 °C hotter than 3,4 (283 °C vs 223 °C at Le Mans,
  387 vs 330 at Monza).
- **Left/right** from cornering kinematics: the outside wheels run a larger
  radius and turn faster. Grouped by steering sign, the asymmetry between
  wheels (1,3) and (2,4) flips direction and is worth about 0.7 m/s each way.

Tyre temperature is useless for this — it has seconds of thermal inertia and
reflects the whole lap's balance rather than the corner you are in. It never
flips sign between left and right corners, which is what made the kinematic
check necessary.

### Lap structure

- **`Lap`** fires at each start/finish crossing with the new lap number; lap *k*
  runs from its event to the next.
- **`Lap Time`** fires at the same instant with the time of the lap that just
  *ended*, matching the gap between crossings to within 0.02 s. **Exactly zero
  means the game invalidated the lap** — that ruling is about track limits,
  which no channel records, so it is taken as authoritative.
- **`Last Sector1` and `Last Sector2` are cumulative**, not per-sector. Sector
  durations are `S1`, `S2 − S1`, `LapTime − S2`. Verified against `Current
  Sector` transitions, and the three durations sum to the lap time exactly.
- The first and last lap of every session are partial, because recording starts
  and stops mid-lap. Normal, flagged, not discarded.
- **Off-track does not imply an invalid lap.** A Monza lap with a
  near-stationary excursion onto grass stayed valid, while laps with no
  off-track sample at all were invalidated. The two are reported independently.

Surface codes were identified by correlating each with speed: 0 = track
(~176 km/h), 2 = grass (18 km/h during a real excursion), 4 = gravel (39 km/h),
5 = kerb (128 km/h and the highest lateral g — being ridden), 6 = another legal
surface. Configurable in `config/defaults.toml`.

### Channels that do not exist

`Yaw Rate`, `Lateral Acceleration`, `Longitudinal Acceleration`, `Steered Angle`
and the aerodynamics channels are **not recorded**. Accelerations are available
only through `G Force Lat`, `G Force Long` and `G Force Vert`. No code depends
on the absent ones; the inspection script flags it loudly if one ever appears.

---

## Getting started

Requires Python 3.11+ (developed on 3.14).

```bash
uv venv                                  # or: python -m venv .venv
uv pip install -r requirements.txt       # or: .venv/bin/pip install -r requirements.txt
pytest -q
```

Tests that need a real session file skip themselves when none is present, so a
clone without the game installed still gets a green run. Point them at your own
folder with `LMU_TELEMETRY_DIR`.

---

## Analysis

```bash
python scripts/analyse_session.py "path/to/session.duckdb"
```

Distance is rebuilt by integrating `Ground Speed` at 100 Hz (0.7 m between
samples) rather than read from `Lap Dist` at 10 Hz (6.9 m at 250 km/h, which
cannot locate a braking point), then rescaled to close on the known lap length.
Every comparison then happens on a 1 m distance grid — two laps cover the same
metres, not the same seconds.

Run against a real Le Mans lap, the corner detector reads the circuit back:

```
  curva      ápice    v_mín   v_entr  frenagem  dist.fren  retomada
  C4          4119    106.5    280.8      3905        214      4119     Mulsanne chicane 1
  C6          7740     81.2    266.9      7575        165      7740     Mulsanne corner
  C7          9850    110.0    274.8      9519        331      9850     Indianapolis
  C8         10165     75.9    176.9     10072         93     10165     Arnage
  C10        12297    169.0      n/d       n/d        n/d     12297     taken without braking
```

Arnage at 75.9 km/h really is the slowest corner at Le Mans, and C10 correctly
reports no braking point rather than inventing one.

The track map cross-checks itself. The GPS projection gives a bounding box of
2597 × 5441 m against the real circuit's ~2.6 × 5.4 km and closes to 0.3 m; the
independent reconstruction from `ω = a_y / V`, which uses no position data at
all, stays within 10 m mean of it at Monza.

**The theoretical ideal lap is not a record.** Exit speed from one segment sets
entry into the next, so stitching the best segments produces a target that is
probably optimistic. Segment boundaries sit midway along the straight between
corners, never at an apex, and the speed discontinuities at the seams are
reported so they can be drawn rather than smoothed away — they are the evidence
that the lap never happened.

Two corrections came out of running the analysis on real data rather than only
on the synthetic circuit:

- **Corner detection works from "where is the car slow", not from peak-picking.**
  A corner held at the cornering limit produces a perfectly flat speed plateau,
  and smoothing rings at its shoulders, so peak-picking found two minima at the
  edges of every corner and none in the middle.
- **Time lost per corner is measured, not modelled.** Estimating it from apex
  speed as `L·(1/V − 1/V_best)` claimed 26 s of loss in one Monza corner of a
  107 s lap, because a corner's window spans the whole stretch to its
  neighbour. Reading each lap's time through the corner directly and comparing
  against the driver's own best has no such failure mode.

### Layering

`analysis` imports numpy, scipy and the standard library — nothing else.
`tests/test_architecture.py` walks the **transitive** import closure to enforce
it, because a direct-imports-only check passes happily while `analysis` reaches
`ingest` through `core`. `lmu_telemetry/pipeline.py` is the seam that joins
ingestion to analysis, and is what the UI will use.

---

## Storage

Everything the app writes lives under `~/.lmu-telemetry` (override with
`LMU_TELEMETRY_DATA_DIR`). Nothing is ever written next to the game's files, and
session files are opened read-only.

```bash
python scripts/import_session.py --folder "path/to/UserData/Telemetry"
python scripts/import_session.py --show
```

The **catalog** (`catalog.duckdb`) answers what a single session cannot: the
best lap ever at a track in a car, what the corners are called, which sessions
exist. Keys are natural — a session's id is its source file's SHA-256, a lap's
is `<session_id>:<index>` — so re-importing a file updates it in place and
import is idempotent without checking first.

`best_laps` is a **view**, not a table. The specification lists it among the
tables, but a stored best lap goes stale the moment a session is re-imported or
deleted, and a wrong personal best is worse than none.

### Why channel data is not cached

The specification asks for the normalised telemetry to be persisted to parquet.
Measured on real sessions, that is a bad trade:

| | |
|---|---|
| read 5 chart channels from the game's file | 3.8 ms |
| read the same 5 columns from a parquet copy | 2.9 ms |
| size of a 100 Hz parquet copy | **1.95×** the source (52 MB from 26.7 MB) |

The source is already a compressed columnar database, so re-encoding it buys
about a millisecond and costs twice the disk — roughly 1.9 GB for 64 sessions.
Dropping the 26 channels that never vary saves nothing either; constant columns
already compress to almost nothing.

What *is* expensive is opening a session: 83 ms, of which 53 ms is building the
channel registry from one `DESCRIBE` and one `COUNT(*)` per channel. Browsing 64
sessions costs about 5 s before anything is drawn. So the cache stores the
**manifest** — identity, time base, channel registry, lap table — at a few
kilobytes each. The whole cache for 64 real sessions is **1.2 MB**.

Phase 4 adds the artifact that genuinely is expensive to recompute: per-lap
frames on a 1 m distance grid, which need cumulative integration of speed and a
per-lap scale correction. Those land in `laps/` inside the same session folder
and reuse the same hash invalidation.

---

## Architecture

Five layers, dependencies strictly in one direction.

```
lmu_telemetry/
├── ingest/     # the only layer that knows the file format exists
├── core/       # models, units, errors. Depends on nothing.
├── analysis/   # numpy arrays in, numbers out
├── storage/    # parquet cache + historical catalog
├── ui/         # PySide6. All user-visible text lives in ui/strings.py
└── export/     # PNG, CSV, PDF report
```

**`analysis` may not import `ingest`, `ui`, `storage`, `export`, `duckdb`,
`pandas` or Qt.** It takes numpy arrays and returns numbers. That is what lets
every formula be tested without the game installed, and what would let a live
data source feed the same functions later without touching an equation. The
rule is enforced mechanically by `tests/test_architecture.py`, which parses
imports with `ast` rather than grepping.

On-screen charts use `pyqtgraph` because a long session is hundreds of
thousands of points per channel and zoom has to stay fluid; `matplotlib` is
used only for export, where print quality matters more than interactivity.

---

## Privacy

Session files from online races contain **other people's data**: driver names,
team names, nationalities and server names. Raw `.duckdb` files are excluded by
`.gitignore`. Only the anonymised demo dataset produced by
`scripts/make_demo_dataset.py` (phase 10) is ever committed, and that script
strips those fields and writes a new file rather than modifying the original.

---

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Schema verification, catalog reading, channel registry | ✅ done |
| 2 | Time base with `GPS Time` validation, step events, lap splitting | ✅ done |
| 3 | Session cache + historical catalog | ✅ done |
| 4 | Full analysis layer with unit tests on synthetic data | ✅ done |
| 5 | Minimal UI: session browser + speed trace | |
| 6 | Synchronised multi-channel charts + delta-t | |
| 7 | Track map + g-g diagram | |
| 8 | Corner table, persistent naming, theoretical ideal lap | |
| 9 | Consistency panel | |
| 10 | Export (PNG/CSV/PDF), demo dataset, docs | |

Deliberately out of scope: live telemetry, HUD/overlay, 3D, tyre degradation
modelling and fuel strategy. The ingestion layer is designed so a live source
could be added later, but that source is not being built.

---

## License

Not affiliated with Studio 397, Motorsport Games or the ACO.
