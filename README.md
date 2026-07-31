# LMU Telemetry Analyzer

Post-session telemetry analysis for [Le Mans Ultimate](https://www.lemansultimate.com/).
Reads the simulator's native DuckDB session files and turns them into the kind
of debrief a race engineer would hand a driver: corner-by-corner comparison
against a reference lap, a theoretical ideal lap, consistency ranking across a
stint, and a grip envelope.

Runs fully offline. The application makes no network calls of any kind.

> Interface is in Portuguese; code, identifiers and documentation are in English.

**Status: phase 1 of 10.** Schema verification, catalog reading and the channel
registry are done. See [Roadmap](#roadmap).

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
| 2 | Time base with `GPS Time` validation, step events, lap splitting | |
| 3 | Parquet cache + historical catalog | |
| 4 | Full analysis layer with unit tests on synthetic data | |
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
