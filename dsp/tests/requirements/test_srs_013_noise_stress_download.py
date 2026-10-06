"""Requirement tests of SRS-013: verified download of the noise stress test database (RC-004).

No test uses the network. A fixture folder holds a few files named like those of the MIT-BIH
Noise Stress Test Database (noisy records such as `118e24` and `118e_6`, the noise records
`bw`, `em` and `ma`, a subfolder `old/`) and their checksum list `SHA256SUMS.txt`; the
`Database` under test pins the SHA-256 of that list. The download is exercised with a fetch
function that serves bytes from a dictionary and raises `OSError` for anything else. A
fixture makes any real network access fail the test.

Pass criteria (SRS-013): an intact set is reported as verified; a set with a missing file or
a file whose checksum does not match is reported as not verified, with an error naming each
such file. The reading of the checksum list, common to both databases, is tested with
SRS-001.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sinus_dsp.data.physionet import (
    NSTDB,
    Database,
    DatabaseLicence,
    describe_verification,
    download_database,
    verify_database,
)
from sinus_dsp.errors import DataVerificationError, SinusError

pytestmark = pytest.mark.usefixtures("forbid_network")

SLUG = "nstdb"
VERSION = "1.0.0"
TITLE = "MIT-BIH Noise Stress Test Database"
# A licence of the fixture database: the `Database` has no default for it (SRS-012, SRS-014;
# architecture, section 8.3). It plays no part in the verification.
FIXTURE_LICENCE = DatabaseLicence(
    name="Fixture Data Licence 1.0", url="https://licences.example.org/fixture/1-0/"
)
BASE_URL = "https://physionet.org/files/nstdb/1.0.0/"
LIST_NAME = "SHA256SUMS.txt"

# SHA-256 of the checksum list of version 1.0.0, as pinned in docs/regulatory/architecture.md.
NSTDB_LIST_SHA256 = "b76bd98c5111439fcfff2f410afd70d64e79f072049c45b5a9916a3044fdb84f"

# A small database with the structure of the real one: relative path -> content.
FILES: dict[str, bytes] = {
    "118e24.atr": b"annotations of record 118e24\n",
    "118e24.dat": bytes(range(256)) * 12,
    "118e24.hea": b"118e24 2 360 650000\n",
    "118e24.xws": b"setup of record 118e24\n",
    "118e_6.atr": b"annotations of record 118e_6\n",
    "118e_6.dat": bytes(reversed(range(256))) * 12,
    "118e_6.hea": b"118e_6 2 360 650000\n",
    "119e00.atr": b"annotations of record 119e00\n",
    "119e00.dat": bytes(range(0, 256, 2)) * 24,
    "119e00.hea": b"119e00 2 360 650000\n",
    "RECORDS": b"118e24\n118e_6\n119e00\nbw\nem\nma\n",
    "bw.dat": b"\x01\x02" * 500,
    "bw.hea": b"bw 2 360 650000\n",
    "em.dat": b"\x03\x04" * 500,
    "em.hea": b"em 2 360 650000\n",
    "ma.dat": b"\x05\x06" * 500,
    "ma.hea": b"ma 2 360 650000\n",
    "old/118_00.dat": b"\x07\x08" * 300,
}
ALL_FILES = tuple(sorted(FILES))

# Files of a second database in the same data directory (names of the arrhythmia database).
MITDB_FILES: dict[str, bytes] = {
    "118.atr": b"annotations of record 118\n",
    "118.dat": bytes(range(256)) * 4,
    "118.hea": b"118 2 360 650000\n",
}


def _database(pinned_sha256: str) -> Database:
    """A database description with the noise stress identity and the given pinned digest."""
    return Database(
        slug=SLUG,
        version=VERSION,
        title=TITLE,
        checksum_list_sha256=pinned_sha256,
        licence=FIXTURE_LICENCE,
    )


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
    """The fixture database, complete and unaltered, in ``tmp_path / "data" / "nstdb"``."""
    return write_database_folder(tmp_path / "data", SLUG, FILES)


# --------------------------------------------------------------------------------------------
# The noise stress test database and its version
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-013")
def test_database_is_version_1_0_0_of_the_mit_bih_noise_stress_test_database() -> None:
    """The database that the software obtains and verifies.

    Input: the database description of the software for the noise stress test database.
    Expected: the MIT-BIH Noise Stress Test Database (PhysioNet name `nstdb`), version
    1.0.0, with the SHA-256 of the checksum list of that version pinned as 64 lowercase
    hexadecimal digits, equal to the documented digest.
    """
    assert NSTDB.slug == "nstdb"
    assert NSTDB.version == "1.0.0"
    assert NSTDB.title == "MIT-BIH Noise Stress Test Database"
    assert NSTDB.checksum_list_sha256 == NSTDB_LIST_SHA256


@pytest.mark.requirement("SRS-013")
def test_database_is_not_verified_when_nothing_was_downloaded(tmp_path: Path) -> None:
    """The real database description on an empty data directory.

    Input: the noise stress test database of the software and a data directory without it.
    Expected: not verified: an error that names the database `nstdb 1.0.0` and the missing
    checksum list `SHA256SUMS.txt`.
    """
    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(NSTDB, tmp_path)

    assert excinfo.value.database == "nstdb 1.0.0"
    assert excinfo.value.missing == (LIST_NAME,)
    assert excinfo.value.mismatched == ()


# --------------------------------------------------------------------------------------------
# Verification of a local copy
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-013")
def test_intact_set_is_reported_as_verified(intact: Any) -> None:
    """The first verification case of SRS-013: an intact set.

    Input: the fixture folder with its 18 files, unaltered, and the checksum list whose
    SHA-256 is pinned in the database description.
    Expected: no error; the result names the database, covers the whole database and lists
    the 18 verified files (every file of the checksum list, the one in `old/` included);
    the folder is left unchanged.
    """
    database = _database(intact.checksum_list_sha256)
    before = _snapshot(intact.folder)

    result = verify_database(database, intact.data_root)

    assert result.database == database
    assert result.records is None
    assert tuple(result.files) == ALL_FILES
    assert _snapshot(intact.folder) == before
    assert describe_verification(result) == (
        "verified: 18 files match the published SHA-256 checksum list "
        f"(SHA256SUMS.txt, SHA-256 {intact.checksum_list_sha256})"
    )


@pytest.mark.requirement("SRS-013")
def test_one_altered_and_one_missing_file_are_both_named(intact: Any) -> None:
    """The second verification case of SRS-013: one altered and one missing file.

    Input: the fixture folder with one bit changed in `118e_6.dat` and `em.hea` deleted.
    Expected: not verified: an error for the database `nstdb 1.0.0` whose missing files are
    exactly `em.hea` and whose mismatched files are exactly `118e_6.dat`; the message names
    both files, in the documented form. The verification changes nothing in the folder.
    """
    _flip_one_bit(_file(intact.folder, "118e_6.dat"))
    _file(intact.folder, "em.hea").unlink()
    before = _snapshot(intact.folder)

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    error = excinfo.value
    assert isinstance(error, SinusError)
    assert error.database == "nstdb 1.0.0"
    assert error.missing == ("em.hea",)
    assert error.mismatched == ("118e_6.dat",)
    assert str(error) == "nstdb 1.0.0 not verified: missing: em.hea; checksum mismatch: 118e_6.dat"
    assert _snapshot(intact.folder) == before


@pytest.mark.requirement("SRS-013")
@pytest.mark.parametrize("name", ALL_FILES)
def test_any_altered_file_is_named(intact: Any, name: str) -> None:
    """Every listed file is verified: an alteration of any one of them is found.

    Input: the fixture folder with one bit changed in one file, for each of the 18 files
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


