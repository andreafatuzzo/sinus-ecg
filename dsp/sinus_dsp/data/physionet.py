"""Download of a PhysioNet database version and its verification (architecture §8.3).

PhysioNet publishes each database version under ``https://physionet.org/files/<slug>/<version>/``
together with ``SHA256SUMS.txt``, the SHA-256 checksum list of its files. The digest of that list
is pinned here for each database, so the verification needs no network and cannot be misled by a
list altered in transit or on the server.

SRS-001 (MIT-BIH Arrhythmia Database) and SRS-013 (MIT-BIH Noise Stress Test Database): a database
is obtained into a local data folder, every file listed in its checksum list is verified, and a
missing or altered file makes the database not verified, with an error naming each such file.

Network access goes through an injectable fetch function, and the outcome is always decided by
the local verification, never by the download.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sinus_dsp.errors import DataVerificationError, InvalidInputError, MalformedFileError

PHYSIONET_FILES_URL: Final = "https://physionet.org/files"
CHECKSUM_LIST_NAME: Final = "SHA256SUMS.txt"

_FETCH_TIMEOUT_S: Final = 60
_HASH_BLOCK_BYTES: Final = 1024 * 1024
_PART_SUFFIX: Final = ".part"

# One entry of a checksum list, in the formats written by ``sha256sum``.
_ENTRY: Final = re.compile(r"^([0-9a-fA-F]{64}) [ *]?(\S+)$")
# One component of a listed path.
_PATH_COMPONENT: Final = re.compile(r"[A-Za-z0-9._+-]+")
_RECORD_NAME: Final = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class Database:
    """A database version published by PhysioNet.

    Attributes:
        slug: Folder name on PhysioNet and under the data folder, e.g. ``mitdb``.
        version: Version of the database, e.g. ``1.0.0``.
        title: Title of the database, e.g. ``MIT-BIH Arrhythmia Database``.
        checksum_list_sha256: Pinned SHA-256 of its ``SHA256SUMS.txt``, 64 lowercase hexadecimal
            digits.
    """

    slug: str
    version: str
    title: str
    checksum_list_sha256: str


#: SRS-001: version 1.0.0 of the MIT-BIH Arrhythmia Database, with the pinned digest of its
#: checksum list (704 files).
MITDB: Final[Database] = Database(
    slug="mitdb",
    version="1.0.0",
    title="MIT-BIH Arrhythmia Database",
    checksum_list_sha256="b61158a96d5f2ca80edfb354a9a66a6324836c390a84e1966dcee2b907d6be43",
)

#: SRS-013: version 1.0.0 of the MIT-BIH Noise Stress Test Database, with the pinned digest of
#: its checksum list (97 files).
NSTDB: Final[Database] = Database(
    slug="nstdb",
    version="1.0.0",
    title="MIT-BIH Noise Stress Test Database",
    checksum_list_sha256="b76bd98c5111439fcfff2f410afd70d64e79f072049c45b5a9916a3044fdb84f",
)

#: URL -> content of the file. It raises ``OSError`` on failure.
FetchFunction = Callable[[str], bytes]


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of a successful verification.

    Attributes:
        database: The database verified.
        records: The record names the verification was restricted to, sorted and without
            repetition, or ``None`` when the whole database was verified.
        files: Relative paths of the files verified, sorted in code-point order.
    """

    database: Database
    records: tuple[str, ...] | None
    files: tuple[str, ...]


def fetch_https(url: str) -> bytes:
    """Return the content served at an ``https://`` URL.

    SRS-001, SRS-013: the default way of obtaining a file from PhysioNet. There is no retry:
    running the download again resumes it, because verified files are skipped.

    Args:
        url: The URL. It must start with ``https://``.

    Returns:
        The whole body of the response.

    Raises:
        InvalidInputError: If ``url`` does not start with ``https://`` (a ``ValueError``).
        OSError: For any failure, including ``urllib.error.URLError`` and ``HTTPError``, and
            for a status other than 200.
    """
    if not url.startswith("https://"):
        raise InvalidInputError(f"URL does not start with https://: {url!r}")
    try:
        with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_S) as response:
            status = int(response.status)
            body = bytes(response.read())
    except http.client.HTTPException as error:
        raise OSError(f"{url}: {error!r}") from error
    if status != 200:
        raise OSError(f"{url}: HTTP status {status}")
    return body


def database_url(database: Database) -> str:
    """Return the URL of the folder of a database version, ending with ``/``.

    SRS-001, SRS-013: ``https://physionet.org/files/<slug>/<version>/``.
    """
    return f"{PHYSIONET_FILES_URL}/{database.slug}/{database.version}/"


