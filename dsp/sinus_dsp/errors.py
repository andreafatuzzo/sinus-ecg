"""Exception hierarchy of Sinus (architecture §8.2).

Every error that the software raises on purpose derives from :class:`SinusError`, and there
is one class per error behaviour. The message of every error is deterministic and names what
failed. Errors of the standard library or of third-party packages, for conditions that the
software does not check itself, propagate unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable


class SinusError(Exception):
    """Base class of every Sinus error.

    It is never raised directly; it lets a caller catch every Sinus error.
    """


class InvalidInputError(SinusError, ValueError):
    """An input or an argument is rejected.

    SRS-003: a signal or a sampling frequency that fails the input checks is rejected with
    this error, and nothing is returned. SRS-005: a mains frequency other than 50 Hz or 60 Hz
    is rejected with it too. SRS-002: a channel that the record does not have, and signal
    units other than mV, are rejected with it. It is also raised for a design argument
    outside its range (architecture §8.6), for an invalid record name or an empty record
    selection (architecture §8.3), for samples out of order or a negative window or start
    given to the matching (architecture §8.8), for invalid counts or duplicate record names
    given to the statistics (architecture §8.9), and by the evaluation run and the report
    rendering (architecture §8.10): record names given as a string, invalid or given twice;
    a record loaded with a channel other than that of the settings; invalid counts or target
    in the comparison with a target; evaluations without records 118 and 119 exactly once
    for the noise stress comparison; a name that is not a noise stress record name; results
    of the wrong kind given to a report renderer. In the golden-vector export (architecture
    §8.12) it is raised for a sampling frequency, heart rate or variant that the synthetic
    generator does not list, an input identifier, source or parameters or reference beats
    that are rejected, a golden vector that cannot be written as a valid file, an invalid or
    empty record selection, and a record shorter than its 60 s segment.
    """


class DataVerificationError(SinusError):
    """A database, or the requested records of it, is not verified (architecture §8.3).

    SRS-001, SRS-013: a database with a listed file that is missing or whose SHA-256 differs
    is reported as not verified with this error, which names each such file. It is also
    raised when the checksum list itself is missing or differs from its pinned digest.
    SRS-012, SRS-014: the command that writes the validation report raises it, before
    anything is written, when either database is not verified (architecture §8.10).
    SRS-016: the subset check raises it, before any report is rendered or written, when a
    file of the subset records is not verified (architecture §8.11). The golden-vector export
    does not raise it: it skips the record segments and states the reason (architecture
    §8.12).

    Attributes:
        database: Name and version of the database, e.g. ``mitdb 1.0.0``.
        missing: Relative paths of the listed files that are missing, sorted in code-point
            order.
        mismatched: Relative paths of the files whose SHA-256 differs, sorted in code-point
            order.

    The message is ``<database> not verified: missing: <a>, <b>; checksum mismatch: <c>``,
    where a part is omitted when it is empty.
    """

    database: str
    missing: tuple[str, ...]
    mismatched: tuple[str, ...]

    def __init__(
        self,
        database: str,
        missing: Iterable[str] = (),
        mismatched: Iterable[str] = (),
    ) -> None:
        self.database = database
        self.missing = tuple(sorted(missing))
        self.mismatched = tuple(sorted(mismatched))
        parts: list[str] = []
        if self.missing:
            parts.append("missing: " + ", ".join(self.missing))
        if self.mismatched:
            parts.append("checksum mismatch: " + ", ".join(self.mismatched))
        message = f"{database} not verified"
        if parts:
            message += ": " + "; ".join(parts)
        super().__init__(message)


class MalformedFileError(SinusError, ValueError):
    """A file does not follow its format (architecture §7.3, §8.3, §8.4, §8.10, §8.11).

    SRS-001: a checksum list with a line that is not an entry, an unsafe path, a duplicate
    path or no entry is rejected with this error. SRS-002: so is an annotation file whose
    sample indices decrease. SRS-016: so is a stored subset report that is not UTF-8 text
    (architecture §8.11). SRS-015: so is a golden-vector file that a reader rejects,
    including one that is not UTF-8 text (architecture §7.3, §8.12); the line is that of the
    first rule broken. It is also raised for a record list ``RECORDS`` that is not UTF-8
    text, names an invalid record or a record twice, or names none (architecture §8.10).

    Attributes:
        path: The file, or the name of the source of the text.
        line: 1-based number of the offending line, or ``None`` when no line applies.
        reason: What is wrong.

    The message is ``<path>, line <line>: <reason>``, or ``<path>: <reason>`` without a line.
    """

    path: str
    line: int | None
    reason: str

    def __init__(self, path: str, line: int | None, reason: str) -> None:
        self.path = path
        self.line = line
        self.reason = reason
        where = path if line is None else f"{path}, line {line}"
        super().__init__(f"{where}: {reason}")


class SubsetReportMismatchError(SinusError):
    """The regenerated subset report differs from the stored one (architecture §8.11).

    SRS-016: any difference between the subset report regenerated in continuous integration
    and the stored one fails the check, and the differences are named.

    Attributes:
        differences: One entry per differing line (at most 20, then the number of the
            others), or one entry naming a stored report that does not exist.

    The message is ``subset report differs from the stored report:`` followed by one
    difference per line.
    """

    differences: tuple[str, ...]

    def __init__(self, differences: Iterable[str]) -> None:
        self.differences = tuple(differences)
        message = "subset report differs from the stored report"
        if self.differences:
            message += ":\n" + "\n".join(self.differences)
        super().__init__(message)


class NonFiniteOutputError(SinusError):
    """The golden-vector export found a value that is not finite (architecture §7.3).

    SRS-015: a golden-vector file never holds a value that is not finite; the export fails
    with this error, naming the input, instead. With the inputs of the golden-vector set
    this cannot happen. Since the input check rejects every sample beyond 1000 mV
    (architecture §13.2; OP-063), no accepted input can produce such a value: the check
    stays as a guard of the file format.

    Attributes:
        input_id: Identifier of the input whose output is not finite.

    The message is ``<input_id>: output contains a value that is not finite``.
    """

    input_id: str

    def __init__(self, input_id: str) -> None:
        self.input_id = input_id
        super().__init__(f"{input_id}: output contains a value that is not finite")