@pytest.mark.requirement("SRS-013")
@pytest.mark.parametrize("name", ALL_FILES)
def test_any_missing_file_is_named(intact: Any, name: str) -> None:
    """Every listed file is verified: the absence of any one of them is found.

    Input: the fixture folder with one file deleted, for each of the 18 files in turn.
    Expected: not verified; the error names exactly that file as missing, no file as
    mismatched, and the message contains its name.
    """
    _file(intact.folder, name).unlink()

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert excinfo.value.missing == (name,)
    assert excinfo.value.mismatched == ()
    assert name in str(excinfo.value)


@pytest.mark.requirement("SRS-013")
def test_every_altered_and_every_missing_file_is_named(intact: Any) -> None:
    """Several altered and several missing files: the error names each of them.

    Input: the fixture folder with `ma.dat`, `118e24.atr` and `RECORDS` altered, and
    `old/118_00.dat`, `bw.hea` and `119e00.dat` deleted.
    Expected: not verified; the missing files and the mismatched files are complete, each
    list in code-point order; the message lists them all in the documented form.
    """
    for name in ("ma.dat", "118e24.atr", "RECORDS"):
        _flip_one_bit(_file(intact.folder, name))
    for name in ("old/118_00.dat", "bw.hea", "119e00.dat"):
        _file(intact.folder, name).unlink()

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert excinfo.value.missing == ("119e00.dat", "bw.hea", "old/118_00.dat")
    assert excinfo.value.mismatched == ("118e24.atr", "RECORDS", "ma.dat")
    assert str(excinfo.value) == (
        "nstdb 1.0.0 not verified: missing: 119e00.dat, bw.hea, old/118_00.dat; "
        "checksum mismatch: 118e24.atr, RECORDS, ma.dat"
    )


