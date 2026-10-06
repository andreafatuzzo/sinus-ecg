"""Unit tests of the download and verification of a database. No test uses the network."""

import dataclasses
import hashlib
import http.client
import inspect
import os
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from sinus_dsp.data.physionet import (
    CHECKSUM_LIST_NAME,
    MITDB,
    NSTDB,
    ODC_BY_1_0,
    PHYSIONET_FILES_URL,
    Database,
    DatabaseLicence,
    VerificationResult,
    database_url,
    describe_verification,
    download_database,
    fetch_https,
    parse_checksum_list,
    select_files,
    verify_database,
)
from sinus_dsp.errors import DataVerificationError, InvalidInputError, MalformedFileError

DIGEST_A = "a" * 64
DIGEST_B = "0123456789abcdef" * 4
#: The licence of the fixture databases, not that of the real ones.
LICENCE = DatabaseLicence("Fixture Licence 1.0", "https://licences.example/fixdb/")

FILES: Mapping[str, bytes] = {
    "100.atr": b"annotations of 100",
    "100.dat": b"samples of 100",
    "100.hea": b"header of 100",
    "101.dat": b"samples of 101",
    "101.hea": b"header of 101",
    "RECORDS": b"100\n101\n",
    "docs/notes.txt": b"notes",
    "docs/deep/100.dat": b"not a record file",
}


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def checksum_list(files: Mapping[str, bytes]) -> bytes:
    """The checksum list of the files, one ``<digest> <path>`` line each, with line feeds."""
    return "".join(f"{sha256(content)} {path}\n" for path, content in files.items()).encode()


def fixture_database(files: Mapping[str, bytes] = FILES, slug: str = "fixdb") -> Database:
    """A database whose pinned digest is the one of the checksum list of ``files``."""
    return Database(
        slug=slug,
        version="1.0.0",
        title="Fixture Database",
        checksum_list_sha256=sha256(checksum_list(files)),
        licence=LICENCE,
    )


def write_database(data_root: Path, database: Database, files: Mapping[str, bytes] = FILES) -> Path:
    """Write the files and their checksum list into ``data_root/<slug>``; return the folder."""
    folder = data_root / database.slug
    for path, content in files.items():
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (folder / CHECKSUM_LIST_NAME).write_bytes(checksum_list(files))
    return folder


class FakeFetch:
    """A fetch function that serves bytes from a dictionary and records the URLs requested."""

    def __init__(self, content: Mapping[str, bytes]) -> None:
        self.content = dict(content)
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if url not in self.content:
            raise OSError(f"not served: {url}")
        return self.content[url]


def served(database: Database, files: Mapping[str, bytes] = FILES) -> dict[str, bytes]:
    """What the server of a database serves: its files and their checksum list."""
    base = database_url(database)
    content = {base + path: body for path, body in files.items()}
    content[base + CHECKSUM_LIST_NAME] = checksum_list(files)
    return content


def tree(folder: Path) -> dict[str, bytes]:
    """Every file under a folder, by relative path with ``/`` separators."""
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any attempt to open a URL fail the test."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"network access attempted: {args!r}")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


# Constants and URLs


def test_constants() -> None:
    assert PHYSIONET_FILES_URL == "https://physionet.org/files"
    assert CHECKSUM_LIST_NAME == "SHA256SUMS.txt"


def test_pinned_databases() -> None:
    assert MITDB == Database(
        slug="mitdb",
        version="1.0.0",
        title="MIT-BIH Arrhythmia Database",
        checksum_list_sha256="b61158a96d5f2ca80edfb354a9a66a6324836c390a84e1966dcee2b907d6be43",
        licence=ODC_BY_1_0,
    )
    assert NSTDB == Database(
        slug="nstdb",
        version="1.0.0",
        title="MIT-BIH Noise Stress Test Database",
        checksum_list_sha256="b76bd98c5111439fcfff2f410afd70d64e79f072049c45b5a9916a3044fdb84f",
        licence=ODC_BY_1_0,
    )


def test_licence_of_the_pinned_databases() -> None:
    # Architecture §8.3, §8.15: the name and the address of the text of version 1.0.
    assert ODC_BY_1_0 == DatabaseLicence(
        name="Open Data Commons Attribution License v1.0",
        url="https://opendatacommons.org/licenses/by/1-0/",
    )
    assert MITDB.licence is ODC_BY_1_0
    assert NSTDB.licence is ODC_BY_1_0


def test_licence_fields_and_database_fields() -> None:
    assert [field.name for field in dataclasses.fields(DatabaseLicence)] == ["name", "url"]
    fields = dataclasses.fields(Database)
    assert [field.name for field in fields] == [
        "slug",
        "version",
        "title",
        "checksum_list_sha256",
        "licence",
    ]
    # No default: every database names its licence.
    assert fields[-1].default is dataclasses.MISSING
    assert fields[-1].default_factory is dataclasses.MISSING
    with pytest.raises(TypeError, match="licence"):
        Database("fixdb", "1.0.0", "Fixture", DIGEST_A)  # type: ignore[call-arg]


def test_licence_is_frozen() -> None:
    with pytest.raises(AttributeError):
        ODC_BY_1_0.url = "https://licences.example/"  # type: ignore[misc]


@pytest.mark.parametrize("database", [MITDB, NSTDB])
def test_pinned_digests_are_64_lowercase_hex_digits(database: Database) -> None:
    digest = database.checksum_list_sha256
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_database_is_frozen() -> None:
    with pytest.raises(AttributeError):
        MITDB.slug = "other"  # type: ignore[misc]


def test_database_url() -> None:
    assert database_url(MITDB) == "https://physionet.org/files/mitdb/1.0.0/"
    assert database_url(NSTDB) == "https://physionet.org/files/nstdb/1.0.0/"
    database = Database("abc", "2.1.0", "T", DIGEST_A, LICENCE)
    assert database_url(database).endswith("/files/abc/2.1.0/")


