"""Reads the serial log of the ESP32-S3 equivalence test app run in the emulator.

SRS-036: the job libs-esp32s3 passes only if the log holds exactly one line
``SINUS-EQUIVALENCE-END pass`` and no other end line (architecture-m2.md 14.13). The results of
the check are the lines between ``SINUS-EQUIVALENCE-BEGIN`` and the end line; they are written to
the results file, whatever the outcome, when the block is complete.

Standard library only. Usage::

    python3 emulator_log.py <log> --results <file>

Exit status: 0 the check passed, 1 it did not (the reason is printed on standard error), 2 usage
error or unreadable log.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

BEGIN = "SINUS-EQUIVALENCE-BEGIN"
END = "SINUS-EQUIVALENCE-END"
OUTCOME_ROW = "| Outcome | pass |"

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_END_LINE = re.compile(rf"^{END}(?:\s+(\S*))?\s*$")


@dataclass(frozen=True)
class Analysis:
    """What the log shows."""

    passed: bool
    message: str  # why not, when not passed; "" otherwise
    results: str | None  # the block between the markers, when complete


def _lines(text: str) -> list[str]:
    """Lines of the log: CR LF or CR alone end a line; colour codes and edge blanks are dropped."""
    plain = _ANSI.sub("", text)
    return [line.strip() for line in plain.replace("\r\n", "\n").replace("\r", "\n").split("\n")]


def analyse(text: str) -> Analysis:
    """Decide the outcome from the text of a serial log (SRS-036)."""
    lines = _lines(text)
    begins = [i for i, line in enumerate(lines) if line == BEGIN]
    ends = [(i, m.group(1)) for i, line in enumerate(lines) if (m := _END_LINE.match(line))]

    results: str | None = None
    if len(begins) == 1 and len(ends) == 1 and begins[0] < ends[0][0]:
        results = "\n".join(lines[begins[0] + 1 : ends[0][0]]).strip("\n") + "\n"

    if not ends:
        return Analysis(
            False, f"no '{END}' line in the log (crash, timeout or failed self-check)", results
        )
    if len(ends) > 1:
        words = ", ".join(repr(word or "") for _, word in ends)
        return Analysis(
            False, f"{len(ends)} '{END}' lines in the log ({words}), exactly one expected", results
        )
    word = ends[0][1]
    if word != "pass":
        return Analysis(False, f"the end line says '{word or ''}', not 'pass'", results)
    if len(begins) != 1 or begins[0] > ends[0][0]:
        return Analysis(
            False, f"'{END} pass' without exactly one '{BEGIN}' line before it", results
        )
    assert results is not None
    if OUTCOME_ROW not in results.splitlines():
        return Analysis(
            False, f"'{END} pass' but the results do not state '{OUTCOME_ROW}'", results
        )
    return Analysis(True, "", results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the log of the ESP32-S3 equivalence run.")
    parser.add_argument("log", type=Path, help="serial log written by the emulator")
    parser.add_argument("--results", type=Path, required=True, help="file for the results block")
    args = parser.parse_args(argv)  # a usage error exits with status 2
    try:
        text = args.log.read_bytes().decode("utf-8", errors="replace")
    except OSError as error:
        print(f"cannot read the log: {error}", file=sys.stderr)
        return 2
    analysis = analyse(text)
    if analysis.results is not None:
        try:
            args.results.write_text(analysis.results, encoding="utf-8", newline="\n")
        except OSError as error:
            print(f"cannot write the results: {error}", file=sys.stderr)
            return 2
    if not analysis.passed:
        print(f"FAIL: {analysis.message}", file=sys.stderr)
        return 1
    print(f"pass: {args.results}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
