"""Unit tests of the command-line wrapper scripts/download_data.py. No test uses the network."""

import hashlib
import importlib.util
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

from sinus_dsp.data.physionet import (
    CHECKSUM_LIST_NAME,
    MITDB,
    NSTDB,
    Database,
    database_url,
    fetch_https,
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "download_data.py"

MITDB_FILES: Mapping[str, bytes] = {
    "100.dat": b"samples of 100",
    "100.hea": b"header of 100",
    "105.dat": b"samples of 105",
    "RECORDS": b"100\n105\n",
}
NSTDB_FILES: Mapping[str, bytes] = {"118e24.dat": b"noisy", "118e24.hea": b"header"}


def checksum_list(files: Mapping[str, bytes]) -> bytes:
    lines = (f"{hashlib.sha256(body).hexdigest()} {path}\n" for path, body in files.items())
    return "".join(lines).encode()


def fixture_database(slug: str, title: str, files: Mapping[str, bytes]) -> Database:
    digest = hashlib.sha256(checksum_list(files)).hexdigest()
    return Database(slug=slug, version="1.0.0", title=title, checksum_list_sha256=digest)


FIXTURE_MITDB = fixture_database("mitdb", "Fixture Arrhythmia Database", MITDB_FILES)
FIXTURE_NSTDB = fixture_database("nstdb", "Fixture Noise Database", NSTDB_FILES)


class FakeFetch:
    """Serves the two fixture databases, except the URLs given as unavailable."""

    def __init__(self, unavailable: tuple[str, ...] = ()) -> None:
        self.urls: list[str] = []
        self.content: dict[str, bytes] = {}
        for database, files in ((FIXTURE_MITDB, MITDB_FILES), (FIXTURE_NSTDB, NSTDB_FILES)):
            base = database_url(database)
            self.content[base + CHECKSUM_LIST_NAME] = checksum_list(files)
            for path, body in files.items():
                self.content[base + path] = body
        for url in unavailable:
            del self.content[url]

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if url not in self.content:
            raise OSError(f"not served: {url}")
        return self.content[url]


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The script as a module, with the two databases replaced by fixture databases."""
    spec = importlib.util.spec_from_file_location("download_data_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.DATABASES == {"mitdb": MITDB, "nstdb": NSTDB}
    monkeypatch.setattr(module, "DATABASES", {"mitdb": FIXTURE_MITDB, "nstdb": FIXTURE_NSTDB})
    return module


def test_defaults(script: ModuleType) -> None:
    args = script.build_parser().parse_args([])
    assert args.data_dir == Path(__file__).resolve().parents[3] / "data"
    assert args.database == "all"
    assert args.records is None
    assert script.main.__kwdefaults__["fetch"] is fetch_https


def test_both_databases_whole_by_default(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fetch = FakeFetch()
    assert script.main(["--data-dir", str(tmp_path)], fetch=fetch) == 0
    assert sorted(path.name for path in (tmp_path / "mitdb").iterdir()) == sorted(
        [*MITDB_FILES, CHECKSUM_LIST_NAME]
    )
    assert sorted(path.name for path in (tmp_path / "nstdb").iterdir()) == sorted(
        [*NSTDB_FILES, CHECKSUM_LIST_NAME]
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    outcome = [line for line in captured.out.splitlines() if not line.startswith("fetching ")]
    assert outcome == [
        "Fixture Arrhythmia Database 1.0.0: verified: 4 files match the published SHA-256 "
        f"checksum list (SHA256SUMS.txt, SHA-256 {FIXTURE_MITDB.checksum_list_sha256})",
        "Fixture Noise Database 1.0.0: verified: 2 files match the published SHA-256 "
        f"checksum list (SHA256SUMS.txt, SHA-256 {FIXTURE_NSTDB.checksum_list_sha256})",
    ]
    fetching = [line for line in captured.out.splitlines() if line.startswith("fetching ")]
    assert fetching == [f"fetching {url}" for url in fetch.urls]
    assert len(fetch.urls) == 8


def test_second_run_fetches_nothing(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--data-dir", str(tmp_path)], fetch=FakeFetch()) == 0
    capsys.readouterr()
    fetch = FakeFetch()
    assert script.main(["--data-dir", str(tmp_path)], fetch=fetch) == 0
    assert fetch.urls == []
    assert "fetching" not in capsys.readouterr().out


@pytest.mark.parametrize(("slug", "other"), [("mitdb", "nstdb"), ("nstdb", "mitdb")])
def test_one_database(script: ModuleType, tmp_path: Path, slug: str, other: str) -> None:
    assert script.main(["--data-dir", str(tmp_path), "--database", slug], fetch=FakeFetch()) == 0
    assert (tmp_path / slug / CHECKSUM_LIST_NAME).is_file()
    assert not (tmp_path / other).exists()


def test_records_of_one_database(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fetch = FakeFetch()
    argv = ["--data-dir", str(tmp_path), "--database", "mitdb", "--records", "105", "100"]
    assert script.main(argv, fetch=fetch) == 0
    assert sorted(path.name for path in (tmp_path / "mitdb").iterdir()) == [
        "100.dat",
        "100.hea",
        "105.dat",
        CHECKSUM_LIST_NAME,
    ]
    assert capsys.readouterr().out.splitlines()[-1].endswith("; records 100, 105")


def test_not_verified_database_gives_status_1_and_the_other_is_still_done(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unavailable = (database_url(FIXTURE_MITDB) + "105.dat",)
    assert script.main(["--data-dir", str(tmp_path)], fetch=FakeFetch(unavailable)) == 1
    captured = capsys.readouterr()
    assert captured.err == (
        "Fixture Arrhythmia Database 1.0.0: mitdb 1.0.0 not verified: missing: 105.dat\n"
    )
    assert "Fixture Noise Database 1.0.0: verified: 2 files" in captured.out
    assert "Fixture Arrhythmia Database 1.0.0: verified" not in captured.out


def test_record_without_files_gives_status_1(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--data-dir", str(tmp_path), "--database", "nstdb", "--records", "999"]
    assert script.main(argv, fetch=FakeFetch()) == 1
    assert "nstdb 1.0.0 not verified: missing: 999.*" in capsys.readouterr().err


def test_malformed_checksum_list_gives_status_1(
    script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    content = b"not a checksum list\n"
    database = Database("mitdb", "1.0.0", "Broken Database", hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(script, "DATABASES", {"mitdb": database})
    (tmp_path / "mitdb").mkdir()
    (tmp_path / "mitdb" / CHECKSUM_LIST_NAME).write_bytes(content)
    argv = ["--data-dir", str(tmp_path), "--database", "mitdb"]
    assert script.main(argv, fetch=FakeFetch()) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("Broken Database 1.0.0: ")
    assert "line 1: not a checksum entry" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["--database", "other"],
        ["--records", "100"],  # with the default, all databases
        ["--database", "all", "--records", "100"],
        ["--database", "mitdb", "--records"],
        ["--database", "mitdb", "--records", "../100"],
        ["--database", "mitdb", "--records", "100.dat"],
        ["--unknown"],
        ["extra"],
    ],
)
def test_usage_error_gives_status_2_and_fetches_nothing(
    script: ModuleType, tmp_path: Path, argv: list[str]
) -> None:
    fetch = FakeFetch()
    with pytest.raises(SystemExit) as caught:
        script.main(["--data-dir", str(tmp_path), *argv], fetch=fetch)
    assert caught.value.code == 2
    assert fetch.urls == []
    assert list(tmp_path.iterdir()) == []