def parse_checksum_list(text: str, source: str) -> dict[str, str]:
    """Parse a SHA-256 checksum list into a mapping from relative path to digest.

    SRS-001, SRS-013: the list names every file that the verification checks. There is one
    entry per non-empty line, ``<64 hexadecimal digits> <relative path>`` (the formats written
    by ``sha256sum``: one space, two spaces, or a space and ``*`` before the path). A path is
    relative, with ``/`` separators, and each of its components matches ``[A-Za-z0-9._+-]+``
    and differs from ``.`` and ``..``, so that a listed name cannot designate a file outside
    the database folder.

    Lines end with a line feed; a carriage return before it is not part of the line.

    Args:
        text: The content of the list.
        source: Name of the list in error messages, e.g. its path.

    Returns:
        The digests, in lowercase, by relative path, in the order of the list.

    Raises:
        MalformedFileError: For a line that is not an entry, an unsafe path or a duplicate
            path (with the 1-based line number), and for a list without any entry.
    """
    checksums: dict[str, str] = {}
    for number, raw_line in enumerate(text.split("\n"), start=1):
        line = raw_line.removesuffix("\r")
        if not line:
            continue
        entry = _ENTRY.fullmatch(line)
        if entry is None:
            raise MalformedFileError(
                source,
                number,
                "not a checksum entry: expected 64 hexadecimal digits, a space and a path",
            )
        digest = entry.group(1).lower()
        path = entry.group(2)
        if not _is_safe_path(path):
            raise MalformedFileError(source, number, f"unsafe path: {path!r}")
        if path in checksums:
            raise MalformedFileError(source, number, f"duplicate path: {path}")
        checksums[path] = digest
    if not checksums:
        raise MalformedFileError(source, None, "the checksum list has no entry")
    return checksums


def select_files(checksums: Mapping[str, str], records: Sequence[str] | None) -> tuple[str, ...]:
    """Select the listed files of the whole database or of some of its records.

    SRS-001, SRS-013: with ``records`` equal to ``None``, every listed file is selected.
    Otherwise the selection holds, for each record, the listed top-level files named
    ``<record>.<extension>`` (e.g. ``100.atr``, ``100.dat``, ``100.hea``, ``100.xws``). A
    record with no such file is selected under the placeholder ``<record>.*``, which no file
    can have as its name, so that the verification reports it as missing.

    Args:
        checksums: The parsed checksum list.
        records: Record names, each matching ``[A-Za-z0-9_]+``, or ``None`` for the whole
            database.

    Returns:
        The relative paths, sorted in code-point order, each one once.

    Raises:
        InvalidInputError: If a record name is invalid.
    """
    if records is None:
        return tuple(sorted(checksums))
    selected: set[str] = set()
    for record in _record_names(records):
        prefix = record + "."
        files = [
            path
            for path in checksums
            if "/" not in path and path.startswith(prefix) and len(path) > len(prefix)
        ]
        if files:
            selected.update(files)
        else:
            selected.add(prefix + "*")
    return tuple(sorted(selected))


def verify_database(
    database: Database, data_root: Path, *, records: Sequence[str] | None = None
) -> VerificationResult:
    """Verify the local copy of a database, or of some of its records, without the network.

    SRS-001, SRS-013: every selected file listed in the checksum list must be present with
    the listed SHA-256. The checksum list itself must be present with its pinned SHA-256.

    1. ``data_root/<slug>/SHA256SUMS.txt`` is read; it is missing if absent and mismatched if
       its SHA-256 differs from ``database.checksum_list_sha256``.
    2. The list is parsed and the files are selected (:func:`select_files`).
    3. The SHA-256 of each selected file is computed. A path that is not a regular file is
       missing; a digest that differs is a mismatch.
    4. Anything missing or mismatched raises, naming every such file.

    A file on disk that the list does not name is ignored.

    Args:
        database: The database to verify.
        data_root: The data folder; the database is in ``data_root / database.slug``.
        records: Record names to restrict the verification to, or ``None`` for every file.

    Returns:
        The database, the records and the files verified.

    Raises:
        DataVerificationError: If the checksum list or a selected file is missing or does not
            have the expected SHA-256. ``missing`` and ``mismatched`` are complete and sorted.
        MalformedFileError: If the checksum list does not follow its format.
        InvalidInputError: If a record name is invalid.
    """
    folder = Path(data_root) / database.slug
    list_path = folder / CHECKSUM_LIST_NAME
    content = _read_if_file(list_path)
    if content is None:
        raise DataVerificationError(_database_name(database), missing=(CHECKSUM_LIST_NAME,))
    if _sha256_bytes(content) != database.checksum_list_sha256:
        raise DataVerificationError(_database_name(database), mismatched=(CHECKSUM_LIST_NAME,))
    checksums = _parse_list_content(content, list_path)
    files = select_files(checksums, records)

    missing: list[str] = []
    mismatched: list[str] = []
    for path in files:
        expected = checksums.get(path)
        local = _local_path(folder, path)
        # A path that the list does not name is the placeholder of a record without files.
        if expected is None or not local.is_file():
            missing.append(path)
        elif _sha256_file(local) != expected:
            mismatched.append(path)
    if missing or mismatched:
        raise DataVerificationError(_database_name(database), missing, mismatched)
    return VerificationResult(
        database=database,
        records=None if records is None else _record_names(records),
        files=files,
    )


