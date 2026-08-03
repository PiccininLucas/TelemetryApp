# Methodology

Every number this application shows, where it comes from, what it assumes, and
where the assumption breaks. Written so a result can be argued with rather than
taken on trust — which is the only reason to build an analysis tool rather than
read the game's own timing screen.

Findings from real data are marked **[measured]**. Everything else is method.

---

## 1. Time

### The problem

Continuous channels in an LMU session file carry **no timestamp**. Time is
implicit in the row index:

```
t[i] = i / f
```

That makes ingestion index arithmetic instead of a temporal join, and it makes
the whole file depend on one assumption: that the game wrote every sample. If it
stalls, index and time stop corresponding and every downstream alignment lies
with no error raised anywhere.

### The check

`GPS Time` is a real clock recorded as an ordinary continuous channel at 100 Hz.
Comparing the index-derived time against it tests the assumption directly. Past
a configurable tolerance (`ingest.time_base.max_drift_s`, 0.05 s) the time base
is rebuilt from `GPS Time` and a banner is raised in the interface.

**[measured]** Across the sessions tested, `GPS Time` is monotonic with a step of
exactly 0.010000 s — median, minimum *and* maximum — and its span matches
`(n−1)/f` to within 0.0000 s. Some sessions do drift: one Monza qualifying
showed 0.4336 s and was corrected.

### Declared frequency is not the real frequency

**[measured]** `channelsList.frequency` is an `INTEGER` column, so a channel
whose real rate is not a whole number is stored truncated. `Engine Oil Temp` and
`Engine Water Temp` are declared at 7 Hz and run at 7.017 Hz. Believing the
declared value puts them 3.5 s out of position by the end of a 24-minute
session.

The rate is therefore derived empirically:

```
f = (n − 1) / span_of_GPS_Time
```

### Event channels have their own clock

Layouts C and D carry a `ts` column and are written **only when the value
changes**. Giving them the implicit uniform grid moves every one of them.

**[measured]** `Gear` records 962 events over a 24-minute race. Spread
uniformly they land 1.5 s apart instead of at the instants they happened, and
since half of those events are the momentary neutral of a shift, the car appears
to be out of gear for half of every lap. Fixed in phase 6; nothing before that
read an event channel through that path.

---

## 2. Distance

### Why it is reconstructed rather than read

`Lap Dist` is recorded at 10 Hz. At 250 km/h that is one sample every 6.9 m,
which cannot locate a braking point. `Ground Speed` is recorded at 100 Hz —
about 0.7 m between samples at the same speed.

Distance is therefore rebuilt by trapezoidal integration of speed:

```
s(t) = ∫ V dt
```

Integration accumulates drift, so the result is rescaled to close on the known
lap length:

```
s_corrected = s_raw × (L_reference / L_integrated)
```

The scale factor is rejected outside 0.9–1.1 (`analysis.distance`). A factor far
from 1 means the integration or the reference length is wrong, and silently
stretching the lap to fit would hide it.

`L_reference` comes from the catalog, which stores the median of every imported
lap's maximum `Lap Dist` for that track.

### Everything is compared in the distance domain

Two laps at the same *elapsed time* are at different points of the circuit, so
any difference between them is a statement about nothing. Every channel is
resampled onto a 1 m grid (`analysis.resample.step_m`) and every comparison
happens there.

The interface enforces this rather than documenting it: the time axis is
available for reading a single lap's rhythm and is **disabled** while two laps
are drawn.

### Resampling: interpolated or held

Continuous channels are interpolated linearly. Discrete ones — gear, flags, tyre
compound, surface type — are **held** (zero-order hold). Interpolating them would
invent a gear 3.5 and a surface halfway between asphalt and kerb.

Discreteness is read from the column's SQL type, not from the layout:
**[measured]** `TC` and `OverheatingState` are `BOOLEAN` in a continuous layout,
and `SurfaceTypes` is `UTINYINT`.

---

## 3. Accelerations

### The channels are mislabelled

