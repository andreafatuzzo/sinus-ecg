"""Unit tests of the exception hierarchy: bases, attributes and message formats."""

import pytest

from sinus_dsp.errors import (
    DataVerificationError,
    InvalidInputError,
    MalformedFileError,
    NonFiniteOutputError,
    SinusError,
    SubsetReportMismatchError,
)


def test_sinus_error_is_an_exception_only() -> None:
    assert SinusError.__bases__ == (Exception,)


@pytest.mark.parametrize(
    ("cls", "bases"),
    [
        (InvalidInputError, (SinusError, ValueError)),
        (DataVerificationError, (SinusError,)),
        (MalformedFileError, (SinusError, ValueError)),
        (SubsetReportMismatchError, (SinusError,)),
        (NonFiniteOutputError, (SinusError,)),
    ],
)
def test_bases(cls: type[Exception], bases: tuple[type, ...]) -> None:
    assert cls.__bases__ == bases


def test_only_input_and_format_errors_are_value_errors() -> None:
    assert issubclass(InvalidInputError, ValueError)
    assert issubclass(MalformedFileError, ValueError)
    assert not issubclass(DataVerificationError, ValueError)
    assert not issubclass(SubsetReportMismatchError, ValueError)
    assert not issubclass(NonFiniteOutputError, ValueError)


def test_invalid_input_error_keeps_its_message() -> None:
    error = InvalidInputError("sampling frequency is not finite: nan")
    assert str(error) == "sampling frequency is not finite: nan"
    with pytest.raises(SinusError):
        raise error


def test_data_verification_error_both_parts() -> None:
    error = DataVerificationError("mitdb 1.0.0", missing=("b.dat", "a.hea"), mismatched=["100.atr"])
    assert error.database == "mitdb 1.0.0"
    assert error.missing == ("a.hea", "b.dat")
    assert error.mismatched == ("100.atr",)
    assert (
        str(error) == "mitdb 1.0.0 not verified: missing: a.hea, b.dat; checksum mismatch: 100.atr"
    )


def test_data_verification_error_missing_only() -> None:
    error = DataVerificationError("nstdb 1.0.0", missing=("SHA256SUMS.txt",))
    assert error.mismatched == ()
    assert str(error) == "nstdb 1.0.0 not verified: missing: SHA256SUMS.txt"


def test_data_verification_error_mismatch_only() -> None:
    error = DataVerificationError("mitdb 1.0.0", mismatched=("100.dat", "100.atr"))
    assert error.missing == ()
    assert error.mismatched == ("100.atr", "100.dat")
    assert str(error) == "mitdb 1.0.0 not verified: checksum mismatch: 100.atr, 100.dat"


def test_data_verification_error_without_files() -> None:
    assert str(DataVerificationError("mitdb 1.0.0")) == "mitdb 1.0.0 not verified"


def test_data_verification_error_sorts_in_code_point_order() -> None:
    error = DataVerificationError("mitdb 1.0.0", missing=("b", "B", "a", "10", "9", "é"))
    assert error.missing == ("10", "9", "B", "a", "b", "é")


def test_malformed_file_error_with_line() -> None:
    error = MalformedFileError("SHA256SUMS.txt", 3, "not a checksum entry")
    assert (error.path, error.line, error.reason) == ("SHA256SUMS.txt", 3, "not a checksum entry")
    assert str(error) == "SHA256SUMS.txt, line 3: not a checksum entry"


def test_malformed_file_error_without_line() -> None:
    error = MalformedFileError("report.md", None, "not UTF-8 text")
    assert error.line is None
    assert str(error) == "report.md: not UTF-8 text"


def test_subset_report_mismatch_error() -> None:
    differences = ["line 4: stored a, regenerated b", "line 9: stored c, regenerated d"]
    error = SubsetReportMismatchError(differences)
    assert error.differences == tuple(differences)
    assert str(error) == (
        "subset report differs from the stored report:\n"
        "line 4: stored a, regenerated b\n"
        "line 9: stored c, regenerated d"
    )


def test_non_finite_output_error() -> None:
    error = NonFiniteOutputError("syn-fs360-hr075-clean")
    assert error.input_id == "syn-fs360-hr075-clean"
    assert str(error) == "syn-fs360-hr075-clean: output contains a value that is not finite"


def test_messages_are_deterministic() -> None:
    first = DataVerificationError("mitdb 1.0.0", missing={"b", "a", "c"}, mismatched={"z", "y"})
    second = DataVerificationError("mitdb 1.0.0", missing={"c", "a", "b"}, mismatched={"y", "z"})
    assert str(first) == str(second)
