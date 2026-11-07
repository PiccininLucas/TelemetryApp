"""The official corner numbering of the circuits Le Mans Ultimate ships.

A corner the detector finds is "C3": its position in a list. A corner a driver
talks about is "T3 Hairpin": the number on the track map and the name on the
sign. This module holds the second kind of identity, for the tracks the game
ships, so the interface can speak the circuit's own language.

**Source.** The turn numbers, names and directions come from the Le Mans
Ultimate wiki's *Track Guide* pages (lemansultimate.wiki.gg), one per circuit.
Those pages are driving guides, not survey data, so they have gaps: some turns
have no name, some have no direction, a few turns are not described at all.
Every gap is kept as `None` here instead of being filled in from memory - a
wrong name shown with confidence is worse than a number shown plainly.

**Anchors.** The wiki gives no distances, and a turn cannot be placed on a lap
without one. `anchor_m` is the distance from the start/finish line at which a
turn's apex sits, and it is only filled in for a circuit once it has been
measured against a recorded lap's GPS trace. A track whose turns carry no
anchors is still listed, but `OfficialTrack.anchors` is empty and the analysis
falls back to the speed-based detector for it.

Fuji's anchors were checked three ways against the demo lap: the 16 turns the
wiki lists, the 6 left / 10 right split the circuit's own track-info panel
gives, and the sign of the GPS heading change at each anchor all agree.

This module imports nothing from the rest of the application.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

LEFT = "L"
RIGHT = "R"


@dataclass(frozen=True, slots=True)
class OfficialTurn:
    """One numbered turn.

    Attributes:
        number: The number on the track map. A string because Le Mans numbers
            the Esses de la Forêt 4.1 and 4.2.
        name: The name of the corner or complex the turn belongs to, when the
            source gives one. Several turns share a name - the two parts of a
            chicane are the same corner to a driver.
        direction: `"L"` or `"R"`, only where the source states it or where the
            GPS trace settled it.
        anchor_m: Distance of the apex from the start/finish line, once
            measured. `None` means "not yet placed on a lap".
    """

    number: str
    name: str | None = None
    direction: str | None = None
    anchor_m: float | None = None

    @property
    def label(self) -> str:
        """What the corner is called on screen: `T1`, or `T1 First Corner`."""
        return f"T{self.number} {self.name}" if self.name else f"T{self.number}"


@dataclass(frozen=True, slots=True)
class OfficialTrack:
    """A circuit's official turns.

    Attributes:
        key: Stable identifier.
        display_name: The circuit's name.
        aliases: Names the game may use for it, matched as whole words.
        length_m: The length the game states, in metres.
        turn_count: How many turns the circuit has. Can exceed `len(turns)`:
            the wiki numbers only 21 of Le Mans's 38.
        turns: The turns the source describes, in lap order.
    """

    key: str
    display_name: str
    aliases: tuple[str, ...]
    length_m: float
    turn_count: int
    turns: tuple[OfficialTurn, ...]

    @property
    def anchored_turns(self) -> tuple[OfficialTurn, ...]:
        """The turns that have been placed on a lap, in lap order."""
        placed = [turn for turn in self.turns if turn.anchor_m is not None]
        return tuple(sorted(placed, key=lambda turn: turn.anchor_m))

    @property
    def anchors(self) -> tuple[tuple[float, str], ...]:
        """`(distance_m, label)` for each placed turn."""
        return tuple((turn.anchor_m, turn.label) for turn in self.anchored_turns)

    @property
    def is_calibrated(self) -> bool:
        """True when every turn the source lists can be placed on a lap.

        Measured against the listed turns, not `turn_count`: the wiki numbers
        only 21 of Le Mans's 38 corners and skips Spa's turn 16, and a circuit
        cannot wait for turns nobody has described. What is never allowed is a
        half-placed list, which would label some corners and leave their
        neighbours unnumbered.
        """
        return bool(self.turns) and len(self.anchored_turns) == len(self.turns)

    def fits_lap(self, lap_length_m: float, tolerance: float = 0.05) -> bool:
        """True when a lap of this length can be this circuit.

        Guards against a layout the numbering does not describe - the game ships
        Bahrain's 3.5 km outer circuit under nearly the same name as the 5.4 km
        one. The game's stated length and the wiki's differ by a few metres, so
        the tolerance is about layout, not precision.
        """
        return abs(lap_length_m - self.length_m) <= tolerance * self.length_m


def _turns(*rows: tuple) -> tuple[OfficialTurn, ...]:
    """Build turns from `(number, name, direction[, anchor_m])` rows."""
    return tuple(OfficialTurn(*row) for row in rows)


# ---------------------------------------------------------------------------
# The circuits. Gaps are None, not guesses; see the module docstring.
# ---------------------------------------------------------------------------

FUJI = OfficialTrack(
    key="fuji",
    display_name="Fuji Speedway",
    aliases=("fuji",),
    length_m=4563.0,
    turn_count=16,
    turns=_turns(
        ("1", "First Corner", RIGHT, 758.0),
        ("2", None, RIGHT, 910.0),
        ("3", None, LEFT, 1354.0),
        ("4", "100R", RIGHT, 1580.0),
        ("5", "100R", RIGHT, 1740.0),
        ("6", "Hairpin", LEFT, 2005.0),
        ("7", "Hairpin", LEFT, 2050.0),
        ("8", "300R", RIGHT, 2326.0),
        ("9", "300R", RIGHT, 2540.0),
        ("10", "Dunlop", RIGHT, 2850.0),
        ("11", "Dunlop", LEFT, 2916.0),
        ("12", "Dunlop", RIGHT, 2990.0),
        ("13", None, RIGHT, 3140.0),
        ("14", None, LEFT, 3270.0),
        ("15", None, LEFT, 3397.0),
        ("16", "Panasonic Corner", RIGHT, 3686.0),
    ),
)

MONZA = OfficialTrack(
    key="monza",
    display_name="Autodromo Nazionale Monza",
    aliases=("monza",),
    length_m=5793.0,
    turn_count=11,
    turns=_turns(
        # Anchors and the directions the wiki leaves blank (6, 7, 11) were read
        # off a race lap's GPS heading; the sequence R-L-R-L-R-R-R-L-R-L-R is
        # the circuit's own.
        ("1", "Variante del Rettifilo", RIGHT, 925.0),
        ("2", "Variante del Rettifilo", LEFT, 975.0),
        ("3", "Curva Grande", RIGHT, 1500.0),
        ("4", "Variante della Roggia", LEFT, 2125.0),
        ("5", "Variante della Roggia", RIGHT, 2190.0),
        ("6", "Lesmo 1", RIGHT, 2552.0),
        ("7", "Lesmo 2", RIGHT, 2875.0),
        ("8", "Variante Ascari", LEFT, 3935.0),
        ("9", "Variante Ascari", RIGHT, 4040.0),
        ("10", "Variante Ascari", LEFT, 4150.0),
        ("11", "Curva Parabolica", RIGHT, 5188.0),
    ),
)

SPA = OfficialTrack(
    key="spa",
    display_name="Circuit de Spa-Francorchamps",
    aliases=("spa", "spa francorchamps"),
    length_m=7004.0,
    turn_count=20,
    turns=_turns(
        # Anchors and directions read off a race lap's GPS heading. The wiki never
        # mentions turn 16, so it is absent rather than invented. Turns 2-4 are
        # taken flat out, so their positions are the least certain.
        ("1", "La Source", RIGHT, 266.0),
        ("2", "Eau Rouge / Raidillon", LEFT, 900.0),
        ("3", "Eau Rouge / Raidillon", RIGHT, 1060.0),
        ("4", "Eau Rouge / Raidillon", LEFT, 1190.0),
        ("5", "Les Combes", RIGHT, 2322.0),
        ("6", "Les Combes", LEFT, 2403.0),
        ("7", "Malmedy", RIGHT, 2540.0),
        ("8", "Bruxelles", RIGHT, 2941.0),
        ("9", "Speaker's Corner", LEFT, 3154.0),
        ("10", "Pouhon", LEFT, 3710.0),
        ("11", "Pouhon", LEFT, 3950.0),
        ("12", "Les Fagnes", RIGHT, 4397.0),
        ("13", "Les Fagnes", LEFT, 4539.0),
        ("14", "Campus", RIGHT, 4805.0),
        ("15", "Stavelot", RIGHT, 5030.0),
        ("17", "Blanchimont", LEFT, 5900.0),
        ("18", "Bus Stop", RIGHT, 6617.0),
        ("19", "Bus Stop", LEFT, 6651.0),
    ),
)

LE_MANS = OfficialTrack(
    key="le-mans",
    display_name="Circuit de la Sarthe",
    aliases=("sarthe", "le mans"),
    length_m=13626.0,
    turn_count=38,
    turns=_turns(
        # Anchors and directions read off a race lap's GPS heading. Each Mulsanne
        # chicane is one numbered turn, so it is anchored at its middle.
        ("1", "Dunlop Curve", RIGHT, 650.0),
        ("2", "Dunlop Chicane", LEFT, 840.0),
        ("3", "Dunlop Chicane", RIGHT, 905.0),
        ("4.1", "Esses de la Forêt", RIGHT, 1250.0),
        ("4.2", "Esses de la Forêt", LEFT, 1470.0),
        ("5", "Esses de la Forêt", RIGHT, 1580.0),
        ("6", "Tertre Rouge", RIGHT, 1920.0),
        ("7", "First Mulsanne Chicane", None, 4125.0),
        ("8", "Second Mulsanne Chicane", None, 6094.0),
        ("9", "Mulsanne Corner", RIGHT, 7743.0),
        ("10", "Indianapolis", RIGHT, 9700.0),
        ("11", "Indianapolis", LEFT, 9852.0),
        ("12", "Arnage", RIGHT, 10169.0),
        ("13", None, LEFT, 10780.0),
        ("14", "Porsche Curves", RIGHT, 11600.0),
        ("15", "Porsche Curves", LEFT, 11870.0),
        ("16", "Porsche Curves", RIGHT, 12260.0),
        ("17", "Karting", LEFT, 12440.0),
        ("18", "Ford Chicane", LEFT, 13259.0),
        ("19", "Ford Chicane", RIGHT, 13325.0),
        ("20", "Ford Chicane", LEFT, 13410.0),
        ("21", "Ford Chicane", RIGHT, 13470.0),
    ),
)

SEBRING = OfficialTrack(
    key="sebring",
    display_name="Sebring International Raceway",
    aliases=("sebring",),
    length_m=6019.0,
    turn_count=17,
    turns=_turns(
        ("1", None, None),
        ("2", None, RIGHT),
        ("3", None, None),
        ("4", None, RIGHT),
        ("5", None, None),
        ("6", "Big Bend", RIGHT),
        ("7", None, None),
        ("8", "Fangio", RIGHT),
        ("9", "Fangio", LEFT),
        ("10", None, None),
        ("11", "Collier", LEFT),
        ("12", None, RIGHT),
        ("13", "Tower", None),
        ("14", "Bishop", LEFT),
        ("15", "The S", None),
        ("16", "Le Mans", None),
        ("17", "Sunset Bend", None),
    ),
)

SILVERSTONE = OfficialTrack(
    key="silverstone",
    display_name="Silverstone Circuit",
    aliases=("silverstone",),
    length_m=5891.0,
    turn_count=18,
    turns=_turns(
        ("1", "Copse", RIGHT),
        ("2", "Maggotts", LEFT),
        ("3", "Becketts", None),
        ("4", "Becketts", None),
        ("5", "Becketts", None),
        ("6", "Chapel", LEFT),
        ("7", "Stowe", RIGHT),
        ("8", "Vale", None),
        ("9", "Vale", None),
        ("10", "Club", RIGHT),
        ("11", "Abbey", RIGHT),
        ("12", "Farm Curve", LEFT),
        ("13", "Village", RIGHT),
        ("14", "Loop", LEFT),
        ("15", "Aintree", LEFT),
        ("16", "Brooklands", None),
        ("17", "Luffield", RIGHT),
        ("18", "Woodcote", RIGHT),
    ),
)

COTA = OfficialTrack(
    key="cota",
    display_name="Circuit of the Americas",
    aliases=("americas", "cota"),
    length_m=5513.0,
    turn_count=20,
    turns=_turns(
        # Anchors read off a race lap's GPS heading. The esses (3-7) and the stadium
        # (16-18) are continuous arcs, so those positions are approximate.
        ("1", "Big Red", LEFT, 670.0),
        ("2", None, RIGHT, 850.0),
        ("3", None, LEFT, 1130.0),
        ("4", None, RIGHT, 1250.0),
        ("5", None, LEFT, 1340.0),
        ("6", None, RIGHT, 1520.0),
        ("7", None, LEFT, 1700.0),
        ("8", None, RIGHT, 1900.0),
        ("9", None, LEFT, 1950.0),
        ("10", None, LEFT, 2160.0),
        ("11", "The Bobby Pin", LEFT, 2575.0),
        ("12", None, LEFT, 3784.0),
        ("13", None, RIGHT, 4000.0),
        ("14", None, RIGHT, 4095.0),
        ("15", None, LEFT, 4275.0),
        ("16", "Stadium", RIGHT, 4450.0),
        ("17", "Stadium", RIGHT, 4600.0),
        ("18", "Stadium", RIGHT, 4760.0),
        ("19", None, LEFT, 5045.0),
        ("20", "The Andretti", LEFT, 5330.0),
    ),
)

IMOLA = OfficialTrack(
    key="imola",
    display_name="Autodromo Enzo e Dino Ferrari (Imola)",
    aliases=("imola", "enzo e dino ferrari"),
    length_m=4909.0,
    turn_count=19,
    turns=_turns(
        # Anchors read off one race lap's GPS heading, checked against the wiki's
        # directions (Tamburello L-R-L, Piratella L, T12 L, Rivazza L-L). Turns 1,
        # 8, 10, 13, 16 and 19 are flat-out kinks the wiki does not describe, so
        # they are the least certain.
        ("1", None, LEFT, 520.0),
        ("2", "Tamburello", LEFT, 680.0),
        ("3", "Tamburello", RIGHT, 760.0),
        ("4", "Tamburello", LEFT, 870.0),
        ("5", "Villeneuve", LEFT, 1305.0),
        ("6", "Villeneuve", RIGHT, 1400.0),
        ("7", "Tosa", LEFT, 1690.0),
        ("8", None, RIGHT, 2100.0),
        ("9", "Piratella", LEFT, 2330.0),
        ("10", None, RIGHT, 2720.0),
        ("11", "Acque Minerali", RIGHT, 2830.0),
        ("12", "Acque Minerali", LEFT, 2910.0),
        ("13", "Acque Minerali", RIGHT, 3100.0),
        ("14", "Variante Alta", RIGHT, 3349.0),
        ("15", "Variante Alta", LEFT, 3382.0),
        ("16", None, LEFT, 3560.0),
        ("17", "Rivazza", LEFT, 4117.0),
        ("18", "Rivazza", LEFT, 4247.0),
        ("19", None, RIGHT, 4600.0),
    ),
)

INTERLAGOS = OfficialTrack(
    key="interlagos",
    display_name="Autódromo José Carlos Pace (Interlagos)",
    aliases=("interlagos", "jose carlos pace"),
    length_m=4309.0,
    turn_count=15,
    turns=_turns(
        # Anchors read off a race lap's GPS heading. The wiki calls turn 3 a right;
        # the trace turns left there, and the trace wins. Turns 9 and 10 share one
        # arc and 13-15 are near-flat kinks, so those positions are approximate.
        ("1", "Senna S", LEFT, 386.0),
        ("2", "Senna S", RIGHT, 460.0),
        ("3", "Curva do Sol", LEFT, 640.0),
        ("4", "Descida do Lago", LEFT, 1430.0),
        ("5", None, LEFT, 1620.0),
        ("6", "Ferradura", RIGHT, 2110.0),
        ("7", "Ferradura", RIGHT, 2367.0),
        ("8", "Laranja", LEFT, 2490.0),
        ("9", "Pinheirinho", RIGHT, 2700.0),
        ("10", "Bico de Pato", RIGHT, 2776.0),
        ("11", "Mergulho", LEFT, 2900.0),
        ("12", "Junção", LEFT, 3258.0),
        ("13", None, LEFT, 3650.0),
        ("14", "Subida dos Boxes", LEFT, 3980.0),
        ("15", None, LEFT, 4150.0),
    ),
)

PAUL_RICARD = OfficialTrack(
    key="paul-ricard",
    display_name="Circuit Paul Ricard",
    aliases=("ricard", "paul ricard"),
    length_m=5842.0,
    turn_count=15,
    turns=_turns(
        ("1", "S de la Verrerie", RIGHT),
        ("2", "S de la Verrerie", LEFT),
        ("3", "Virage de l'Hôtel", RIGHT),
        ("4", "Virage de l'Hôtel", LEFT),
        ("5", "Virage du Camp", RIGHT),
        ("6", "Virage de la Ste Baume", RIGHT),
        ("7", None, LEFT),
        ("8", "Chicane Nord", LEFT),
        ("9", "Chicane Nord", RIGHT),
        ("10", "Courbe de Signes", RIGHT),
        ("11", "Double Droite du Beausset", RIGHT),
        ("12", "Virage de Bendor", LEFT),
        ("13", "Courbe du Garlaban", RIGHT),
        ("14", "Virage du Lac", LEFT),
        ("15", "Virage du Pont", RIGHT),
    ),
)

PORTIMAO = OfficialTrack(
    key="portimao",
    display_name="Autódromo Internacional do Algarve (Portimão)",
    aliases=("portimao", "algarve"),
    length_m=4653.0,
    turn_count=15,
    turns=_turns(
        # Anchors and directions read off a race lap's GPS heading.
        ("1", "Primeira Curva", RIGHT, 420.0),
        ("2", None, RIGHT, 560.0),
        ("3", "Lagos", RIGHT, 740.0),
        ("4", None, LEFT, 830.0),
        ("5", "Tore Vip", LEFT, 1460.0),
        ("6", None, LEFT, 1680.0),
        ("7", None, RIGHT, 1920.0),
        ("8", "Samsung Corner", RIGHT, 2075.0),
        ("9", "Craig Jones", LEFT, 2440.0),
        ("10", "Portimão Curve", RIGHT, 2690.0),
        ("11", "Portimão Curve", RIGHT, 2770.0),
        ("12", None, LEFT, 2940.0),
        ("13", None, LEFT, 3195.0),
        ("14", "Sagres", RIGHT, 3400.0),
        ("15", "Galp", RIGHT, 3840.0),
    ),
)

QATAR = OfficialTrack(
    key="qatar",
    display_name="Lusail International Circuit",
    aliases=("lusail", "qatar"),
    length_m=5419.0,
    turn_count=16,
    turns=_turns(
        ("1", None, RIGHT),
        ("2", None, LEFT),
        ("3", None, RIGHT),
        ("4", None, RIGHT),
        ("5", None, RIGHT),
        ("6", None, LEFT),
        ("7", None, RIGHT),
        ("8", None, LEFT),
        ("9", None, RIGHT),
        ("10", None, LEFT),
        ("11", None, LEFT),
        ("12", None, RIGHT),
        ("13", None, RIGHT),
        ("14", None, RIGHT),
        ("15", None, LEFT),
        ("16", None, RIGHT),
    ),
)

BAHRAIN = OfficialTrack(
    key="bahrain",
    display_name="Bahrain International Circuit",
    aliases=("bahrain international", "sakhir"),
    length_m=5412.0,
    turn_count=15,
    turns=_turns(
        # Anchors and directions read off a race lap's GPS heading. This is the
        # 5.4 km layout; the 3.5 km Outer Circuit is a different track.
        ("1", None, RIGHT, 740.0),
        ("2", None, LEFT, 810.0),
        ("3", None, RIGHT, 930.0),
        ("4", None, RIGHT, 1535.0),
        ("5", None, LEFT, 1700.0),
        ("6", None, RIGHT, 1900.0),
        ("7", None, LEFT, 2050.0),
        ("8", "Hairpin", RIGHT, 2254.0),
        ("9", None, LEFT, 2620.0),
        ("10", None, LEFT, 2710.0),
        ("11", None, LEFT, 3440.0),
        ("12", None, RIGHT, 3800.0),
        ("13", None, RIGHT, 4100.0),
        ("14", None, RIGHT, 4915.0),
        ("15", None, RIGHT, 5010.0),
    ),
)

TRACKS: tuple[OfficialTrack, ...] = (
    FUJI, MONZA, SPA, LE_MANS, SEBRING, SILVERSTONE, COTA, IMOLA,
    INTERLAGOS, PAUL_RICARD, PORTIMAO, QATAR, BAHRAIN,
)


def _words(text: str) -> str:
    """Lower-case, accent-free words of a name, joined by single spaces."""
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", plain.lower()))


def find_track(game_track_name: str | None) -> OfficialTrack | None:
    """The official circuit a game track name refers to, or None.

    Matched on whole words, because the game's names are long and varied -
    "Autodromo Nazionale Monza", "Circuit de Spa-Francorchamps" - and a bare
    substring would match "spa" inside an unrelated name.
    """
    if not game_track_name:
        return None
    padded = f" {_words(game_track_name)} "
    for track in TRACKS:
        if any(f" {_words(alias)} " in padded for alias in track.aliases):
            return track
    return None