# fetch_https (the network is replaced)


@pytest.mark.parametrize(
    "url",
    [
        "http://physionet.org/files/mitdb/1.0.0/100.hea",
        "ftp://physionet.org/files",
        "file:///etc/passwd",
        "HTTPS://physionet.org/files",
        " https://physionet.org/files",
        "physionet.org/files",
        "",
    ],
)
def test_fetch_https_rejects_other_urls_without_opening_them(url: str) -> None:
    with pytest.raises(ValueError, match="https://") as caught:
        fetch_https(url)
    assert isinstance(caught.value, InvalidInputError)
    assert not isinstance(caught.value, OSError)


class _Response:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_fetch_https_returns_the_body_and_uses_a_60_s_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, float]] = []

    def urlopen(url: str, timeout: float) -> _Response:
        calls.append((url, timeout))
        return _Response(200, b"content")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert fetch_https("https://example.org/a") == b"content"
    assert calls == [("https://example.org/a", 60)]


@pytest.mark.parametrize("status", [201, 204, 206, 304])
def test_fetch_https_raises_os_error_for_a_status_other_than_200(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: _Response(status, b"x"))
    with pytest.raises(OSError, match=f"HTTP status {status}"):
        fetch_https("https://example.org/a")


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.URLError("no route"),
        TimeoutError("timed out"),
        ConnectionResetError("reset"),
        http.client.IncompleteRead(b"partial"),
        http.client.RemoteDisconnected("closed"),
    ],
)
def test_fetch_https_raises_os_error_for_any_failure(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def urlopen(url: str, timeout: float) -> _Response:
        raise failure

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(OSError):
        fetch_https("https://example.org/a")


def test_http_error_is_an_os_error() -> None:
    assert issubclass(urllib.error.HTTPError, OSError)
    assert issubclass(urllib.error.URLError, OSError)


# parse_checksum_list


@pytest.mark.parametrize(
    "line",
    [
        f"{DIGEST_A} 100.dat",  # as PhysioNet writes it
        f"{DIGEST_A}  100.dat",  # sha256sum, text mode
        f"{DIGEST_A} *100.dat",  # sha256sum, binary mode
    ],
)
def test_parse_accepts_the_sha256sum_formats(line: str) -> None:
    assert parse_checksum_list(line + "\n", "list") == {"100.dat": DIGEST_A}


def test_parse_keeps_the_order_and_lowercases_the_digests() -> None:
    text = f"{DIGEST_B.upper()} b/z.txt\n{DIGEST_A} a.txt\n{DIGEST_B} RECORDS\n"
    parsed = parse_checksum_list(text, "list")
    assert list(parsed.items()) == [
        ("b/z.txt", DIGEST_B),
        ("a.txt", DIGEST_A),
        ("RECORDS", DIGEST_B),
    ]


def test_parse_skips_empty_lines_and_needs_no_final_line_feed() -> None:
    text = f"\n{DIGEST_A} a\n\n\n{DIGEST_B} b"
    assert parse_checksum_list(text, "list") == {"a": DIGEST_A, "b": DIGEST_B}


def test_parse_accepts_carriage_return_line_feed() -> None:
    text = f"{DIGEST_A} a\r\n\r\n{DIGEST_B} b\r\n"
    assert parse_checksum_list(text, "list") == {"a": DIGEST_A, "b": DIGEST_B}


@pytest.mark.parametrize(
    "path",
    ["100.dat", "x_mitdb/x_108.dat", "a/b/c/d.e", "A-Z_a+z.0-9", "...", ".hidden", "a..b"],
)
def test_parse_accepts_safe_paths(path: str) -> None:
    assert parse_checksum_list(f"{DIGEST_A} {path}\n", "list") == {path: DIGEST_A}


@pytest.mark.parametrize(
    "line",
    [
        "a" * 63 + " 100.dat",  # digest too short
        "a" * 65 + " 100.dat",  # digest too long
        "g" * 64 + " 100.dat",  # not hexadecimal
        DIGEST_A,  # no path
        DIGEST_A + " ",  # no path
        DIGEST_A + "100.dat",  # no separator
        DIGEST_A + "\t100.dat",  # tab separator
        DIGEST_A + "   100.dat",  # three spaces
        DIGEST_A + " 100.dat ",  # trailing space
        DIGEST_A + " my file.dat",  # space in the path
        " " + DIGEST_A + " 100.dat",  # leading space
        " ",  # a line that is not empty
        "100.dat " + DIGEST_A,  # reversed
        "# comment",
    ],
)
def test_parse_rejects_a_line_that_is_not_an_entry(line: str) -> None:
    text = f"{DIGEST_B} first\n{line}\n{DIGEST_B} last\n"
    with pytest.raises(MalformedFileError) as caught:
        parse_checksum_list(text, "the/list")
    assert caught.value.path == "the/list"
    assert caught.value.line == 2
    assert "not a checksum entry" in caught.value.reason
    assert str(caught.value).startswith("the/list, line 2: ")


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../outside",
        "a/../../outside",
        "a/..",
        "./a",
        "a/./b",
        ".",
        "..",
        "a//b",
        "a/",
        "a\\b",
        "..\\outside",
        "C:/windows/x",
        "C:x",
        "~/x",
        # "~" is what keeps the temporary files of the download apart from listed files.
        "a~b",
        "100.dat.part~",
        "SHA256SUMS.txt.part~",
        "sub/100.dat.part~",
        "a?b",
        "a*",
        "é.dat",
        "a\x00b",
    ],
)
def test_parse_rejects_an_unsafe_path(path: str) -> None:
    text = f"\n{DIGEST_B} good\n{DIGEST_A} {path}\n"
    with pytest.raises(MalformedFileError) as caught:
        parse_checksum_list(text, "SHA256SUMS.txt")
    assert caught.value.path == "SHA256SUMS.txt"
    assert caught.value.line == 3
    assert caught.value.reason == f"unsafe path: {path!r}"