@pytest.mark.requirement("SRS-013")
def test_missing_checksum_list_is_named(
    tmp_path: Path, write_database_folder: Callable[..., Any]
) -> None:
    """The files are present but the checksum list is not.

    Input: the fixture folder with its 18 intact files and no `SHA256SUMS.txt`.
    Expected: not verified; the error names `SHA256SUMS.txt` as missing.
    """
    folder = write_database_folder(tmp_path, SLUG, FILES, with_list=False)

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(folder.checksum_list_sha256), folder.data_root)

    assert excinfo.value.missing == (LIST_NAME,)
    assert excinfo.value.mismatched == ()
    assert str(excinfo.value) == "nstdb 1.0.0 not verified: missing: SHA256SUMS.txt"


@pytest.mark.requirement("SRS-013")
def test_altered_checksum_list_is_named(intact: Any) -> None:
    """A checksum list that differs from the published one.

    Input: the fixture folder with its 18 intact files and a `SHA256SUMS.txt` in which the
    line of `em.dat` was removed, while the database description pins the SHA-256 of the
    complete list.
    Expected: not verified; the error names `SHA256SUMS.txt` as mismatched. The files that
    are still listed are not reported as verified.
    """
    lines = intact.checksum_list.decode("ascii").splitlines(keepends=True)
    shortened = "".join(line for line in lines if not line.endswith(" em.dat\n"))
    assert len(shortened.splitlines()) == 17
    (intact.folder / LIST_NAME).write_bytes(shortened.encode("ascii"))

    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(_database(intact.checksum_list_sha256), intact.data_root)

    assert excinfo.value.mismatched == (LIST_NAME,)
    assert excinfo.value.missing == ()
    assert str(excinfo.value) == "nstdb 1.0.0 not verified: checksum mismatch: SHA256SUMS.txt"


@pytest.mark.requirement("SRS-013")
def test_both_databases_are_verified_independently_in_the_same_data_directory(
    tmp_path: Path, write_database_folder: Callable[..., Any]
) -> None:
    """The noise stress test database next to the reference database.

    Input: one data directory with the fixture folder `nstdb` and a folder `mitdb` (three
    files of record 118 and their own checksum list). First the `mitdb` folder is altered,
    then the `nstdb` folder.
    Expected: each database is verified in its own folder `<data directory>/<name>` against
    its own list: with `mitdb/118.dat` altered, the noise stress test database is still
    verified and the other is not; with `nstdb/bw.dat` deleted, the error is for
    `nstdb 1.0.0` and names `bw.dat`.
    """
    data_root = tmp_path / "data"
    noise = write_database_folder(data_root, SLUG, FILES)
    arrhythmia = write_database_folder(data_root, "mitdb", MITDB_FILES)
    noise_database = _database(noise.checksum_list_sha256)
    arrhythmia_database = Database(
        slug="mitdb",
        version="1.0.0",
        title="MIT-BIH Arrhythmia Database",
        checksum_list_sha256=arrhythmia.checksum_list_sha256,
        licence=FIXTURE_LICENCE,
    )

    assert tuple(verify_database(noise_database, data_root).files) == ALL_FILES
    assert tuple(verify_database(arrhythmia_database, data_root).files) == tuple(
        sorted(MITDB_FILES)
    )

    _flip_one_bit(arrhythmia.folder / "118.dat")
    assert tuple(verify_database(noise_database, data_root).files) == ALL_FILES
    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(arrhythmia_database, data_root)
    assert excinfo.value.database == "mitdb 1.0.0"
    assert excinfo.value.mismatched == ("118.dat",)

    (noise.folder / "bw.dat").unlink()
    with pytest.raises(DataVerificationError) as excinfo:
        verify_database(noise_database, data_root)
    assert excinfo.value.database == "nstdb 1.0.0"
    assert excinfo.value.missing == ("bw.dat",)
    assert excinfo.value.mismatched == ()