**[measured]** `G Force Lat` holds **longitudinal** acceleration and
`G Force Long` holds **lateral** acceleration. Both are **negated**.

Neither needs the G channels to be measured independently:

| | recorded channel | independent estimate | correlation |
|---|---|---|---|
| longitudinal | −2.32 / +1.26 g | `dV/dt` from Ground Speed: −2.36 / +0.90 g | 0.9925 |
| lateral | 2.84 g peak | `V·ω` from wheel-speed asymmetry: 3.11 g peak | 0.9814 |

`ingest.corrections` applies the swap and the sign before anything downstream
sees the values. Without it the g-g diagram plots longitudinal acceleration on
the lateral axis and the integrated track map turns the wrong way.

The lateral cross-check is

```
ω = (v_left − v_right) / track_width
a_y = V · ω
```

which assumes small slip angles and no wheelspin. `track_width` scales the
magnitude but not the sign, and the sign is what it is used for.

### The magnitudes are the simulation's

**[measured]** A GT3 at Le Mans reaches 2.8 g lateral, above what the real car
does. Two independent derivations agree, so that is the simulation's grip level
and not a fault in this pipeline. Worth knowing before the number is read as a
real-world figure.

---

## 4. Corners

A corner, here, is **a sustained local minimum in speed**. That definition is
about what the driver did rather than about the circuit's geometry: a fast kink
taken flat is not a corner to analyse, and two geometric bends taken as one long
arc are one corner to a driver.

### Detection

1. Smooth the speed trace with a Savitzky–Golay filter. Unlike a moving average
   it fits a local polynomial, so it removes noise without displacing a minimum —
   and the position of the minimum *is* the measurement.
2. Find contiguous regions below a fraction of the lap's maximum speed
   (`speed_threshold_fraction`, 0.85).
3. Split a region at any internal speed peak rising by at least
   `split_prominence_fraction` (0.08) of the lap maximum.
4. Merge apexes closer than `min_separation_m` (50 m), keeping the slower.
5. The apex is the **centre of the plateau**, not the first sample at the
   minimum.

**Two corrections came from real data, not from the synthetic circuit:**

- **[measured]** Peak-picking on the negated speed trace found two minima at the
  *edges* of every corner and none in the middle, because a corner held at the
  cornering limit produces a perfectly flat plateau and smoothing rings at its
  shoulders. Hence step 2 replacing peak-picking, and step 5.
- **[measured]** Monza came out with four corners instead of six: corners joined
  by a short throttle burst never rise back above the threshold. Hence step 3.
  The separation rule then had to move from *regions* to *apexes*, because the
  split halves touch and were being merged straight back together.

### Per-corner measurements

- **Braking point** — where sustained braking begins, `brake_threshold` (0.03)
  held for `brake_min_duration_s`.
- **Trail braking** — distance over which braking continues past turn-in while
  speed is still falling.
- **Coasting** — time inside the corner window with neither pedal applied. The
  cost of an unresolved decision between brake and throttle, and invisible on a
  speed trace.
- **Throttle resumption** — where sustained throttle returns after the apex.

### Corner identity

Corners are matched between laps **by apex distance**, with a 50 m tolerance.
Names the user gives are stored per track and anchored to a distance, never to a
corner number: the number shifts the moment the detector finds one more or one
fewer corner, and a name pinned to an index would move to the wrong corner and
quietly stay wrong.

---

## 5. Delta-t

```
delta(s) = t_lap(s) − t_reference(s)
```

Positive means the lap is behind at that point. **The slope matters more than
the value**: a rising delta is where time is being lost right now, while a flat
delta at a high value is a loss that happened earlier and is being carried.

For colouring the track map, the slope is what is used — colouring by the value
paints the whole second half of the lap red because of one mistake at turn one.
The derivative of a 1 m-grid delta is noise (two laps a metre apart differ by
microseconds), so the delta is smoothed with Savitzky–Golay **before**
differentiating, using `deriv=1` so the derivative comes from the fitted
polynomial rather than from differencing smoothed values.