def test_parse_rejects_a_duplicate_path_at_its_second_line() -> None:
    text = f"{DIGEST_A} a\n{DIGEST_B} b\n\n{DIGEST_B} a\n"
    with pytest.raises(MalformedFileError) as caught:
        parse_checksum_list(text, "list")
    assert caught.value.line == 4
    assert caught.value.reason == "duplicate path: a"


def test_parse_rejects_a_duplicate_with_the_same_digest() -> None:
    with pytest.raises(MalformedFileError, match="duplicate path: a"):
        parse_checksum_list(f"{DIGEST_A} a\n{DIGEST_A} *a\n", "list")


@pytest.mark.parametrize("text", ["", "\n", "\n\n\n", "\r\n\r\n"])
def test_parse_rejects_an_empty_list_without_a_line_number(text: str) -> None:
    with pytest.raises(MalformedFileError) as caught:
        parse_checksum_list(text, "empty.txt")
    assert caught.value.path == "empty.txt"
    assert caught.value.line is None
    assert str(caught.value) == "empty.txt: the checksum list has no entry"


def test_parse_error_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        parse_checksum_list("nonsense\n", "list")


# select_files

CHECKSUMS: Mapping[str, str] = {
    "RECORDS": DIGEST_A,
    "100.hea": DIGEST_A,
    "100.dat": DIGEST_A,
    "100.atr": DIGEST_A,
    "100.xws": DIGEST_A,
    "100-0.atr": DIGEST_A,
    "1000.dat": DIGEST_A,
    "100": DIGEST_A,
    "100.": DIGEST_A,
    "x100.dat": DIGEST_A,
    "sub/100.dat": DIGEST_A,
    "203.at-": DIGEST_A,
    "203.dat": DIGEST_A,
    "118e_6.dat": DIGEST_A,
}


def test_select_whole_database_is_every_listed_path_sorted() -> None:
    selected = select_files(CHECKSUMS, None)
    assert selected == tuple(sorted(CHECKSUMS))
    assert selected[0] == "100"
    assert selected[-1] == "x100.dat"


def test_select_record_takes_its_top_level_files_only() -> None:
    assert select_files(CHECKSUMS, ["100"]) == ("100.atr", "100.dat", "100.hea", "100.xws")


def test_select_several_records_sorted_in_code_point_order() -> None:
    assert select_files(CHECKSUMS, ["203", "118e_6", "100"]) == (
        "100.atr",
        "100.dat",
        "100.hea",
        "100.xws",
        "118e_6.dat",
        "203.at-",
        "203.dat",
    )


def test_select_record_repeated_gives_each_file_once() -> None:
    assert select_files(CHECKSUMS, ("203", "203")) == ("203.at-", "203.dat")


def test_select_record_without_files_gives_a_placeholder() -> None:
    assert select_files(CHECKSUMS, ["999"]) == ("999.*",)
    assert select_files(CHECKSUMS, ["203", "999", "10"]) == ("10.*", "203.at-", "203.dat", "999.*")


def test_select_record_known_only_in_a_subfolder_gives_a_placeholder() -> None:
    assert select_files({"sub/5.dat": DIGEST_A, "5": DIGEST_A}, ["5"]) == ("5.*",)


@pytest.mark.parametrize("records", [[], ()])
def test_select_rejects_an_empty_selection(records: Sequence[str]) -> None:
    with pytest.raises(InvalidInputError):
        select_files(CHECKSUMS, records)


def test_select_empty_selection_message() -> None:
    with pytest.raises(InvalidInputError) as caught:
        select_files(CHECKSUMS, [])
    assert str(caught.value) == "no record name given: the record selection is empty"


def test_select_selects_any_extension_of_a_record() -> None:
    checksums = {"108.at_": DIGEST_A, "108.dat": DIGEST_A, "108.hea": DIGEST_A, "1080.x": DIGEST_A}
    assert select_files(checksums, ["108"]) == ("108.at_", "108.dat", "108.hea")


@pytest.mark.parametrize(
    "name", ["", "10.0", "a/b", "../x", "a b", "100*", "100-0", "é", "100\n", ".", "a\\b"]
)
def test_select_rejects_an_invalid_record_name(name: str) -> None:
    with pytest.raises(InvalidInputError, match="invalid record name") as caught:
        select_files(CHECKSUMS, ["100", name])
    assert repr(name) in str(caught.value)


def test_select_rejects_a_record_name_that_is_not_a_string() -> None:
    with pytest.raises(InvalidInputError, match="invalid record name: 100"):
        select_files(CHECKSUMS, [100])  # type: ignore[list-item]


def test_select_rejects_a_string_in_place_of_the_sequence() -> None:
    with pytest.raises(InvalidInputError, match="not a sequence of record names"):
        select_files(CHECKSUMS, "100")


def test_select_checks_the_string_first_then_the_empty_sequence_then_each_name() -> None:
    with pytest.raises(InvalidInputError, match="not a sequence of record names"):
        select_files(CHECKSUMS, "")
    with pytest.raises(InvalidInputError, match="invalid record name: 'a/b'"):
        select_files(CHECKSUMS, ["100", "a/b", "c/d"])


def test_select_accepts_a_list_or_a_tuple_of_names() -> None:
    assert select_files(CHECKSUMS, ["203"]) == select_files(CHECKSUMS, ("203",))


def test_select_is_never_empty_for_a_parsed_list() -> None:
    checksums = parse_checksum_list(f"{DIGEST_A} only.txt\n", "list")
    assert select_files(checksums, None) == ("only.txt",)
    assert select_files(checksums, ["100"]) == ("100.*",)