# --------------------------------------------------------------------------------------------
# Download, with a fetch function that needs no network
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-013")
def test_download_obtains_every_listed_file_from_physionet_and_verifies_it(
    tmp_path: Path,
    make_checksum_list: Callable[..., bytes],
    sha256_hex: Callable[[bytes], str],
    make_fake_fetch: Callable[..., Any],
) -> None:
    """Download of the whole database into an empty data directory.

    Input: an empty data directory, and a fetch function that serves the checksum list and
    the 18 files of the fixture database at their PhysioNet addresses,
    `https://physionet.org/files/nstdb/1.0.0/<path>`.
    Expected: the database is reported as verified, with its 18 files; the folder
    `<data directory>/nstdb` holds exactly the 18 files (the one of `old/` in its
    subfolder) and the checksum list, with the served content; every address asked is one
    of the served ones, under the PhysioNet address of version 1.0.0.
    """
    checksum_list = make_checksum_list(FILES)
    fetch = make_fake_fetch(_served(FILES, checksum_list))
    database = _database(sha256_hex(checksum_list))

    result = download_database(database, tmp_path, fetch=fetch)

    assert result.database == database
    assert result.records is None
    assert tuple(result.files) == ALL_FILES
    assert _snapshot(tmp_path / SLUG) == {**FILES, LIST_NAME: checksum_list}
    assert sorted(fetch.calls) == sorted(fetch.contents)
    assert all(url.startswith(BASE_URL) for url in fetch.calls)


@pytest.mark.requirement("SRS-013")
def test_download_names_the_file_not_obtained_and_the_file_obtained_altered(
    tmp_path: Path,
    make_checksum_list: Callable[..., bytes],
    sha256_hex: Callable[[bytes], str],
    make_fake_fetch: Callable[..., Any],
) -> None:
    """A download that leaves one file missing and one file altered.

    Input: an empty data directory, and a fetch function that fails for `em.dat` (raises
    `OSError`) and serves `119e00.hea` with one byte changed; everything else is served
    intact.
    Expected: the database is reported as not verified; the error names `em.dat` as missing
    and names `119e00.hea` too, and its message contains both names.
    """
    checksum_list = make_checksum_list(FILES)
    served = _served(FILES, checksum_list)
    del served[BASE_URL + "em.dat"]
    served[BASE_URL + "119e00.hea"] = b"X" + FILES["119e00.hea"][1:]
    fetch = make_fake_fetch(served)

    with pytest.raises(DataVerificationError) as excinfo:
        download_database(_database(sha256_hex(checksum_list)), tmp_path, fetch=fetch)

    error = excinfo.value
    assert error.database == "nstdb 1.0.0"
    assert "em.dat" in error.missing
    assert set(error.missing) | set(error.mismatched) == {"119e00.hea", "em.dat"}
    assert "119e00.hea" in str(error)
    assert "em.dat" in str(error)


@pytest.mark.requirement("SRS-013")
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


@pytest.mark.requirement("SRS-013")
def test_download_of_the_database_asks_physionet_for_version_1_0_0(
    tmp_path: Path, make_checksum_list: Callable[..., bytes], make_fake_fetch: Callable[..., Any]
) -> None:
    """The real database description, with a fetch function that serves a different list.

    Input: the noise stress test database of the software, an empty data directory, and a
    fetch function that serves the fixture checksum list (not the one PhysioNet publishes)
    at `https://physionet.org/files/nstdb/1.0.0/SHA256SUMS.txt`.
    Expected: the software asks for the checksum list at that address, finds that it is not
    the published list of version 1.0.0 and reports the database as not verified, naming
    `SHA256SUMS.txt` as mismatched; nothing else is fetched and nothing is written.
    """
    fetch = make_fake_fetch(_served(FILES, make_checksum_list(FILES)))

    with pytest.raises(DataVerificationError) as excinfo:
        download_database(NSTDB, tmp_path, fetch=fetch)

    assert excinfo.value.database == "nstdb 1.0.0"
    assert excinfo.value.mismatched == (LIST_NAME,)
    assert excinfo.value.missing == ()
    assert fetch.calls == ["https://physionet.org/files/nstdb/1.0.0/SHA256SUMS.txt"]
    assert _snapshot(tmp_path / "nstdb") == {}


@pytest.mark.requirement("SRS-013")
def test_download_completes_a_partial_local_copy(
    intact: Any, make_fake_fetch: Callable[..., Any]
) -> None:
    """Running the download on a copy with one altered and one missing file.

    Input: the fixture folder with one bit changed in `118e24.dat` and `old/118_00.dat`
    deleted, and a fetch function that serves the whole database.
    Expected: the database is reported as verified; both files now have the published
    content; only these two files were fetched, the intact ones were kept.
    """
    _flip_one_bit(_file(intact.folder, "118e24.dat"))
    _file(intact.folder, "old/118_00.dat").unlink()
    fetch = make_fake_fetch(_served(FILES, intact.checksum_list))
    database = _database(intact.checksum_list_sha256)

    result = download_database(database, intact.data_root, fetch=fetch)

    assert tuple(result.files) == ALL_FILES
    assert _snapshot(intact.folder) == {**FILES, LIST_NAME: intact.checksum_list}
    assert sorted(fetch.calls) == [BASE_URL + "118e24.dat", BASE_URL + "old/118_00.dat"]
