"""Unit tests of the checks behind the ``needs_data`` and ``needs_nstdb`` markers.

``tests/conftest.py`` is loaded as a module and its checks are run on fixture data folders.
Only file names matter to them, so the fixture files hold a few bytes each.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from sinus_dsp.evaluation.noise_stress import NOISE_STRESS_RECORDS
from sinus_dsp.evaluation.subset import SUBSET_RECORDS

CONFTEST = Path(__file__).resolve().parents[1] / "conftest.py"


@pytest.fixture(scope="module")
def markers() -> ModuleType:
    spec = importlib.util.spec_from_file_location("data_markers_conftest", CONFTEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_records(folder: Path, records: tuple[str, ...] | list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for record in records:
        for suffix in (".hea", ".dat", ".atr"):
            (folder / f"{record}{suffix}").write_bytes(b"x")


def test_data_folder_is_the_one_at_the_repository_root(markers: ModuleType) -> None:
    assert markers.DATA_DIR == Path(__file__).resolve().parents[3] / "data"


def test_complete_arrhythmia_database(markers: ModuleType, tmp_path: Path) -> None:
    write_records(tmp_path / "mitdb", ["100", "101", "232"])
    (tmp_path / "mitdb" / "RECORDS").write_bytes(b"100\n101\n232\n")
    assert markers.mitdb_unavailable(tmp_path) is None


def test_subset_copy_does_not_satisfy_needs_data(markers: ModuleType, tmp_path: Path) -> None:
    """What the CI cache holds: the files of the six records and no ``RECORDS``."""
    write_records(tmp_path / "mitdb", SUBSET_RECORDS)
    (tmp_path / "mitdb" / "SHA256SUMS.txt").write_bytes(b"x")
    reason = markers.mitdb_unavailable(tmp_path)
    assert reason is not None
    assert reason.startswith("MIT-BIH Arrhythmia Database not complete: no usable record list: ")


def test_absent_folder(markers: ModuleType, tmp_path: Path) -> None:
    assert markers.mitdb_unavailable(tmp_path / "absent") is not None
    assert markers.nstdb_unavailable(tmp_path / "absent") == (
        "MIT-BIH Noise Stress Test Database not complete: "
        f"{tmp_path / 'absent' / 'nstdb' / '118e24.hea'} not found"
    )


@pytest.mark.parametrize("missing", ["101.hea", "101.dat", "101.atr"])
def test_a_missing_file_of_a_listed_record(
    markers: ModuleType, tmp_path: Path, missing: str
) -> None:
    folder = tmp_path / "mitdb"
    write_records(folder, ["100", "101"])
    (folder / "RECORDS").write_bytes(b"100\n101\n")
    (folder / missing).unlink()
    assert markers.mitdb_unavailable(tmp_path) == (
        f"MIT-BIH Arrhythmia Database not complete: {folder / missing} not found"
    )


def test_a_listed_record_without_files(markers: ModuleType, tmp_path: Path) -> None:
    folder = tmp_path / "mitdb"
    write_records(folder, ["100"])
    (folder / "RECORDS").write_bytes(b"100\n234\n")
    assert markers.mitdb_unavailable(tmp_path) == (
        f"MIT-BIH Arrhythmia Database not complete: {folder / '234.hea'} not found"
    )


def test_a_folder_in_place_of_a_file(markers: ModuleType, tmp_path: Path) -> None:
    folder = tmp_path / "mitdb"
    write_records(folder, ["100"])
    (folder / "100.dat").unlink()
    (folder / "100.dat").mkdir()
    (folder / "RECORDS").write_bytes(b"100\n")
    assert markers.mitdb_unavailable(tmp_path) is not None


@pytest.mark.parametrize("content", [b"", b"\xff\n", b"100\n100\n", b"../100\n"])
def test_unusable_record_list(markers: ModuleType, tmp_path: Path, content: bytes) -> None:
    write_records(tmp_path / "mitdb", ["100"])
    (tmp_path / "mitdb" / "RECORDS").write_bytes(content)
    reason = markers.mitdb_unavailable(tmp_path)
    assert reason is not None
    assert reason.startswith("MIT-BIH Arrhythmia Database not complete: no usable record list: ")


def test_complete_noise_stress_records(markers: ModuleType, tmp_path: Path) -> None:
    write_records(tmp_path / "nstdb", NOISE_STRESS_RECORDS)
    assert markers.nstdb_unavailable(tmp_path) is None


@pytest.mark.parametrize("missing", ["118e00.dat", "119e_6.atr", "119e24.hea"])
def test_a_missing_file_of_a_noise_stress_record(
    markers: ModuleType, tmp_path: Path, missing: str
) -> None:
    folder = tmp_path / "nstdb"
    write_records(folder, NOISE_STRESS_RECORDS)
    (folder / missing).unlink()
    assert markers.nstdb_unavailable(tmp_path) == (
        f"MIT-BIH Noise Stress Test Database not complete: {folder / missing} not found"
    )


def test_the_two_checks_are_independent(markers: ModuleType, tmp_path: Path) -> None:
    write_records(tmp_path / "mitdb", ["100"])
    (tmp_path / "mitdb" / "RECORDS").write_bytes(b"100\n")
    assert markers.mitdb_unavailable(tmp_path) is None
    assert markers.nstdb_unavailable(tmp_path) is not None
    write_records(tmp_path / "nstdb", NOISE_STRESS_RECORDS)
    (tmp_path / "mitdb" / "RECORDS").unlink()
    assert markers.mitdb_unavailable(tmp_path) is not None
    assert markers.nstdb_unavailable(tmp_path) is None


def test_both_markers_are_registered(pytestconfig: pytest.Config) -> None:
    lines = pytestconfig.getini("markers")
    assert any(line.startswith("needs_data:") for line in lines)
    assert any(line.startswith("needs_nstdb:") for line in lines)


class FakeItem:
    def __init__(self, *names: str) -> None:
        self.names = names
        self.added: list[pytest.MarkDecorator] = []

    def get_closest_marker(self, name: str) -> object | None:
        return name if name in self.names else None

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        self.added.append(marker)


@pytest.mark.parametrize(
    ("mitdb", "nstdb", "skipped"),
    [
        (True, True, set()),
        (False, True, {"data", "both"}),
        (True, False, {"nstdb", "both"}),
        (False, False, {"data", "nstdb", "both"}),
    ],
)
def test_marked_tests_are_skipped_when_their_database_is_not_complete(
    markers: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mitdb: bool,
    nstdb: bool,
    skipped: set[str],
) -> None:
    if mitdb:
        write_records(tmp_path / "mitdb", ["100"])
        (tmp_path / "mitdb" / "RECORDS").write_bytes(b"100\n")
    if nstdb:
        write_records(tmp_path / "nstdb", NOISE_STRESS_RECORDS)
    monkeypatch.setattr(markers, "DATA_DIR", tmp_path)
    items = {
        "none": FakeItem(),
        "data": FakeItem("needs_data"),
        "nstdb": FakeItem("needs_nstdb"),
        "both": FakeItem("needs_data", "needs_nstdb"),
    }
    markers.pytest_collection_modifyitems(None, list(items.values()))
    assert {name for name, item in items.items() if item.added} == skipped
    for item in items.values():
        assert all(marker.name == "skip" for marker in item.added)