# verify_database


def test_verify_whole_database(tmp_path: Path) -> None:
    database = fixture_database()
    write_database(tmp_path, database)
    result = verify_database(database, tmp_path)
    assert result == VerificationResult(database=database, records=None, files=tuple(sorted(FILES)))


def test_verify_accepts_the_data_root_as_a_string(tmp_path: Path) -> None:
    database = fixture_database()
    write_database(tmp_path, database)
    assert verify_database(database, str(tmp_path)).records is None  # type: ignore[arg-type]


def test_verify_subset_of_records(tmp_path: Path) -> None:
    database = fixture_database()
    write_database(tmp_path, database)
    result = verify_database(database, tmp_path, records=["101", "100", "101"])
    assert result.records == ("100", "101")
    assert result.files == ("100.atr", "100.dat", "100.hea", "101.dat", "101.hea")


def test_verify_subset_ignores_damage_to_other_files(tmp_path: Path) -> None:
    database = fixture_database()
    folder = write_database(tmp_path, database)
    (folder / "101.dat").write_bytes(b"altered")
    (folder / "RECORDS").unlink()
    assert verify_database(database, tmp_path, records=["100"]).files == (
        "100.atr",
        "100.dat",
        "100.hea",
    )


def test_verify_without_the_database_folder_names_the_list_as_missing(tmp_path: Path) -> None:
    database = fixture_database()
    with pytest.raises(DataVerificationError) as caught:
        verify_database(database, tmp_path)
    assert caught.value.database == "fixdb 1.0.0"
    assert caught.value.missing == ("SHA256SUMS.txt",)
    assert caught.value.mismatched == ()
    assert str(caught.value) == "fixdb 1.0.0 not verified: missing: SHA256SUMS.txt"


def test_verify_without_the_list_names_it_as_missing(tmp_path: Path) -> None:
    database = fixture_database()
    folder = write_database(tmp_path, database)
    (folder / CHECKSUM_LIST_NAME).unlink()
    with pytest.raises(DataVerificationError) as caught:
        verify_database(database, tmp_path)
    assert (caught.value.missing, caught.value.mismatched) == (("SHA256SUMS.txt",), ())


def test_verify_with_a_folder_in_place_of_the_list_names_it_as_missing(tmp_path: Path) -> None:
    database = fixture_database()
    (tmp_path / database.slug / CHECKSUM_LIST_NAME).mkdir(parents=True)
    with pytest.raises(DataVerificationError) as caught:
        verify_database(database, tmp_path)
    assert caught.value.missing == ("SHA256SUMS.txt",)


def test_verify_with_an_altered_list_names_it_as_mismatched(tmp_path: Path) -> None:
    database = fixture_database()
    folder = write_database(tmp_path, database)
    altered = dict(FILES) | {"100.dat": b"altered"}
    (folder / "100.dat").write_bytes(altered["100.dat"])
    # The list is consistent with the files, but it is not the pinned one.
    (folder / CHECKSUM_LIST_NAME).write_bytes(checksum_list(altered))
    with pytest.raises(DataVerificationError) as caught:
        verify_database(database, tmp_path)
    assert (caught.value.missing, caught.value.mismatched) == ((), ("SHA256SUMS.txt",))
    assert str(caught.value) == "fixdb 1.0.0 not verified: checksum mismatch: SHA256SUMS.txt"


def test_verify_names_every_missing_and_altered_file_sorted(tmp_path: Path) -> None:
    database = fixture_database()
    folder = write_database(tmp_path, database)
    (folder / "docs" / "notes.txt").write_bytes(b"altered")
    (folder / "100.hea").write_bytes(b"altered")
    (folder / "RECORDS").unlink()
    (folder / "100.atr").unlink()
    (folder / "docs" / "deep" / "100.dat").unlink()
    with pytest.raises(DataVerificationError) as caught:
        verify_database(database, tmp_path)
    assert caught.value.missing == ("100.atr", "RECORDS", "docs/deep/100.dat")
    assert caught.value.mismatched == ("100.hea", "docs/notes.txt")
    assert str(caught.value) == (
        "fixdb 1.0.0 not verified: missing: 100.atr, RECORDS, docs/deep/100.dat; "
        "checksum mismatch: 100.hea, docs/notes.txt"
    )


def test_verify_a_folder_in_place_of_a_file_is_missing(tmp_path: Path) -> None:
    database = fixture_database()
    folder = write_database(tmp_path, database)
    (folder / "100.dat").unlink()
    (folder / "100.dat").mkdir()
    with pytest.raises(DataVerificationError) as caught:
        verify_database(database, tmp_path)
    assert (caught.value.missing, caught.value.mismatched) == (("100.dat",), ())


def test_verify_a_truncated_or_extended_file_is_mismatched(tmp_path: Path) -> None:
    database = fixture_database()
    folder = write_database(tmp_path, database)
    (folder / "100.dat").write_bytes(FILES["100.dat"][:-1])
    (folder / "101.dat").write_bytes(FILES["101.dat"] + b"\n")
    (folder / "101.hea").write_bytes(b"")
    with pytest.raises(DataVerificationError) as caught:
        verify_database(database, tmp_path)
    assert caught.value.mismatched == ("100.dat", "101.dat", "101.hea")


def test_verify_ignores_files_that_the_list_does_not_name(tmp_path: Path) -> None:
    database = fixture_database()
    folder = write_database(tmp_path, database)
    (folder / "extra.dat").write_bytes(b"extra")
    (folder / "100.dat.part").write_bytes(b"stale")
    result = verify_database(database, tmp_path)
    assert result.files == tuple(sorted(FILES))


