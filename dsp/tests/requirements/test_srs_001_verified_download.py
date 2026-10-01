"""Requirement tests of SRS-001: verified download of the reference database (RC-004).

No test uses the network. A fixture folder holds a few files named like those of the MIT-BIH
Arrhythmia Database (records, a documentation subfolder, a second subfolder) and their
checksum list `SHA256SUMS.txt`; the `Database` under test pins the SHA-256 of that list, as
the software pins the list that PhysioNet publishes. The download is exercised with a fetch
function that serves bytes from a dictionary and raises `OSError` for anything else. A
fixture makes any real network access fail the test.

Pass criteria (SRS-001): an intact set is reported as verified; a set with a missing file or
a file whose checksum does not match is reported as not verified, with an error naming each
such file. The same holds when the checksum list itself is missing or altered, since no file
can then be verified against the published list.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sinus_dsp.data.physionet import (
    MITDB,
    Database,
    describe_verification,
    download_database,
    parse_checksum_list,
    select_files,
    verify_database,
)
from sinus_dsp.errors import DataVerificationError, MalformedFileError, SinusError

pytestmark = pytest.mark.usefixtures("forbid_network")

SLUG = "mitdb"
VERSION = "1.0.0"
TITLE = "MIT-BIH Arrhythmia Database"
BASE_URL = "https://physionet.org/files/mitdb/1.0.0/"
LIST_NAME = "SHA256SUMS.txt"

# SHA-256 of the checksum list of version 1.0.0, as pinned in docs/regulatory/architecture.md.
MITDB_LIST_SHA256 = "b61158a96d5f2ca80edfb354a9a66a6324836c390a84e1966dcee2b907d6be43"

# A small database with the structure of the real one: relative path -> content.
FILES: dict[str, bytes] = {
    "100.atr": b"annotations of record 100\n",
    "100.dat": bytes(range(256)) * 16,
    "100.hea": b"100 2 360 650000\n100.dat 212 200 11 1024 995 -22131 0 MLII\n",
    "100.xws": b"setup of record 100\n",
    "101.atr": b"annotations of record 101\n",
    "101.dat": bytes(reversed(range(256))) * 16,
    "101.hea": b"101 2 360 650000\n101.dat 212 200 11 1024 955 29832 0 MLII\n",
    "ANNOTATORS": b"atr\treference beat, rhythm, and signal quality annotations\n",
    "RECORDS": b"100\n101\n",
    "mitdbdir/intro.htm": b"<html><body>Introduction</body></html>\n",
    "mitdbdir/samples/10000.ps": b"%!PS-Adobe-2.0\n",
    "x_mitdb/x_108.dat": b"\x00\x01\x02\x03" * 100,
}
ALL_FILES = tuple(sorted(FILES))


def _database(pinned_sha256: str) -> Database:
    """A database description with the MIT-BIH identity and the given pinned list digest."""
    return Database(slug=SLUG, version=VERSION, title=TITLE, checksum_list_sha256=pinned_sha256)


def _file(folder: Path, relative: str) -> Path:
    return folder.joinpath(*relative.split("/"))


def _snapshot(folder: Path) -> dict[str, bytes]:
    """Every file under ``folder``: relative path with ``/`` -> content."""
    if not folder.is_dir():
        return {}
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _flip_one_bit(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))


def _served(files: dict[str, bytes], checksum_list: bytes) -> dict[str, bytes]:
    """What PhysioNet would serve for the database: URL -> content."""
    served = {BASE_URL + path: content for path, content in files.items()}
    served[BASE_URL + LIST_NAME] = checksum_list
    return served


@pytest.fixture
def intact(tmp_path: Path, write_database_folder: Callable[..., Any]) -> Any:
    """The fixture database, complete and unaltered, in ``tmp_path / "data" / "mitdb"``."""
    return write_database_folder(tmp_path / "data", SLUG, FILES)


# --------------------------------------------------------------------------------------------
# The reference database and its version
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-001")
def test_reference_database_is_version_1_0_0_of_the_mit_bih_arrhythmia_database() -> None:
    """The database that the software obtains and verifies.

    Input: the database description of the software for the reference database.
    Expected: the MIT-BIH Arrhythmia Database (PhysioNet name `mitdb`), version 1.0.0, with
    the SHA-256 of the checksum list of that version pinned as 64 lowercase hexadecimal
    digits, equal to the documented digest.
    """
    assert MITDB.slug == "mitdb"
    assert MITDB.version == "1.0.0"
    assert MITDB.title == "MIT-BIH Arrhythmia Database"
    assert MITDB.checksum_list_sha256 == MITDB_LIST_SHA256


@pytest.mark.requirement("SRS-001")
def test_reference_database_is_not_verified_when_nothing_was_downloaded(tmp_path: Path) -> None:
    """The real database description on an empty data directory.

    Input: the reference database of the software and a data directory without it.
    Expected: not verified: an error that names the database `mitdb 1.0.0` and the missing
    checksum list `SHA256SUMS.txt`.
    """
    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(MITDB, tmp_path)

    assert excinfo.value.database == "mitdb 1.0.0"
    assert excinfo.value.missing == (LIST_NAME,)
    assert excinfo.value.mismatched == ()


# --------------------------------------------------------------------------------------------
# Verification of a local copy
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-001")
def test_intact_set_is_reported_as_verified(intact: Any) -> None:
    """The first verification case of SRS-001: an intact set.

    Input: the fixture folder with its 12 files, unaltered, and the checksum list whose
    SHA-256 is pinned in the database description.
    Expected: no error; the result names the database, covers the whole database and lists
    the 12 verified files (every file of the checksum list, files in subfolders included);
    the folder is left unchanged.
    """
    database = _database(intact.checksum_list_sha256)
    before = _snapshot(intact.folder)

    result = verify_database(database, intact.data_root)

    assert result.database == database
    assert result.records is None
    assert tuple(result.files) == ALL_FILES
    assert _snapshot(intact.folder) == before


@pytest.mark.requirement("SRS-001")
def test_verified_set_is_described_as_verified(intact: Any) -> None:
    """The outcome of a successful verification, as text.

    Input: the result of verifying the intact fixture folder.
    Expected: the text `verified: 12 files match the published SHA-256 checksum list
    (SHA256SUMS.txt, SHA-256 <digest of the list>)`.
    """
    result = verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert describe_verification(result) == (
        "verified: 12 files match the published SHA-256 checksum list "
        f"(SHA256SUMS.txt, SHA-256 {intact.checksum_list_sha256})"
    )


@pytest.mark.requirement("SRS-001")
def test_one_altered_and_one_missing_file_are_both_named(intact: Any) -> None:
    """The second verification case of SRS-001: one altered and one missing file.

    Input: the fixture folder with one bit changed in `100.dat` and `101.atr` deleted.
    Expected: not verified: an error for the database `mitdb 1.0.0` whose missing files are
    exactly `101.atr` and whose mismatched files are exactly `100.dat`; the message names
    both files, in the documented form. The verification changes nothing in the folder.
    """
    _flip_one_bit(_file(intact.folder, "100.dat"))
    _file(intact.folder, "101.atr").unlink()
    before = _snapshot(intact.folder)

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    error = excinfo.value
    assert isinstance(error, SinusError)
    assert error.database == "mitdb 1.0.0"
    assert error.missing == ("101.atr",)
    assert error.mismatched == ("100.dat",)
    assert str(error) == "mitdb 1.0.0 not verified: missing: 101.atr; checksum mismatch: 100.dat"
    assert _snapshot(intact.folder) == before


@pytest.mark.requirement("SRS-001")
@pytest.mark.parametrize("name", ALL_FILES)
def test_any_altered_file_is_named(intact: Any, name: str) -> None:
    """Every listed file is verified: an alteration of any one of them is found.

    Input: the fixture folder with one bit changed in one file, for each of the 12 files
    in turn.
    Expected: not verified; the error names exactly that file as mismatched, no file as
    missing, and the message contains its name.
    """
    _flip_one_bit(_file(intact.folder, name))

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert excinfo.value.mismatched == (name,)
    assert excinfo.value.missing == ()
    assert name in str(excinfo.value)


@pytest.mark.requirement("SRS-001")
@pytest.mark.parametrize("name", ALL_FILES)
def test_any_missing_file_is_named(intact: Any, name: str) -> None:
    """Every listed file is verified: the absence of any one of them is found.

    Input: the fixture folder with one file deleted, for each of the 12 files in turn.
    Expected: not verified; the error names exactly that file as missing, no file as
    mismatched, and the message contains its name.
    """
    _file(intact.folder, name).unlink()

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert excinfo.value.missing == (name,)
    assert excinfo.value.mismatched == ()
    assert name in str(excinfo.value)


@pytest.mark.requirement("SRS-001")
@pytest.mark.parametrize(
    "alter",
    [
        pytest.param(lambda data: data[:-1], id="last-byte-removed"),
        pytest.param(lambda data: data + b"\x00", id="one-byte-appended"),
        pytest.param(lambda data: b"", id="emptied"),
        pytest.param(lambda data: data[1:] + data[:1], id="bytes-rotated"),
        pytest.param(lambda data: FILES["101.dat"], id="content-of-another-listed-file"),
    ],
)
def test_any_kind_of_alteration_is_a_mismatch(intact: Any, alter: Callable[[bytes], bytes]) -> None:
    """A file whose content differs in any way does not match its checksum.

    Input: the fixture folder with `100.dat` shortened by one byte, extended by one byte,
    emptied, with its bytes rotated, or replaced by the content of `101.dat`.
    Expected: not verified; the error names `100.dat` as mismatched (an empty file is a
    mismatch, not a missing file).
    """
    target = _file(intact.folder, "100.dat")
    target.write_bytes(alter(target.read_bytes()))

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert excinfo.value.mismatched == ("100.dat",)
    assert excinfo.value.missing == ()


@pytest.mark.requirement("SRS-001")
def test_every_altered_and_every_missing_file_is_named(intact: Any) -> None:
    """Several altered and several missing files: the error names each of them.

    Input: the fixture folder with `mitdbdir/intro.htm`, `100.atr` and `RECORDS` altered,
    and `x_mitdb/x_108.dat`, `101.hea` and `100.hea` deleted.
    Expected: not verified; the missing files and the mismatched files are complete, each
    list in code-point order, with the relative path of the files in subfolders; the message
    lists them all in the documented form.
    """
    for name in ("mitdbdir/intro.htm", "100.atr", "RECORDS"):
        _flip_one_bit(_file(intact.folder, name))
    for name in ("x_mitdb/x_108.dat", "101.hea", "100.hea"):
        _file(intact.folder, name).unlink()

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert excinfo.value.missing == ("100.hea", "101.hea", "x_mitdb/x_108.dat")
    assert excinfo.value.mismatched == ("100.atr", "RECORDS", "mitdbdir/intro.htm")
    assert str(excinfo.value) == (
        "mitdb 1.0.0 not verified: missing: 100.hea, 101.hea, x_mitdb/x_108.dat; "
        "checksum mismatch: 100.atr, RECORDS, mitdbdir/intro.htm"
    )


@pytest.mark.requirement("SRS-001")
def test_message_with_missing_files_only(intact: Any) -> None:
    """The error message when no file is altered.

    Input: the fixture folder with `RECORDS` and `100.xws` deleted.
    Expected: the message `mitdb 1.0.0 not verified: missing: 100.xws, RECORDS`, without a
    checksum-mismatch part.
    """
    for name in ("RECORDS", "100.xws"):
        _file(intact.folder, name).unlink()

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert str(excinfo.value) == "mitdb 1.0.0 not verified: missing: 100.xws, RECORDS"


@pytest.mark.requirement("SRS-001")
def test_message_with_mismatched_files_only(intact: Any) -> None:
    """The error message when no file is missing.

    Input: the fixture folder with `101.dat` altered.
    Expected: the message `mitdb 1.0.0 not verified: checksum mismatch: 101.dat`, without a
    missing part.
    """
    _flip_one_bit(_file(intact.folder, "101.dat"))

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert str(excinfo.value) == "mitdb 1.0.0 not verified: checksum mismatch: 101.dat"


@pytest.mark.requirement("SRS-001")
def test_all_files_missing_are_all_named(
    tmp_path: Path, write_database_folder: Callable[..., Any]
) -> None:
    """A folder that holds the checksum list and nothing else.

    Input: the checksum list of the fixture database, without any of its 12 files.
    Expected: not verified; the error names the 12 files as missing, in code-point order.
    """
    folder = write_database_folder(tmp_path, SLUG, FILES, with_files=False)

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(folder.checksum_list_sha256), folder.data_root)

    assert excinfo.value.missing == ALL_FILES
    assert excinfo.value.mismatched == ()


@pytest.mark.requirement("SRS-001")
def test_folder_in_place_of_a_file_is_a_missing_file(intact: Any) -> None:
    """A listed path that exists but is not a file.

    Input: the fixture folder with `100.hea` replaced by a folder of the same name.
    Expected: not verified; the error names `100.hea` as missing.
    """
    target = _file(intact.folder, "100.hea")
    target.unlink()
    target.mkdir()

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert excinfo.value.missing == ("100.hea",)
    assert excinfo.value.mismatched == ()


# --------------------------------------------------------------------------------------------
# The checksum list itself
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-001")
def test_missing_checksum_list_is_named(
    tmp_path: Path, write_database_folder: Callable[..., Any]
) -> None:
    """The files are present but the checksum list is not.

    Input: the fixture folder with its 12 intact files and no `SHA256SUMS.txt`.
    Expected: not verified; the error names `SHA256SUMS.txt` as missing, and its message
    contains that name.
    """
    folder = write_database_folder(tmp_path, SLUG, FILES, with_list=False)

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(folder.checksum_list_sha256), folder.data_root)

    assert excinfo.value.database == "mitdb 1.0.0"
    assert excinfo.value.missing == (LIST_NAME,)
    assert excinfo.value.mismatched == ()
    assert str(excinfo.value) == "mitdb 1.0.0 not verified: missing: SHA256SUMS.txt"


@pytest.mark.requirement("SRS-001")
@pytest.mark.parametrize(
    "alter",
    [
        pytest.param(lambda text: text.replace("0", "1", 1), id="one-digit-changed"),
        pytest.param(lambda text: text.split("\n", 1)[1], id="first-line-removed"),
        pytest.param(lambda text: text + "0" * 64 + " extra.dat\n", id="line-added"),
        pytest.param(lambda text: text.replace("100.dat", "100.dax"), id="name-changed"),
        pytest.param(lambda text: text + "\n", id="empty-line-appended"),
        pytest.param(lambda text: text.upper(), id="upper-case"),
        pytest.param(lambda text: "", id="emptied"),
    ],
)
def test_altered_checksum_list_is_named(intact: Any, alter: Callable[[str], str]) -> None:
    """A checksum list that differs from the published one.

    Input: the fixture folder with its 12 intact files and a `SHA256SUMS.txt` that differs
    from the list whose SHA-256 is pinned: one digit changed, a line removed, a line added,
    a file name changed, an empty line appended, upper case, or empty.
    Expected: not verified; the error names `SHA256SUMS.txt` as mismatched and its message
    contains that name. No file is reported as verified against an altered list.
    """
    altered = alter(intact.checksum_list.decode("ascii")).encode("ascii")
    assert altered != intact.checksum_list
    (intact.folder / LIST_NAME).write_bytes(altered)

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert excinfo.value.mismatched == (LIST_NAME,)
    assert excinfo.value.missing == ()
    assert str(excinfo.value) == "mitdb 1.0.0 not verified: checksum mismatch: SHA256SUMS.txt"


@pytest.mark.requirement("SRS-001")
def test_file_and_list_altered_consistently_are_not_verified(
    intact: Any, make_checksum_list: Callable[..., bytes]
) -> None:
    """An altered file whose entry in the local list was altered to match it.

    Input: the fixture folder where `100.dat` is altered and `SHA256SUMS.txt` is rewritten
    with the checksum of the altered file, so that every file matches the local list.
    Expected: not verified: the local list no longer has the pinned SHA-256, and the error
    names `SHA256SUMS.txt` as mismatched.
    """
    _flip_one_bit(_file(intact.folder, "100.dat"))
    altered_files = dict(FILES)
    altered_files["100.dat"] = _file(intact.folder, "100.dat").read_bytes()
    (intact.folder / LIST_NAME).write_bytes(make_checksum_list(altered_files))

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert excinfo.value.mismatched == (LIST_NAME,)


@pytest.mark.requirement("SRS-001")
def test_missing_database_folder_is_not_verified(tmp_path: Path, intact: Any) -> None:
    """A data directory that does not hold the database folder.

    Input: the database description of the fixture and an empty data directory.
    Expected: not verified; the error names `SHA256SUMS.txt` as missing.
    """
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), empty)

    assert excinfo.value.missing == (LIST_NAME,)
    assert excinfo.value.mismatched == ()


# --------------------------------------------------------------------------------------------
# Reading the checksum list
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-001")
def test_every_listed_file_is_read_from_the_checksum_list(
    make_checksum_list: Callable[..., bytes], sha256_hex: Callable[[bytes], str]
) -> None:
    """The checksum list gives one SHA-256 per listed file.

    Input: the checksum list of the fixture database (12 lines `<digest> <path>`).
    Expected: 12 entries, one per path, each with the SHA-256 of the file in lowercase; the
    selection for the whole database is these 12 paths.
    """
    text = make_checksum_list(FILES).decode("ascii")

    checksums = parse_checksum_list(text, LIST_NAME)

    assert dict(checksums) == {path: sha256_hex(content) for path, content in FILES.items()}
    assert sorted(select_files(checksums, None)) == list(ALL_FILES)


@pytest.mark.requirement("SRS-001")
@pytest.mark.parametrize(
    "line",
    [
        pytest.param("{digest} {path}", id="one-space"),
        pytest.param("{digest}  {path}", id="two-spaces"),
        pytest.param("{digest} *{path}", id="binary-mark"),
        pytest.param("{upper} {path}", id="upper-case-digest"),
    ],
)
def test_checksum_list_formats_of_sha256sum_are_read(line: str) -> None:
    """The line formats of a checksum list.

    Input: a list of two lines for `100.dat` and `mitdbdir/intro.htm`, written with one
    space, two spaces or a binary mark between digest and path, or with the digest in upper
    case; with an empty line between them.
    Expected: two entries, with the digests in lowercase.
    """
    digests = {
        path: hashlib.sha256(FILES[path]).hexdigest() for path in ("100.dat", "mitdbdir/intro.htm")
    }
    text = "\n\n".join(
        line.format(digest=digest, upper=digest.upper(), path=path)
        for path, digest in digests.items()
    )

    assert dict(parse_checksum_list(text + "\n", LIST_NAME)) == digests


GOOD_DIGEST = "ab" * 32
GOOD_LINE = f"{GOOD_DIGEST} 100.dat\n"


@pytest.mark.requirement("SRS-001")
@pytest.mark.parametrize(
    ("text", "line"),
    [
        pytest.param(GOOD_LINE + "100.hea\n", 2, id="no-digest"),
        pytest.param(GOOD_LINE + GOOD_DIGEST[:-1] + " 100.hea\n", 2, id="63-digits"),
        pytest.param(GOOD_LINE + GOOD_DIGEST + "a 100.hea\n", 2, id="65-digits"),
        pytest.param(GOOD_LINE + "g" + GOOD_DIGEST[1:] + " 100.hea\n", 2, id="not-hexadecimal"),
        pytest.param(GOOD_DIGEST + "\n", 1, id="no-path"),
        pytest.param(GOOD_LINE + GOOD_DIGEST + " 100 .hea\n", 2, id="space-in-path"),
        pytest.param(GOOD_LINE + GOOD_DIGEST + " 100.dat\n", 2, id="duplicate-path"),
        pytest.param(GOOD_DIGEST + " ../outside.dat\n", 1, id="parent-folder"),
        pytest.param(GOOD_LINE + GOOD_DIGEST + " mitdbdir/../../outside.dat\n", 2, id="dot-dot"),
        pytest.param(GOOD_DIGEST + " /etc/outside.dat\n", 1, id="absolute-path"),
        pytest.param(GOOD_DIGEST + " ./100.hea\n", 1, id="dot-component"),
        pytest.param(GOOD_DIGEST + " mitdbdir//intro.htm\n", 1, id="empty-component"),
        pytest.param(GOOD_DIGEST + " mitdbdir\\intro.htm\n", 1, id="backslash"),
        pytest.param(GOOD_DIGEST + " C:/outside.dat\n", 1, id="drive-letter"),
    ],
)
def test_malformed_checksum_list_is_rejected(text: str, line: int) -> None:
    """A checksum list that does not follow its format, or names a file outside the folder.

    Input: a list with a line that has no valid digest or no path, a path listed twice, or
    a path that is absolute, leaves the database folder or is not written with `/`.
    Expected: an error for a malformed file that names the list and the 1-based number of
    the offending line; no entry is returned.
    """
    with pytest.raises(MalformedFileError) as excinfo:
        parse_checksum_list(text, LIST_NAME)

    assert isinstance(excinfo.value, SinusError)
    assert excinfo.value.path == LIST_NAME
    assert excinfo.value.line == line
    assert LIST_NAME in str(excinfo.value)


@pytest.mark.requirement("SRS-001")
@pytest.mark.parametrize("text", ["", "\n", "\n\n\n"], ids=["empty", "one-newline", "newlines"])
def test_empty_checksum_list_is_rejected(text: str) -> None:
    """A checksum list without any entry.

    Input: an empty text, or only empty lines.
    Expected: an error for a malformed file that names the list: an empty list cannot make
    a database verified.
    """
    with pytest.raises(MalformedFileError) as excinfo:
        parse_checksum_list(text, LIST_NAME)

    assert excinfo.value.path == LIST_NAME


@pytest.mark.requirement("SRS-001")
def test_database_with_a_malformed_pinned_list_is_not_reported_as_verified(
    tmp_path: Path, sha256_hex: Callable[[bytes], str]
) -> None:
    """A local list that has the pinned SHA-256 but does not follow the format.

    Input: a folder whose `SHA256SUMS.txt` holds a valid line and a line without digest,
    and a database description that pins the SHA-256 of that text.
    Expected: no verification result: an error for a malformed file is raised.
    """
    folder = tmp_path / SLUG
    folder.mkdir()
    content = GOOD_LINE.encode("ascii") + b"not a checksum line\n"
    (folder / LIST_NAME).write_bytes(content)
    (folder / "100.dat").write_bytes(b"data")

    with pytest.raises(MalformedFileError):
        verify_database(_database(sha256_hex(content)), tmp_path)


# --------------------------------------------------------------------------------------------
# Download, with a fetch function that needs no network
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-001")
def test_download_obtains_every_listed_file_from_physionet_and_verifies_it(
    tmp_path: Path,
    make_checksum_list: Callable[..., bytes],
    sha256_hex: Callable[[bytes], str],
    make_fake_fetch: Callable[..., Any],
) -> None:
    """Download of the whole database into a data directory that does not exist yet.

    Input: an empty location, and a fetch function that serves the checksum list and the 12
    files of the fixture database at their PhysioNet addresses,
    `https://physionet.org/files/mitdb/1.0.0/<path>`.
    Expected: the database is reported as verified, with its 12 files; the folder
    `<data directory>/mitdb` holds exactly the 12 files (in their subfolders) and the
    checksum list, with the served content; every address asked is one of the served ones,
    under the PhysioNet address of version 1.0.0.
    """
    checksum_list = make_checksum_list(FILES)
    fetch = make_fake_fetch(_served(FILES, checksum_list))
    data_root = tmp_path / "new" / "data"
    database = _database(sha256_hex(checksum_list))

    result = download_database(database, data_root, fetch=fetch)

    assert result.database == database
    assert result.records is None
    assert tuple(result.files) == ALL_FILES
    assert _snapshot(data_root / SLUG) == {**FILES, LIST_NAME: checksum_list}
    assert sorted(fetch.calls) == sorted(fetch.contents)
    assert all(url.startswith(BASE_URL) for url in fetch.calls)
    assert verify_database(database, data_root).files == result.files


@pytest.mark.requirement("SRS-001")
def test_download_names_the_file_not_obtained_and_the_file_obtained_altered(
    tmp_path: Path,
    make_checksum_list: Callable[..., bytes],
    sha256_hex: Callable[[bytes], str],
    make_fake_fetch: Callable[..., Any],
) -> None:
    """A download that leaves one file missing and one file altered.

    Input: an empty data directory, and a fetch function that fails for `101.atr` (raises
    `OSError`) and serves `100.dat` with one byte changed; everything else is served intact.
    Expected: the database is reported as not verified; the error names `101.atr` as missing
    and names `100.dat` too, and its message contains both names. The failure of the fetch
    is not raised as such: the outcome comes from the verification of the local files.
    """
    checksum_list = make_checksum_list(FILES)
    served = _served(FILES, checksum_list)
    del served[BASE_URL + "101.atr"]
    served[BASE_URL + "100.dat"] = b"\xff" + FILES["100.dat"][1:]
    fetch = make_fake_fetch(served)

    with pytest.raises(DataVerificationError) as excinfo:
        download_database(_database(sha256_hex(checksum_list)), tmp_path, fetch=fetch)

    error = excinfo.value
    assert error.database == "mitdb 1.0.0"
    assert "101.atr" in error.missing
    assert set(error.missing) | set(error.mismatched) == {"100.dat", "101.atr"}
    assert "100.dat" in str(error)
    assert "101.atr" in str(error)
    assert BASE_URL + "101.atr" in fetch.calls


@pytest.mark.requirement("SRS-001")
def test_download_without_network_is_not_verified(
    tmp_path: Path,
    make_checksum_list: Callable[..., bytes],
    sha256_hex: Callable[[bytes], str],
    make_fake_fetch: Callable[..., Any],
) -> None:
    """A download when nothing can be fetched.

    Input: an empty data directory and a fetch function that fails for every address.
    Expected: not verified; the error names the checksum list `SHA256SUMS.txt` as missing;
    the only address asked is that of the list; no database file is written.
    """
    fetch = make_fake_fetch({})
    database = _database(sha256_hex(make_checksum_list(FILES)))

    with pytest.raises(DataVerificationError) as excinfo:
        download_database(database, tmp_path, fetch=fetch)

    assert excinfo.value.missing == (LIST_NAME,)
    assert excinfo.value.mismatched == ()
    assert fetch.calls == [BASE_URL + LIST_NAME]
    assert _snapshot(tmp_path / SLUG) == {}


@pytest.mark.requirement("SRS-001")
def test_download_rejects_a_checksum_list_that_differs_from_the_published_one(
    tmp_path: Path,
    make_checksum_list: Callable[..., bytes],
    sha256_hex: Callable[[bytes], str],
    make_fake_fetch: Callable[..., Any],
) -> None:
    """A checksum list altered on the server or in transit.

    Input: an empty data directory, and a fetch function that serves the 12 files and a
    checksum list in which the digest of `100.dat` was replaced, while the database
    description pins the SHA-256 of the genuine list.
    Expected: not verified; the error names `SHA256SUMS.txt` as mismatched; the served list
    is not written, and no file is fetched on the word of that list.
    """
    genuine = make_checksum_list(FILES)
    forged = make_checksum_list({**FILES, "100.dat": b"forged content"})
    fetch = make_fake_fetch(_served(FILES, forged))

    with pytest.raises(DataVerificationError) as excinfo:
        download_database(_database(sha256_hex(genuine)), tmp_path, fetch=fetch)

    assert excinfo.value.mismatched == (LIST_NAME,)
    assert excinfo.value.missing == ()
    assert fetch.calls == [BASE_URL + LIST_NAME]
    assert _snapshot(tmp_path / SLUG) == {}


@pytest.mark.requirement("SRS-001")
def test_download_of_the_reference_database_asks_physionet_for_version_1_0_0(
    tmp_path: Path, make_checksum_list: Callable[..., bytes], make_fake_fetch: Callable[..., Any]
) -> None:
    """The real database description, with a fetch function that serves a different list.

    Input: the reference database of the software, an empty data directory, and a fetch
    function that serves the fixture checksum list (not the one PhysioNet publishes) at
    `https://physionet.org/files/mitdb/1.0.0/SHA256SUMS.txt`.
    Expected: the software asks for the checksum list at that address, finds that it is not
    the published list of version 1.0.0 and reports the database as not verified, naming
    `SHA256SUMS.txt` as mismatched; nothing else is fetched and nothing is written.
    """
    fetch = make_fake_fetch(_served(FILES, make_checksum_list(FILES)))

    with pytest.raises(DataVerificationError) as excinfo:
        download_database(MITDB, tmp_path, fetch=fetch)

    assert excinfo.value.database == "mitdb 1.0.0"
    assert excinfo.value.mismatched == (LIST_NAME,)
    assert fetch.calls == ["https://physionet.org/files/mitdb/1.0.0/SHA256SUMS.txt"]
    assert _snapshot(tmp_path / "mitdb") == {}


@pytest.mark.requirement("SRS-001")
def test_download_of_an_intact_local_copy_fetches_nothing(
    intact: Any, make_fake_fetch: Callable[..., Any]
) -> None:
    """Running the download again on a complete and verified copy.

    Input: the intact fixture folder and a fetch function that fails for every address.
    Expected: the database is reported as verified with its 12 files, from the local files
    alone: no address is asked and the folder is unchanged.
    """
    fetch = make_fake_fetch({})
    before = _snapshot(intact.folder)

    result = download_database(
        _database(intact.checksum_list_sha256), intact.data_root, fetch=fetch
    )

    assert tuple(result.files) == ALL_FILES
    assert fetch.calls == []
    assert _snapshot(intact.folder) == before


@pytest.mark.requirement("SRS-001")
def test_download_replaces_altered_files_and_adds_missing_ones(
    intact: Any, make_fake_fetch: Callable[..., Any]
) -> None:
    """Running the download on a copy with one altered and one missing file.

    Input: the fixture folder with one bit changed in `100.dat` and `mitdbdir/intro.htm`
    deleted, and a fetch function that serves the whole database.
    Expected: the database is reported as verified; both files now have the published
    content; only these two files were fetched, the intact ones were kept.
    """
    _flip_one_bit(_file(intact.folder, "100.dat"))
    _file(intact.folder, "mitdbdir/intro.htm").unlink()
    fetch = make_fake_fetch(_served(FILES, intact.checksum_list))

    result = download_database(
        _database(intact.checksum_list_sha256), intact.data_root, fetch=fetch
    )

    assert tuple(result.files) == ALL_FILES
    assert _snapshot(intact.folder) == {**FILES, LIST_NAME: intact.checksum_list}
    assert sorted(fetch.calls) == [BASE_URL + "100.dat", BASE_URL + "mitdbdir/intro.htm"]


@pytest.mark.requirement("SRS-001")
def test_download_replaces_an_altered_local_checksum_list(
    intact: Any, make_fake_fetch: Callable[..., Any]
) -> None:
    """Running the download on a copy whose checksum list was altered.

    Input: the fixture folder with intact files and a `SHA256SUMS.txt` with one digit
    changed, and a fetch function that serves the whole database.
    Expected: the list is fetched again and replaced by the published one; the database is
    reported as verified.
    """
    altered = intact.checksum_list.decode("ascii").replace("0", "1", 1).encode("ascii")
    (intact.folder / LIST_NAME).write_bytes(altered)
    fetch = make_fake_fetch(_served(FILES, intact.checksum_list))

    result = download_database(
        _database(intact.checksum_list_sha256), intact.data_root, fetch=fetch
    )

    assert tuple(result.files) == ALL_FILES
    assert (intact.folder / LIST_NAME).read_bytes() == intact.checksum_list
    assert BASE_URL + LIST_NAME in fetch.calls


@pytest.mark.requirement("SRS-001")
def test_download_does_not_write_outside_the_database_folder(
    tmp_path: Path, sha256_hex: Callable[[bytes], str], make_fake_fetch: Callable[..., Any]
) -> None:
    """A checksum list that names a file outside the database folder.

    Input: a served checksum list, with the pinned SHA-256, that lists `100.dat` and
    `../outside.dat`, and a fetch function that serves both.
    Expected: the list is rejected as malformed; no file is written outside the database
    folder.
    """
    files = {"100.dat": b"inside", "../outside.dat": b"outside"}
    checksum_list = "".join(
        f"{sha256_hex(content)} {path}\n" for path, content in files.items()
    ).encode("ascii")
    served = {BASE_URL + LIST_NAME: checksum_list}
    served.update({BASE_URL + path: content for path, content in files.items()})
    fetch = make_fake_fetch(served)
    data_root = tmp_path / "data"

    with pytest.raises(MalformedFileError):
        download_database(_database(sha256_hex(checksum_list)), data_root, fetch=fetch)

    assert not (data_root / "outside.dat").exists()
    assert not (tmp_path / "outside.dat").exists()
    assert BASE_URL + "../outside.dat" not in fetch.calls
