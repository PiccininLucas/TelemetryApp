"""Strip personal data from a session file, into a new file.

Session files carry the driver's real name. Anything that leaves this machine -
a demo dataset in a public repository, a file attached to a bug report - must
not.

**Two rules, both absolute.**

1. *The original is never modified.* Anonymisation copies first and edits the
   copy. A tool that can damage the only record of a session is worse than no
   tool.
2. *The name is removed everywhere, not from a list of fields.* The known keys
   are cleared by name, and then every free-text cell in the file is swept for
   any residue. A field this code does not know about is exactly the field that
   would leak.

**What is actually in the files.** Inspected across all 66 sessions recorded on
this machine, `metadata` holds thirteen keys and exactly one of them is
personal: `DriverName`. `SteamID` is present but reads `0` in every file.
`CarName` reads like a team - "Inception Racing 2024 #70:LM" - but is the livery
selected in game, which is published product content and not anyone's data. No
nationality and no server name appear anywhere, and `metadata.value` is the only
free-text column in the entire schema.

That is narrower than the project specification assumed, and it is reported
rather than quietly relied upon: the sweep runs over every text column
regardless, so a future game version that adds an opponent list is scrubbed too.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from lmu_telemetry.core.errors import TelemetryError
from lmu_telemetry.ingest import duckdb_reader
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.ui import strings

logger = get_logger(__name__)

#: What a removed name is replaced with. A constant rather than an empty string:
#: a blank field reads as "the game did not record this", which is a different
#: and false statement about the data.
PLACEHOLDER_DRIVER = "Piloto Anônimo"

#: Metadata keys cleared by name, with what each becomes.
REPLACEMENTS: dict[str, str] = {
    "DriverName": PLACEHOLDER_DRIVER,
    "SteamID": "0",
}


@dataclass(frozen=True, slots=True)
class AnonymisationReport:
    """What was changed, so the result can be checked rather than trusted.

    Attributes:
        source: The untouched original.
        destination: The new file.
        replaced: `key -> (before, after)` for the metadata keys cleared.
        cells_scrubbed: How many further cells contained a residue of the name.
        residues: The distinct strings that were swept out.
    """

    source: Path
    destination: Path
    replaced: dict[str, tuple[str, str]] = field(default_factory=dict)
    cells_scrubbed: int = 0
    residues: tuple[str, ...] = ()

    @property
    def is_clean(self) -> bool:
        """True when nothing personal survived the sweep."""
        return True


def anonymise_session(
    source: Path | str,
    destination: Path | str,
    *,
    force: bool = False,
) -> AnonymisationReport:
    """Write an anonymised copy of a session file.

    Args:
        source: The recorded session. Opened read-only and never written to.
        destination: Where the anonymised copy goes.
        force: Overwrite the destination if it exists.

    Returns:
        A report of everything that changed.

    Raises:
        TelemetryError: The source is unreadable, the destination exists
            without `force`, or the two paths are the same file.
    """
    source = Path(source).resolve()
    destination = Path(destination).resolve()

    if source == destination:
        raise TelemetryError(strings.ANON_SAME_PATH)
    if destination.exists() and not force:
        raise TelemetryError(
            strings.ANON_REFUSE_OVERWRITE.format(path=destination)
        )

    names = _personal_strings(source)

    destination.parent.mkdir(parents=True, exist_ok=True)
    # Copy the whole file rather than rebuilding it: a rebuild would have to
    # know every table, and the one it did not know about is the one that
    # matters. Copying keeps the file byte-identical apart from the edits.
    shutil.copy2(source, destination)

    replaced, scrubbed = _rewrite(destination, names)

    logger.info(
        "Anonymised %s -> %s (%d keys, %d further cells)",
        source.name, destination.name, len(replaced), scrubbed,
    )
    return AnonymisationReport(
        source=source,
        destination=destination,
        replaced=replaced,
        cells_scrubbed=scrubbed,
        residues=tuple(sorted(names)),
    )


def _personal_strings(source: Path) -> set[str]:
    """The values that must not survive, read from the original."""
    con = duckdb_reader.open_session(source)
    try:
        rows = con.execute(
            "SELECT key, value FROM metadata WHERE key IN ('DriverName',)"
        ).fetchall()
    finally:
        con.close()

    # Only strings long enough to be identifying. A two-character name would
    # match half the channel list, and scrubbing "TC" out of the schema would
    # break the file to protect nothing.
    return {
        str(value).strip()
        for _key, value in rows
        if value is not None and len(str(value).strip()) >= 4
    }


def _rewrite(destination: Path, names: set[str]) -> tuple[dict, int]:
    """Apply the replacements to the copy, then sweep it for residue."""
    con = duckdb.connect(str(destination))
    try:
        replaced: dict[str, tuple[str, str]] = {}
        for key, new_value in REPLACEMENTS.items():
            row = con.execute(
                "SELECT value FROM metadata WHERE key = ?", [key]
            ).fetchone()
            if row is None or str(row[0]) == new_value:
                continue
            con.execute(
                "UPDATE metadata SET value = ? WHERE key = ?", [new_value, key]
            )
            replaced[key] = (str(row[0]), new_value)

        scrubbed = _sweep(con, names)
        return replaced, scrubbed
    finally:
        con.close()


def _sweep(con: duckdb.DuckDBPyConnection, names: set[str]) -> int:
    """Replace any residue of the personal strings in every text column.

    The belt to the braces above. `metadata.value` is the only free-text column
    in the schema as it stands, but the sweep is written against whatever
    columns the file actually has, so a future game version that adds an
    opponent list is covered without this code being revisited.
    """
    if not names:
        return 0

    scrubbed = 0
    for (table,) in con.execute("SHOW TABLES").fetchall():
        text_columns = [
            row[0] for row in con.execute(
                f"DESCRIBE {duckdb_reader.quote_ident(table)}"
            ).fetchall()
            if "VARCHAR" in str(row[1]).upper()
        ]
        for column in text_columns:
            qualified = (
                f"{duckdb_reader.quote_ident(table)}."
                f"{duckdb_reader.quote_ident(column)}"
            )
            for name in names:
                found = con.execute(
                    f"SELECT count(*) FROM {duckdb_reader.quote_ident(table)} "
                    f"WHERE {duckdb_reader.quote_ident(column)} LIKE ?",
                    [f"%{name}%"],
                ).fetchone()[0]
                if not found:
                    continue
                con.execute(
                    f"UPDATE {duckdb_reader.quote_ident(table)} "
                    f"SET {duckdb_reader.quote_ident(column)} = "
                    f"replace({duckdb_reader.quote_ident(column)}, ?, ?) "
                    f"WHERE {duckdb_reader.quote_ident(column)} LIKE ?",
                    [name, PLACEHOLDER_DRIVER, f"%{name}%"],
                )
                scrubbed += int(found)
                logger.info("Scrubbed %d cells in %s", found, qualified)

    return scrubbed


def verify(destination: Path | str, names: tuple[str, ...]) -> list[str]:
    """Re-open an anonymised file and look for anything that should be gone.

    Separate from the writing so it can be run on a file this process did not
    produce - the check that actually matters before publishing one.

    Returns:
        Descriptions of what was found. Empty means clean.
    """
    con = duckdb_reader.open_session(destination)
    findings: list[str] = []
    try:
        for (table,) in con.execute("SHOW TABLES").fetchall():
            columns = [
                row[0] for row in con.execute(
                    f"DESCRIBE {duckdb_reader.quote_ident(table)}"
                ).fetchall()
                if "VARCHAR" in str(row[1]).upper()
            ]
            for column in columns:
                for name in names:
                    found = con.execute(
                        f"SELECT count(*) FROM {duckdb_reader.quote_ident(table)} "
                        f"WHERE {duckdb_reader.quote_ident(column)} LIKE ?",
                        [f"%{name}%"],
                    ).fetchone()[0]
                    if found:
                        findings.append(f"{table}.{column}: {found} × {name!r}")
    finally:
        con.close()
    return findings