def test_verify_a_record_without_listed_files_is_missing_as_a_placeholder(tmp_path: Path) -> None:
    database = fixture_database()
    write_database(tmp_path, database)
    with pytest.raises(DataVerificationError) as caught:
        verify_database(database, tmp_path, records=["100", "999"])
    assert (caught.value.missing, caught.value.mismatched) == (("999.*",), ())


def test_verify_hashes_a_file_larger_than_one_block(tmp_path: Path) -> None:
    big = bytes(range(256)) * 4096 * 2 + b"tail"  # 2 MiB and 4 bytes
    files = {"big.dat": big, "empty.dat": b""}
    database = fixture_database(files)
    folder = write_database(tmp_path, database, files)
    assert verify_database(database, tmp_path).files == ("big.dat", "empty.dat")
    (folder / "big.dat").write_bytes(big[:-1] + b"L")
    with pytest.raises(DataVerificationError) as caught:
        verify_database(database, tmp_path)
    assert caught.value.mismatched == ("big.dat",)


def test_verify_rejects_an_invalid_record_name(tmp_path: Path) -> None:
    database = fixture_database()
    write_database(tmp_path, database)
    with pytest.raises(InvalidInputError, match="invalid record name"):
        verify_database(database, tmp_path, records=["../100"])


def test_verify_rejects_an_invalid_record_name_without_the_folder_or_the_list(
    tmp_path: Path,
) -> None:
    database = fixture_database()
    # Without the data folder, then without the checksum list: the selection is checked
    # before the list is read, so the error is not a DataVerificationError.
    with pytest.raises(InvalidInputError, match="invalid record name"):
        verify_database(database, tmp_path / "absent", records=["../100"])
    (tmp_path / database.slug).mkdir()
    with pytest.raises(InvalidInputError, match="invalid record name"):
        verify_database(database, tmp_path, records=["../100"])
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("records", [[], ()])
def test_verify_rejects_an_empty_selection(tmp_path: Path, records: Sequence[str]) -> None:
    database = fixture_database()
    write_database(tmp_path, database)
    with pytest.raises(InvalidInputError, match="the record selection is empty"):
        verify_database(database, tmp_path, records=records)


def test_verify_reports_a_pinned_list_that_is_malformed(tmp_path: Path) -> None:
    content = f"{DIGEST_A} good\nnot an entry\n".encode()
    database = Database("fixdb", "1.0.0", "Fixture", sha256(content), LICENCE)
    list_path = tmp_path / "fixdb" / CHECKSUM_LIST_NAME
    list_path.parent.mkdir()
    list_path.write_bytes(content)
    with pytest.raises(MalformedFileError) as caught:
        verify_database(database, tmp_path)
    assert caught.value.path == str(list_path)
    assert caught.value.line == 2


def test_verify_reports_a_pinned_list_that_is_not_utf8(tmp_path: Path) -> None:
    content = b"\xff\xfe not text\n"
    database = Database("fixdb", "1.0.0", "Fixture", sha256(content), LICENCE)
    list_path = tmp_path / "fixdb" / CHECKSUM_LIST_NAME
    list_path.parent.mkdir()
    list_path.write_bytes(content)
    with pytest.raises(MalformedFileError) as caught:
        verify_database(database, tmp_path)
    assert (caught.value.path, caught.value.line) == (str(list_path), None)
    assert caught.value.reason == "not UTF-8 text"


def test_verify_a_list_written_with_carriage_returns(tmp_path: Path) -> None:
    files = {"a.dat": b"a", "b.dat": b"b"}
    content = checksum_list(files).replace(b"\n", b"\r\n")
    database = Database("fixdb", "1.0.0", "Fixture", sha256(content), LICENCE)
    folder = write_database(tmp_path, database, files)
    (folder / CHECKSUM_LIST_NAME).write_bytes(content)
    assert verify_database(database, tmp_path).files == ("a.dat", "b.dat")


def test_verify_writes_nothing(tmp_path: Path) -> None:
    database = fixture_database()
    folder = write_database(tmp_path, database)
    before = tree(folder)
    verify_database(database, tmp_path)
    assert tree(folder) == before


# download_database


def test_download_whole_database_into_an_empty_data_folder(tmp_path: Path) -> None:
    database = fixture_database()
    fetch = FakeFetch(served(database))
    data_root = tmp_path / "data"
    result = download_database(database, data_root, fetch=fetch)
    assert result == VerificationResult(database=database, records=None, files=tuple(sorted(FILES)))
    assert tree(data_root / "fixdb") == dict(FILES) | {CHECKSUM_LIST_NAME: checksum_list(FILES)}
    base = "https://physionet.org/files/fixdb/1.0.0/"
    assert fetch.urls == [base + CHECKSUM_LIST_NAME] + [base + path for path in sorted(FILES)]


def test_download_again_fetches_nothing(tmp_path: Path) -> None:
    database = fixture_database()
    download_database(database, tmp_path, fetch=FakeFetch(served(database)))
    offline = FakeFetch({})
    result = download_database(database, tmp_path, fetch=offline)
    assert offline.urls == []
    assert result.files == tuple(sorted(FILES))


def test_download_fetches_only_what_is_missing_or_outdated(tmp_path: Path) -> None:
    database = fixture_database()
    folder = write_database(tmp_path, database)
    (folder / "100.dat").write_bytes(b"outdated")
    (folder / "docs" / "notes.txt").unlink()
    fetch = FakeFetch(served(database))
    download_database(database, tmp_path, fetch=fetch)
    base = database_url(database)
    assert fetch.urls == [base + "100.dat", base + "docs/notes.txt"]
    assert tree(folder) == dict(FILES) | {CHECKSUM_LIST_NAME: checksum_list(FILES)}