def download_database(
    database: Database,
    data_root: Path,
    *,
    records: Sequence[str] | None = None,
    fetch: FetchFunction = fetch_https,
) -> VerificationResult:
    """Obtain a database, or some of its records, into the data folder, and verify it.

    SRS-001, SRS-013: the files are obtained from PhysioNet and the outcome is the one of
    :func:`verify_database`, which this function calls last.

    The database folder ``data_root / database.slug`` is created, then:

    1. The local ``SHA256SUMS.txt`` is used if its SHA-256 equals the pinned one. Otherwise
       the list is fetched; it is written only if its SHA-256 equals the pinned one.
    2. Each selected file whose local copy does not have the listed SHA-256 is fetched and
       written atomically (to ``<name>.part`` in the same folder, then renamed), with its
       subfolders. A fetch that fails with ``OSError`` is not raised: the file stays absent
       or outdated. The placeholder of a record without files is never fetched.
    3. The local copy is verified.

    Args:
        database: The database to obtain.
        data_root: The data folder.
        records: Record names to restrict the download to, or ``None`` for every file.
        fetch: Function returning the content of a URL; it raises ``OSError`` on failure.

    Returns:
        The result of the final verification.

    Raises:
        DataVerificationError: If the checksum list cannot be fetched (it is named as
            missing), if the fetched list does not have the pinned SHA-256 (it is named as
            mismatched, and is not written), or if the final verification fails.
        MalformedFileError: If the checksum list does not follow its format.
        InvalidInputError: If a record name is invalid.
    """
    folder = Path(data_root) / database.slug
    folder.mkdir(parents=True, exist_ok=True)
    base_url = database_url(database)

    list_path = folder / CHECKSUM_LIST_NAME
    content = _read_if_file(list_path)
    if content is None or _sha256_bytes(content) != database.checksum_list_sha256:
        try:
            content = fetch(base_url + CHECKSUM_LIST_NAME)
        except OSError as error:
            raise DataVerificationError(
                _database_name(database), missing=(CHECKSUM_LIST_NAME,)
            ) from error
        if _sha256_bytes(content) != database.checksum_list_sha256:
            raise DataVerificationError(_database_name(database), mismatched=(CHECKSUM_LIST_NAME,))
        _write_atomically(list_path, content)
    checksums = _parse_list_content(content, list_path)

    for path in select_files(checksums, records):
        expected = checksums.get(path)
        if expected is None:
            continue
        local = _local_path(folder, path)
        if local.is_file() and _sha256_file(local) == expected:
            continue
        try:
            body = fetch(base_url + path)
        except OSError:
            # Not raised here: the final verification names the file.
            continue
        _write_atomically(local, body)

    return verify_database(database, data_root, records=records)


def describe_verification(result: VerificationResult) -> str:
    """Return the sentence that reports a successful verification.

    SRS-001, SRS-013: ``verified: <n> files match the published SHA-256 checksum list
    (SHA256SUMS.txt, SHA-256 <digest>)``, followed for a subset of records by
    ``; records <r1>, <r2>, …``.
    """
    text = (
        f"verified: {len(result.files)} files match the published SHA-256 checksum list "
        f"({CHECKSUM_LIST_NAME}, SHA-256 {result.database.checksum_list_sha256})"
    )
    if result.records is not None:
        text += "; records " + ", ".join(result.records)
    return text


def _database_name(database: Database) -> str:
    """Name of a database in errors, e.g. ``mitdb 1.0.0``."""
    return f"{database.slug} {database.version}"


def _is_safe_path(path: str) -> bool:
    """Whether a listed path is relative and stays inside the database folder."""
    return all(
        _PATH_COMPONENT.fullmatch(component) is not None and component not in (".", "..")
        for component in path.split("/")
    )


def _record_names(records: Sequence[str]) -> tuple[str, ...]:
    """Check the record names and return them sorted, each one once."""
    if isinstance(records, str):
        raise InvalidInputError(f"records is a string, not a sequence of record names: {records!r}")
    for record in records:
        if not isinstance(record, str) or _RECORD_NAME.fullmatch(record) is None:
            raise InvalidInputError(f"invalid record name: {record!r}")
    return tuple(sorted(set(records)))


def _local_path(folder: Path, relative_path: str) -> Path:
    """Local path of a listed file."""
    return folder.joinpath(*relative_path.split("/"))


def _read_if_file(path: Path) -> bytes | None:
    """Content of a regular file, or ``None`` if the path is not a regular file."""
    if not path.is_file():
        return None
    return path.read_bytes()


def _parse_list_content(content: bytes, list_path: Path) -> dict[str, str]:
    """Parse the bytes of a checksum list whose SHA-256 is the pinned one."""
    source = str(list_path)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MalformedFileError(source, None, "not UTF-8 text") from error
    return parse_checksum_list(text, source)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    """SHA-256 of the bytes of a file, read in blocks of 1 MiB."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(_HASH_BLOCK_BYTES):
            digest.update(block)
    return digest.hexdigest()


def _write_atomically(path: Path, content: bytes) -> None:
    """Write a file through ``<name>.part`` in the same folder, creating the folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + _PART_SUFFIX)
    part.write_bytes(content)
    os.replace(part, path)