Classes: below 0.5 s/km is within the repeatability of two laps by the same
driver and is reported as neutral; above 2 s/km is marked strongly.

---

## 6. The ideal lap

The lap is cut into segments and each is credited to whichever lap was fastest
through it. **Boundaries sit midway along the straight between one apex and the
next, never at an apex**, so a corner's braking, apex and exit always stay in one
segment — a corner is driven as one action, and splitting it would compare
fragments that never happened together.

### It is a target, not a record

Exit speed from one segment conditions entry into the next, so a lap that was
quickest through segment 3 may have been quickest precisely because it
sacrificed the entry to segment 4. The interface states how many laps contribute
— one means the ideal lap *is* a real lap and is therefore achievable — and the
seams where the stitched speed trace jumps are **marked rather than smoothed
away**, because they are the evidence that the lap is synthetic.

**[measured]** Monza, 9 comparable laps: ideal 1:46.424 against a best real
1:47.045, so 0.622 s from 5 contributing laps, with no seam jumping more than
1 km/h. Le Mans, 3 laps: 0.895 s from 3 laps, with one seam jumping 15.2 km/h.

### A defect only the delta could expose

Elapsed time was originally spread **linearly** across each segment, which
assumes constant speed through it. A Monza segment runs from 275 km/h on the
straight to 58 km/h at the apex, so the ideal lap's clock was about a second
wrong in the middle of every segment. Invisible in the lap total — that is the
sum of the segment times either way — and the dominant term in any delta drawn
against it: the worst apparent loss read +1.076 s where the real figure is
+0.622 s at the line. Each winning lap's own elapsed profile is now used.

---

## 7. The grip envelope

Lateral against longitudinal acceleration. The tyre produces roughly a fixed
total force in any direction, so the reachable points fill a rounded region and
the driver's job is to live on its edge.

- **A hollow between the bottom and the sides** means the brake is released
  before the car is turned instead of the two being blended.
- **A small cloud** means the limit was never approached.
- **Points past the usual edge** are not extra grip; they are the moment it ran
  out.

The envelope is the **convex hull** of the points. `fill_fraction` is the hull's
area over that of an ellipse whose semi-axes are the largest lateral and
longitudinal magnitudes *this car and driver reached* — not an assumed tyre
model. Values near 1 are not expected: the ellipse is an outer bound.

`transition_quality` is the fraction of the working samples where the smaller
acceleration component is at least a third of the larger — the measurable form
of "does this driver blend braking into turning".

Samples below `analysis.friction.min_speed_ms` (10 m/s) are excluded: a
stationary car registers accelerometer noise that would inflate the envelope.

---

## 8. The track map

### From GPS

Equirectangular projection about the lap's first point:

```
x = R (lon − lon₀) cos(lat₀)
y = R (lat − lat₀)
```

The `cos(lat₀)` factor accounts for meridians converging; without it a circuit at
47° N comes out stretched east–west by about 47%. Over a circuit — at most 14 km
across — the flat-earth distortion is far below the metre.

**[measured]** Monza projects to 1257 × 2169 m and closes to 0.4 m; Le Mans to
2597 × 5441 m and closes to 0.7 m. Both match the real circuits.

### From acceleration alone, as a cross-check

The game records no yaw rate, so it is inferred from the quasi-steady cornering
relation and the heading integrated from it:

```
ω ≈ a_y / V
ψ(t) = ψ₀ + ∫ ω dt
x(t) = ∫ V sin ψ dt,   y(t) = ∫ V cos ψ dt
```

**Where the assumption fails.** `ω = a_y/V` holds for a circular path at
constant radius with negligible sideslip. It is wrong during transients (the car
rotates before lateral acceleration builds), whenever the car is sliding
(sideslip is exactly what the relation assumes away), at low speed (dividing by
`V` amplifies any error without bound), and under braking or traction (load
transfer alters the relation between lateral acceleration and path curvature).
Integration compounds all of it.