def test_download_replaces_a_local_list_that_is_not_the_pinned_one(tmp_path: Path) -> None:
    database = fixture_database()
    folder = write_database(tmp_path, database)
    (folder / CHECKSUM_LIST_NAME).write_bytes(b"something else\n")
    fetch = FakeFetch(served(database))
    download_database(database, tmp_path, fetch=fetch)
    assert fetch.urls == [database_url(database) + CHECKSUM_LIST_NAME]
    assert (folder / CHECKSUM_LIST_NAME).read_bytes() == checksum_list(FILES)


def test_download_list_that_cannot_be_fetched_is_missing(tmp_path: Path) -> None:
    database = fixture_database()
    fetch = FakeFetch({})
    with pytest.raises(DataVerificationError) as caught:
        download_database(database, tmp_path, fetch=fetch)
    assert (caught.value.missing, caught.value.mismatched) == (("SHA256SUMS.txt",), ())
    assert isinstance(caught.value.__cause__, OSError)
    assert fetch.urls == [database_url(database) + CHECKSUM_LIST_NAME]
    assert tree(tmp_path / "fixdb") == {}


def test_download_list_that_cannot_be_fetched_is_missing_even_with_a_wrong_local_list(
    tmp_path: Path,
) -> None:
    database = fixture_database()
    folder = tmp_path / "fixdb"
    folder.mkdir()
    (folder / CHECKSUM_LIST_NAME).write_bytes(b"wrong\n")
    with pytest.raises(DataVerificationError) as caught:
        download_database(database, tmp_path, fetch=FakeFetch({}))
    assert (caught.value.missing, caught.value.mismatched) == (("SHA256SUMS.txt",), ())
    assert tree(folder) == {CHECKSUM_LIST_NAME: b"wrong\n"}


def test_download_fetched_list_with_another_digest_is_mismatched_and_not_written(
    tmp_path: Path,
) -> None:
    database = fixture_database()
    content = served(database)
    content[database_url(database) + CHECKSUM_LIST_NAME] = checksum_list({"100.dat": b"forged"})
    fetch = FakeFetch(content)
    with pytest.raises(DataVerificationError) as caught:
        download_database(database, tmp_path, fetch=fetch)
    assert (caught.value.missing, caught.value.mismatched) == ((), ("SHA256SUMS.txt",))
    assert str(caught.value) == "fixdb 1.0.0 not verified: checksum mismatch: SHA256SUMS.txt"
    # Nothing is written, and no file is requested after the list.
    assert (tmp_path / "fixdb").is_dir()
    assert tree(tmp_path / "fixdb") == {}
    assert fetch.urls == [database_url(database) + CHECKSUM_LIST_NAME]


def test_download_fetched_list_with_another_digest_leaves_the_local_list(tmp_path: Path) -> None:
    database = fixture_database()
    folder = tmp_path / "fixdb"
    folder.mkdir()
    (folder / CHECKSUM_LIST_NAME).write_bytes(b"local\n")
    forged = {database_url(database) + CHECKSUM_LIST_NAME: b"forged\n"}
    with pytest.raises(DataVerificationError) as caught:
        download_database(database, tmp_path, fetch=FakeFetch(forged))
    assert caught.value.mismatched == ("SHA256SUMS.txt",)
    assert tree(folder) == {CHECKSUM_LIST_NAME: b"local\n"}


def test_download_file_that_cannot_be_fetched_is_named_by_the_final_verification(
    tmp_path: Path,
) -> None:
    database = fixture_database()
    content = served(database)
    base = database_url(database)
    del content[base + "100.dat"]
    del content[base + "docs/notes.txt"]
    fetch = FakeFetch(content)
    with pytest.raises(DataVerificationError) as caught:
        download_database(database, tmp_path, fetch=fetch)
    assert caught.value.missing == ("100.dat", "docs/notes.txt")
    assert caught.value.mismatched == ()
    # Every file was tried once, and the others were written.
    assert fetch.urls == [base + CHECKSUM_LIST_NAME] + [base + path for path in sorted(FILES)]
    expected = {path: body for path, body in FILES.items() if path not in caught.value.missing}
    assert tree(tmp_path / "fixdb") == expected | {CHECKSUM_LIST_NAME: checksum_list(FILES)}


def test_download_outdated_file_that_cannot_be_fetched_stays_and_is_mismatched(
    tmp_path: Path,
) -> None:
    database = fixture_database()
    folder = write_database(tmp_path, database)
    (folder / "100.dat").write_bytes(b"outdated")
    with pytest.raises(DataVerificationError) as caught:
        download_database(database, tmp_path, fetch=FakeFetch({}))
    assert (caught.value.missing, caught.value.mismatched) == ((), ("100.dat",))
    assert (folder / "100.dat").read_bytes() == b"outdated"


def test_download_file_served_with_other_content_is_mismatched(tmp_path: Path) -> None:
    database = fixture_database()
    content = served(database)
    content[database_url(database) + "101.hea"] = b"an error page"
    with pytest.raises(DataVerificationError) as caught:
        download_database(database, tmp_path, fetch=FakeFetch(content))
    assert (caught.value.missing, caught.value.mismatched) == ((), ("101.hea",))


def test_download_resumes_after_a_failed_run(tmp_path: Path) -> None:
    database = fixture_database()
    content = served(database)
    base = database_url(database)
    partial = {url: body for url, body in content.items() if not url.endswith("100.dat")}
    with pytest.raises(DataVerificationError):
        download_database(database, tmp_path, fetch=FakeFetch(partial))
    fetch = FakeFetch(content)
    result = download_database(database, tmp_path, fetch=fetch)
    assert fetch.urls == [base + "100.dat", base + "docs/deep/100.dat"]
    assert result.files == tuple(sorted(FILES))


