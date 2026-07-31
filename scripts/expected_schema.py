"""The schema as documented in the project specification, section 1.

This list came from a **binary inspection** of a session file, not from SQL, so
it is a hypothesis to be checked - never a source of truth. It is used by
`inspect_schema.py` for one purpose only: to report where the real file differs,
so a human decides what to do about it.

Production code must never import this module. `channel_registry` derives every
layout from the file's own DESCRIBE output, so a game update that reshapes a
channel changes behaviour automatically; this file only makes the change
*visible*.
"""

from __future__ import annotations

# --- Format A: continuous, single valued: (value,) ---------------------------
EXPECTED_FORMAT_A: frozenset[str] = frozenset({
    "Ambient Temperature",
    "Brake Pos",
    "Brake Pos Unfiltered",
    "Clutch Pos",
    "Clutch RPM",
    "Engine Oil Temp",
    "Engine RPM",
    "Engine Water Temp",
    "FFB Output",
    "Front3rdDeflection",
    "FrontRideHeight",
    "Fuel Level",
    "G Force Lat",
    "G Force Long",
    "G Force Vert",
    "GPS Latitude",
    "GPS Longitude",
    "GPS Speed",
    "GPS Time",
    "Ground Speed",
    "Lap Dist",
    "Path Lateral",
    "Rear3rdDeflection",
    "RearRideHeight",
    "Regen Rate",
    "SoC",
    "Steering Pos",
    "Steering Pos Unfiltered",
    "Steering Shaft Torque",
    "TC",
    "Throttle Pos",
    "Throttle Pos Unfiltered",
    "Time Behind Next",
    "Total Dist",
    "Track Edge",
    "Track Temperature",
    "Turbo Boost Pressure",
    "Virtual Energy",
    "Wind Heading",
    "Wind Speed",
})

# --- Format B: continuous, per wheel: (value1..value4) -----------------------
EXPECTED_FORMAT_B: frozenset[str] = frozenset({
    "Brake Thickness",
    "Brakes Air Temp",
    "Brakes Force",
    "Brakes Temp",
    "RideHeights",
    "SurfaceTypes",
    "Susp Pos",
    "TyresCarcassTemp",
    "TyresPressure",
    "TyresRimTemp",
    "TyresRubberTemp",
    "TyresTempCentre",
    "TyresTempLeft",
    "TyresTempRight",
    "Tyres Wear",
    "Wheel Speed",
})

# --- Format C: event, single valued: (ts, value) -----------------------------
EXPECTED_FORMAT_C: frozenset[str] = frozenset({
    "ABS",
    "AntiStall Activated",
    "Best Sector1",
    "Best Sector2",
    "Brake Migration",
    "CloudDarkness",
    "Current LapTime",
    "Current Sector",
    "Current Sector1",
    "Current Sector2",
    "Engine Max RPM",
    "Finish Status",
    "FrontFlapActivated",
    "FuelMixtureMap",
    "Gear",
    "Headlights State",
    "In Pits",
    "Lap",
    "Lap Time",
    "LastImpactMagnitude",
    "Last Sector1",
    "Last Sector2",
    "LaunchControlActive",
    "Minimum Path Wetness",
    "OffpathWetness",
    "RearFlapActivated",
    "RearFlapLegalStatus",
    "Sector1 Flag",
    "Sector2 Flag",
    "Sector3 Flag",
    "Speed Limiter",
    "TCCut",
    "TCLevel",
    "TCSlipAngle",
    "Yellow Flag State",
})

# --- Format D: event, per wheel: (ts, value1..value4) ------------------------
EXPECTED_FORMAT_D: frozenset[str] = frozenset({
    "TyresCompound",
    "WheelsDetached",
})

#: Channel name -> expected format letter.
EXPECTED_BY_CHANNEL: dict[str, str] = {
    **{name: "A" for name in EXPECTED_FORMAT_A},
    **{name: "B" for name in EXPECTED_FORMAT_B},
    **{name: "C" for name in EXPECTED_FORMAT_C},
    **{name: "D" for name in EXPECTED_FORMAT_D},
}

#: Channels the specification states are NOT recorded. No production code may
#: depend on them; the report flags it loudly if one ever shows up, because that
#: would open up yaw-rate-based analyses currently ruled out.
DOCUMENTED_ABSENT: frozenset[str] = frozenset({
    "Yaw Rate",
    "Lateral Acceleration",
    "Longitudinal Acceleration",
    "Steered Angle",
})