**The point is not to replace the GPS trace but to quantify the disagreement.**
The reconstructed path is rotated onto the GPS one first — its absolute
orientation is unknowable, and a rotation offset is not an error in the method —
by solving the 2-D Procrustes problem in closed form.

**[measured]** Monza: closes to 3 m over 5.8 km, 10 m mean error against GPS,
30 m worst. Le Mans: 37 m mean over 13.6 km, 89 m worst — 0.27% of lap length.

---

## 9. Consistency

Lap times hide repeatability. Two drivers with the same average lap time can be
very different: one repeats the same lap, the other alternates a good lap with a
bad one. Only the second has something easy to gain.

Per corner, across a stint: the sample standard deviation (`ddof=1` — these laps
are a sample of how the driver drives, not the population of their laps) of the
braking point, the apex speed and the throttle resumption point.

### Time lost is measured, not modelled

```
loss = mean(t_through_corner) − min(t_through_corner)
```

An earlier version estimated it from apex speed as `L·(1/V − 1/V_best)`.
**[measured]** On real data that produced 26 s of loss in a single corner of a
107 s lap, because a corner's window spans the whole stretch between its
neighbours — about 1400 m at Monza — and the model assumed the deficit was
carried over all of it. Measuring the time directly has no such failure mode.

### Which laps count

Laps slower than the **median** (not the mean — one very slow lap drags a mean
upward and would then justify keeping itself) are dropped. **Two ceilings, and
the tighter wins**: a relative one and an absolute one.

**[measured]** A purely relative allowance does not survive a change of circuit:
5% of a 108 s Monza lap is 5.4 s and 5% of a 245 s Le Mans lap is 12 s. The
relative rule alone admitted a lap taken through the first chicane at 28 km/h —
an incident, not driving — which tripled that corner's reported dispersion
(17.1 km/h of apex spread against a true 6.2) and inflated the stint's available
time from 2.07 to 2.65 s a lap.

### Drift versus scatter

A braking point creeping 20 m over five laps is tyre or fuel state; the same
20 m jumping about is the driver. They have identical standard deviations.

The test is a **rank** correlation against lap order, not a linear one: "is it
drifting" is a question about order, not about linearity. **[measured]** The
linear correlation called the Parabolica a drift from the braking points 5007,
4996, 5005, 5005, 4955 m — four flat laps and one late outlier, whose magnitude
carried the entire statistic.

Consistency is measured **per stint**. Across a pit stop fuel load and tyre age
both step, so the dispersion would report the car's state as the driver's
repeatability.

---

## 10. Privacy

**[measured]** Inspected across all 66 sessions on the development machine,
`metadata` holds thirteen keys and exactly one is personal: `DriverName`.
`SteamID` is present but reads `0` in every file. `CarName` reads like a team —
"Inception Racing 2024 #70:LM" — but is the livery selected in game, which is
published product content. No nationality and no server name appear anywhere,
and `metadata.value` is the only free-text column in the entire schema.

That is narrower than this project's specification assumed, and it is reported
rather than quietly relied on. Anonymisation therefore does two things:

1. Clears the known keys by name.
2. **Sweeps every text column in the file** for any residue of the name, so a
   field the code does not know about — the one that would actually leak — is
   scrubbed too.

The original is copied first and never modified: a tool that can damage the only
record of a session is worse than no tool. The written file is then re-opened
and checked, because verifying the artefact rather than trusting the writer is
the only check that means anything before publishing one.

---

## Layering, and why it is enforced

```
ingest/     the only layer that knows the file format exists
core/       models, units, errors. Depends on nothing.
analysis/   numpy arrays in, numbers out
storage/    session cache + historical catalog
ui/         PySide6. All user-visible text lives in ui/strings.py
export/     PNG, CSV, PDF, anonymisation
```

`analysis` may import numpy, scipy and the standard library — nothing else. That
is what lets every formula here be tested without the game installed, and what
would let a live data source feed the same functions later without touching an
equation.

`tests/test_architecture.py` walks the **transitive** import closure to enforce
it, because a direct-imports-only check passes happily while `analysis` reaches
`ingest` through `core`.