def test_download_overwrites_stale_part_files_and_leaves_none(tmp_path: Path) -> None:
    database = fixture_database()
    folder = tmp_path / "fixdb"
    (folder / "docs").mkdir(parents=True)
    (folder / "100.dat.part~").write_bytes(b"stale and longer than the real file content")
    (folder / "docs" / "notes.txt.part~").write_bytes(b"stale")
    (folder / "SHA256SUMS.txt.part~").write_bytes(b"stale")
    download_database(database, tmp_path, fetch=FakeFetch(served(database)))
    assert tree(folder) == dict(FILES) | {CHECKSUM_LIST_NAME: checksum_list(FILES)}
    assert list(folder.rglob("*.part~")) == []


def test_download_leaves_a_part_file_of_the_former_suffix_alone(tmp_path: Path) -> None:
    # A file named <name>.part, left by a version that used that suffix, is not listed: it is
    # neither used, nor verified, nor removed.
    database = fixture_database()
    folder = tmp_path / "fixdb"
    folder.mkdir()
    (folder / "100.dat.part").write_bytes(b"left by an older version")
    result = download_database(database, tmp_path, fetch=FakeFetch(served(database)))
    assert result.files == tuple(sorted(FILES))
    assert (folder / "100.dat.part").read_bytes() == b"left by an older version"
    assert (folder / "100.dat").read_bytes() == FILES["100.dat"]


COLLIDING_FILES: Mapping[str, bytes] = {
    "a.dat": b"samples of a",
    "a.dat.part": b"a listed file whose name ends with .part",
    "sub/b.hea": b"header of b",
    "sub/b.hea.part": b"another one, in a subfolder",
}


def test_download_a_list_that_names_a_file_and_its_part_name(tmp_path: Path) -> None:
    database = fixture_database(COLLIDING_FILES)
    fetch = FakeFetch(served(database, COLLIDING_FILES))
    result = download_database(database, tmp_path, fetch=fetch)
    assert result.files == ("a.dat", "a.dat.part", "sub/b.hea", "sub/b.hea.part")
    expected = dict(COLLIDING_FILES) | {CHECKSUM_LIST_NAME: checksum_list(COLLIDING_FILES)}
    assert tree(tmp_path / database.slug) == expected


def test_download_refetching_a_file_keeps_the_listed_file_of_its_part_name(
    tmp_path: Path,
) -> None:
    # With ".part" as the suffix, writing a.dat again would go through a.dat.part, a verified
    # listed file, and remove it. The server offers only the two files to fetch again.
    database = fixture_database(COLLIDING_FILES)
    folder = write_database(tmp_path, database, COLLIDING_FILES)
    (folder / "a.dat").write_bytes(b"outdated")
    (folder / "sub" / "b.hea").unlink()
    base = database_url(database)
    fetch = FakeFetch(
        {base + "a.dat": COLLIDING_FILES["a.dat"], base + "sub/b.hea": COLLIDING_FILES["sub/b.hea"]}
    )
    result = download_database(database, tmp_path, fetch=fetch)
    assert fetch.urls == [base + "a.dat", base + "sub/b.hea"]
    assert result.files == ("a.dat", "a.dat.part", "sub/b.hea", "sub/b.hea.part")
    expected = dict(COLLIDING_FILES) | {CHECKSUM_LIST_NAME: checksum_list(COLLIDING_FILES)}
    assert tree(folder) == expected


def test_download_writes_through_a_part_file_in_the_same_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = fixture_database()
    replaced: list[tuple[str, str, bytes]] = []
    real_replace = os.replace

    def replace(source: Path, target: Path) -> None:
        assert not Path(target).exists()
        replaced.append(
            (
                Path(source).relative_to(tmp_path).as_posix(),
                Path(target).relative_to(tmp_path).as_posix(),
                Path(source).read_bytes(),
            )
        )
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", replace)
    download_database(database, tmp_path, records=["101"], fetch=FakeFetch(served(database)))
    assert replaced == [
        ("fixdb/SHA256SUMS.txt.part~", "fixdb/SHA256SUMS.txt", checksum_list(FILES)),
        ("fixdb/101.dat.part~", "fixdb/101.dat", FILES["101.dat"]),
        ("fixdb/101.hea.part~", "fixdb/101.hea", FILES["101.hea"]),
    ]


def test_download_subset_fetches_only_the_files_of_the_records(tmp_path: Path) -> None:
    database = fixture_database()
    fetch = FakeFetch(served(database))
    result = download_database(database, tmp_path, records=("101", "100"), fetch=fetch)
    base = database_url(database)
    names = ["100.atr", "100.dat", "100.hea", "101.dat", "101.hea"]
    assert fetch.urls == [base + CHECKSUM_LIST_NAME] + [base + name for name in names]
    assert result.records == ("100", "101")
    assert result.files == tuple(names)
    assert sorted(tree(tmp_path / "fixdb")) == sorted([*names, CHECKSUM_LIST_NAME])


def test_download_never_fetches_the_placeholder_of_a_record_without_files(tmp_path: Path) -> None:
    database = fixture_database()
    fetch = FakeFetch(served(database))
    with pytest.raises(DataVerificationError) as caught:
        download_database(database, tmp_path, records=["101", "999"], fetch=fetch)
    assert (caught.value.missing, caught.value.mismatched) == (("999.*",), ())
    assert not any("999" in url for url in fetch.urls)
    assert (tmp_path / "fixdb" / "101.dat").read_bytes() == FILES["101.dat"]


def test_download_rejects_an_invalid_record_name(tmp_path: Path) -> None:
    database = fixture_database()
    data_root = tmp_path / "data"
    fetch = FakeFetch(served(database))
    with pytest.raises(InvalidInputError, match="invalid record name"):
        download_database(database, data_root, records=["a/b"], fetch=fetch)
    assert not data_root.exists()
    assert fetch.urls == []


