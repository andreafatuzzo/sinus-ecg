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
    is rejected with it too. It is also raised for a design argument outside its range
    (architecture §8.6).
    """


class DataVerificationError(SinusError):
    """A database, or the requested records of it, is not verified (architecture §8.3).

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
    """A file does not follow its format (architecture §7.3, §8.3, §8.4, §8.11).

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

    Attributes:
        differences: One entry per differing line.

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

    Attributes:
        input_id: Identifier of the input whose output is not finite.

    The message is ``<input_id>: output contains a value that is not finite``.
    """

    input_id: str

    def __init__(self, input_id: str) -> None:
        self.input_id = input_id
        super().__init__(f"{input_id}: output contains a value that is not finite")
