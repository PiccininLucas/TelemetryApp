"""Produce the anonymised demo session that ships with the repository.

    python scripts/make_demo_dataset.py "path/to/session.duckdb" [--out DIR]

Writes a **new** file. The recorded session is opened read-only and is never
modified - it is the only copy of a session that will never happen again.

Only the anonymised file is ever committed; `.gitignore` keeps raw `.duckdb`
files out of the repository regardless.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lmu_telemetry.core.errors import TelemetryError  # noqa: E402
from lmu_telemetry.export import anonymise  # noqa: E402
from lmu_telemetry.logging_config import setup_logging  # noqa: E402
from lmu_telemetry.ui import strings  # noqa: E402

DEFAULT_OUTPUT = Path("data/demo")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Recorded session file")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Output directory (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--name", type=str, default=None,
                        help="Output file name (default: the source's)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite the output if it exists")
    arguments = parser.parse_args(argv)

    setup_logging()

    destination = arguments.out / (arguments.name or arguments.source.name)

    print(strings.ANON_TITLE)
    print("=" * len(strings.ANON_TITLE))
    print(f"{strings.ANON_SOURCE:<12} {arguments.source}")
    print(f"{strings.ANON_DESTINATION:<12} {destination}")
    print()

    try:
        report = anonymise.anonymise_session(
            arguments.source, destination, force=arguments.force
        )
    except TelemetryError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    for key, (before, after) in sorted(report.replaced.items()):
        print("  " + strings.ANON_FIELD_REPLACED.format(
            key=key, before=before, after=after
        ))
    if report.cells_scrubbed:
        print("  " + strings.ANON_CELLS_SCRUBBED.format(n=report.cells_scrubbed))
    else:
        print("  " + strings.ANON_NOTHING_FOUND)

    # Re-open the written file and look again. Verifying the artefact rather
    # than trusting the writer is the only check that means anything before
    # publishing one.
    findings = anonymise.verify(destination, report.residues)
    if findings:
        print("\nFALHA NA VERIFICAÇÃO:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    print()
    print(strings.ANON_DONE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