@pytest.mark.parametrize("records", [[], ()])
def test_download_rejects_an_empty_selection(tmp_path: Path, records: Sequence[str]) -> None:
    database = fixture_database()
    data_root = tmp_path / "data"
    fetch = FakeFetch(served(database))
    with pytest.raises(InvalidInputError, match="the record selection is empty"):
        download_database(database, data_root, records=records, fetch=fetch)
    assert not data_root.exists()
    assert fetch.urls == []


def _failing_fetch(url: str) -> bytes:
    raise AssertionError(f"fetch called for a rejected selection: {url}")


def _snapshot(root: Path) -> dict[str, bytes | None]:
    """Every file and folder under ``root`` (a folder maps to ``None``)."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


_INVALID_SELECTIONS: list[Any] = [
    [],
    (),
    "100",
    "",
    ["../100"],
    ["100", "a/b"],
    ["100", ""],
    [100],
]

_DATA_FOLDER_STATES = [
    "no data folder",
    "no database folder",
    "no checksum list",
    "altered checksum list",
    "malformed pinned checksum list",
    "complete database",
]


def _prepare(state: str, tmp_path: Path) -> tuple[Database, Path]:
    """A database and a data folder in the given state."""
    data_root = tmp_path / "data"
    database = fixture_database()
    if state == "no data folder":
        return database, data_root
    data_root.mkdir()
    if state == "no database folder":
        return database, data_root
    folder = write_database(data_root, database)
    if state == "no checksum list":
        (folder / CHECKSUM_LIST_NAME).unlink()
    elif state == "altered checksum list":
        (folder / CHECKSUM_LIST_NAME).write_bytes(b"altered\n")
    elif state == "malformed pinned checksum list":
        content = b"not a checksum list\n"
        (folder / CHECKSUM_LIST_NAME).write_bytes(content)
        database = Database(database.slug, "1.0.0", "Fixture", sha256(content), LICENCE)
    return database, data_root


@pytest.mark.parametrize("state", _DATA_FOLDER_STATES)
@pytest.mark.parametrize("records", _INVALID_SELECTIONS)
def test_verify_validates_the_selection_before_reading_anything(
    tmp_path: Path, state: str, records: Any
) -> None:
    database, data_root = _prepare(state, tmp_path)
    before = _snapshot(tmp_path)
    with pytest.raises(InvalidInputError):
        verify_database(database, data_root, records=records)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("state", _DATA_FOLDER_STATES)
@pytest.mark.parametrize("records", _INVALID_SELECTIONS)
def test_download_validates_the_selection_before_any_folder_or_fetch(
    tmp_path: Path, state: str, records: Any
) -> None:
    database, data_root = _prepare(state, tmp_path)
    before = _snapshot(tmp_path)
    with pytest.raises(InvalidInputError):
        download_database(database, data_root, records=records, fetch=_failing_fetch)
    assert _snapshot(tmp_path) == before
    if state == "no data folder":
        assert not data_root.exists()


def test_download_lets_other_errors_of_the_fetch_function_through(tmp_path: Path) -> None:
    database = fixture_database()
    write_database(tmp_path, database)
    (tmp_path / "fixdb" / "100.dat").unlink()

    def fetch(url: str) -> bytes:
        raise RuntimeError("not an OSError")

    with pytest.raises(RuntimeError, match="not an OSError"):
        download_database(database, tmp_path, fetch=fetch)


def test_download_creates_the_data_folder_and_its_parents(tmp_path: Path) -> None:
    database = fixture_database()
    data_root = tmp_path / "a" / "b" / "data"
    download_database(database, data_root, fetch=FakeFetch(served(database)))
    assert (data_root / "fixdb" / "docs" / "deep" / "100.dat").is_file()


def test_download_uses_fetch_https_by_default() -> None:
    assert inspect.signature(download_database).parameters["fetch"].default is fetch_https


def test_download_keeps_two_databases_apart(tmp_path: Path) -> None:
    first = fixture_database(slug="one")
    other_files = {"118e24.dat": b"noisy", "118e24.hea": b"header"}
    second = fixture_database(other_files, slug="two")
    download_database(first, tmp_path, fetch=FakeFetch(served(first)))
    download_database(second, tmp_path, fetch=FakeFetch(served(second, other_files)))
    assert verify_database(first, tmp_path).files == tuple(sorted(FILES))
    assert verify_database(second, tmp_path, records=["118e24"]).files == (
        "118e24.dat",
        "118e24.hea",
    )


# describe_verification


def test_describe_whole_database() -> None:
    result = VerificationResult(database=MITDB, records=None, files=("100.atr", "100.dat"))
    assert describe_verification(result) == (
        "verified: 2 files match the published SHA-256 checksum list (SHA256SUMS.txt, SHA-256 "
        "b61158a96d5f2ca80edfb354a9a66a6324836c390a84e1966dcee2b907d6be43)"
    )


def test_describe_subset_names_the_records() -> None:
    result = VerificationResult(
        database=NSTDB, records=("118e24", "119e_6"), files=("118e24.dat", "119e_6.dat", "x")
    )
    assert describe_verification(result) == (
        "verified: 3 files match the published SHA-256 checksum list (SHA256SUMS.txt, SHA-256 "
        "b76bd98c5111439fcfff2f410afd70d64e79f072049c45b5a9916a3044fdb84f); "
        "records 118e24, 119e_6"
    )


def test_describe_the_result_of_a_verification(tmp_path: Path) -> None:
    database = fixture_database()
    write_database(tmp_path, database)
    whole = describe_verification(verify_database(database, tmp_path))
    subset = describe_verification(verify_database(database, tmp_path, records=["101"]))
    digest = database.checksum_list_sha256
    assert whole == (
        f"verified: 8 files match the published SHA-256 checksum list "
        f"(SHA256SUMS.txt, SHA-256 {digest})"
    )
    assert subset == (
        f"verified: 2 files match the published SHA-256 checksum list "
        f"(SHA256SUMS.txt, SHA-256 {digest}); records 101"
    )
