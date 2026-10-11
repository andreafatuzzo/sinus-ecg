"""Unit tests of the harness code (evaluation/harness.py and scripts/compare_library.py).

Most tests replace the shared library by a Python object with the same two functions; the tests
marked ``needs_harness`` load the real library of the release build of ``libs/sinus-dsp`` (the
path in ``SINUS_DSP_HARNESS``, or the default build folder) and are skipped without it.
"""

import ctypes
import importlib.util
import os
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from sinus_dsp.data.physionet import Database
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.harness import (
    DetectionComparison,
    LibraryHarness,
    compare_detection,
    load_harness,
)
from sinus_dsp.evaluation.metrics import RecordCounts
from sinus_dsp.evaluation.run import DEFAULT_SETTINGS
from sinus_dsp.pipeline import detect_beats

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compare_library.py"
BUILD = Path(__file__).resolve().parents[3] / "libs" / "sinus-dsp" / "build" / "release" / "harness"

Detector = Callable[[npt.NDArray[np.float64], float, int], npt.NDArray[np.int64]]


class FakeFunction:
    """A stand-in for a ctypes function: accepts ``restype`` and ``argtypes``."""

    restype: Any = None
    argtypes: Any = None

    def __init__(self, behaviour: Callable[..., Any]) -> None:
        self.behaviour = behaviour

    def __call__(self, *args: Any) -> Any:
        return self.behaviour(*args)


class FakeLibrary:
    """Reports a fixed list of detections; ``code`` makes it fail like the real one."""

    def __init__(self, detections: list[int], code: int | None = None, identity: bytes = b"v;d"):
        self.detections = detections
        self.code = code
        self.calls: list[tuple[Any, ...]] = []
        self.sinus_dsp_harness_detect = FakeFunction(self._detect)
        self.sinus_dsp_harness_identity = FakeFunction(lambda: identity)

    def _detect(
        self,
        fs: float,
        mains: int,
        samples: int,
        n: int,
        indices: int,
        startup: int,
        reported_at: int,
        capacity: int,
    ) -> int:
        self.calls.append((fs, mains, samples, n, capacity))
        if self.code is not None:
            return self.code
        count = len(self.detections)
        for k, value in enumerate(self.detections[:capacity]):
            ctypes.cast(indices + 8 * k, ctypes.POINTER(ctypes.c_uint64))[0] = value
        return count


def harness_of(library: FakeLibrary) -> LibraryHarness:
    return LibraryHarness(library)  # type: ignore[arg-type]


def test_detect_returns_the_indices_as_int64() -> None:
    harness = harness_of(FakeLibrary([10, 250, 500]))
    result = harness.detect(np.zeros(1000), 360.0, 60)
    assert result.dtype == np.int64
    assert result.tolist() == [10, 250, 500]


def test_detect_passes_a_float32_copy_and_the_settings() -> None:
    library = FakeLibrary([])
    harness_of(library).detect(np.arange(7.0), 250.0, 50)
    fs, mains, _, n, capacity = library.calls[0]
    assert (fs, mains, n) == (250.0, 50, 7)
    assert capacity > 0


def test_detect_calls_again_with_the_exact_capacity_for_a_long_result() -> None:
    detections = list(range(0, 20000, 2))
    library = FakeLibrary(detections)
    result = harness_of(library).detect(np.zeros(100), 360.0, 60)
    assert result.tolist() == detections
    assert len(library.calls) == 2
    assert library.calls[1][4] == len(detections)


def test_detect_accepts_a_non_contiguous_signal() -> None:
    library = FakeLibrary([3])
    signal = np.zeros(20)[::2]
    assert harness_of(library).detect(signal, 360.0, 60).tolist() == [3]
    assert library.calls[0][3] == 10


@pytest.mark.parametrize(
    ("code", "text"),
    [(-3, "invalid sampling frequency"), (-4, "invalid mains frequency"), (-5, "invalid sample")],
)
def test_detect_names_the_status_of_a_failure(code: int, text: str) -> None:
    harness = harness_of(FakeLibrary([], code=code))
    with pytest.raises(InvalidInputError, match=text):
        harness.detect(np.zeros(10), 360.0, 60)


def test_detect_reports_an_unknown_status() -> None:
    harness = harness_of(FakeLibrary([], code=-100))
    with pytest.raises(InvalidInputError, match="status 99"):
        harness.detect(np.zeros(10), 360.0, 60)


def test_detect_rejects_a_two_dimensional_signal() -> None:
    with pytest.raises(InvalidInputError, match="one-dimensional"):
        harness_of(FakeLibrary([])).detect(np.zeros((2, 5)), 360.0, 60)


def test_identity_is_decoded() -> None:
    assert harness_of(FakeLibrary([], identity=b"0.2.0;abc")).identity() == "0.2.0;abc"


def test_load_harness_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="not found"):
        load_harness(tmp_path / "absent.dll")


def test_load_harness_rejects_a_file_that_is_no_library(tmp_path: Path) -> None:
    path = tmp_path / "text.dll"
    path.write_bytes(b"not a library\n")
    with pytest.raises(InvalidInputError, match="cannot load"):
        load_harness(path)


def test_compare_detection_pairs_the_counts_and_names_the_record_that_differs(
    tmp_path: Path,
    write_fixture_databases: Callable[[Path], tuple[Database, Database]],
    fake_detector: Detector,
) -> None:
    write_fixture_databases(tmp_path)
    mitdb = tmp_path / "mitdb"
    same = compare_detection(
        mitdb, ["100", "119"], DEFAULT_SETTINGS, fake_detector, reference=fake_detector
    )
    assert [c.record for c in same] == ["100", "119"]
    assert all(c.equal for c in same)
    assert same[0].reference == RecordCounts(record="100", tp=2, fn=1, fp=1)

    def drop_last(signal: npt.NDArray[np.float64], fs: float, mains: int) -> npt.NDArray[np.int64]:
        return fake_detector(signal, fs, mains)[:-1]

    different = compare_detection(
        mitdb, ["100", "118"], DEFAULT_SETTINGS, drop_last, reference=fake_detector
    )
    assert [c.equal for c in different] == [False, False]
    assert different[1].reference.tp == 2
    assert different[1].candidate.tp == 1


def test_comparison_is_unequal_when_any_one_count_differs() -> None:
    base = RecordCounts(record="x", tp=5, fn=2, fp=1)
    for other in (
        RecordCounts(record="x", tp=6, fn=2, fp=1),
        RecordCounts(record="x", tp=5, fn=3, fp=1),
        RecordCounts(record="x", tp=5, fn=2, fp=0),
    ):
        assert not DetectionComparison("x", base, other).equal
    assert DetectionComparison("x", base, base).equal


@pytest.fixture
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("compare_library_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["compare_library_script"] = module
    spec.loader.exec_module(module)
    return module


class FakeHarness:
    """Detects like the fake detector, optionally missing the last detection of a record."""

    def __init__(self, fake: Detector, drop_last: bool) -> None:
        self.fake = fake
        self.drop_last = drop_last

    def detect(
        self, signal: npt.NDArray[np.float64], fs: float, mains: int
    ) -> npt.NDArray[np.int64]:
        found = self.fake(signal, fs, mains)
        return found[:-1] if self.drop_last else found

    def identity(self) -> str:
        return "0.0;fake"


@pytest.fixture
def fixture_data(
    tmp_path: Path, write_fixture_databases: Callable[[Path], tuple[Database, Database]]
) -> tuple[Path, Database, Database]:
    mitdb, nstdb = write_fixture_databases(tmp_path)
    return tmp_path, mitdb, nstdb


def _run(
    script: ModuleType,
    fixture_data: tuple[Path, Database, Database],
    harness: Any,
    fake_detector: Detector,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    data, mitdb, nstdb = fixture_data
    # The script's reference is detect_beats: replace it with the fixture detector.
    original = script.compare_detection

    def compare(*args: Any, **kwargs: Any) -> Any:
        return original(*args, reference=fake_detector, **kwargs)

    monkeypatch.setattr(script, "compare_detection", compare)
    return int(
        script.main(
            ["--harness", "unused", "--data-dir", str(data)],
            harness_loader=lambda path: harness,
            mitdb=mitdb,
            nstdb=nstdb,
        )
    )


def test_script_exits_zero_and_prints_both_identities_when_all_equal(
    script: ModuleType,
    fixture_data: tuple[Path, Database, Database],
    fake_detector: Detector,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = _run(
        script, fixture_data, FakeHarness(fake_detector, False), fake_detector, monkeypatch
    )
    out = capsys.readouterr().out
    assert status == 0
    assert "Library (libs/sinus-dsp): 0.0;fake" in out
    assert "Reference (dsp): " in out
    assert "| 207 | " in out
    assert "| 118e24 | " in out
    assert "16 records, 16 equal" in out
    assert "NO" not in out


def test_script_exits_one_and_names_the_records_that_differ(
    script: ModuleType,
    fixture_data: tuple[Path, Database, Database],
    fake_detector: Detector,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = _run(
        script, fixture_data, FakeHarness(fake_detector, True), fake_detector, monkeypatch
    )
    captured = capsys.readouterr()
    assert status == 1
    assert "| NO |" in captured.out
    assert "records with different counts:" in captured.err
    assert "207" in captured.err


def test_script_exits_two_when_the_library_cannot_be_loaded(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--harness", str(tmp_path / "absent.dll")]) == 2
    assert "usage error" in capsys.readouterr().err


def test_script_requires_the_harness_argument(script: ModuleType) -> None:
    with pytest.raises(SystemExit) as raised:
        script.main([])
    assert raised.value.code == 2


def test_script_exits_one_when_a_database_is_not_verified(
    script: ModuleType,
    fixture_data: tuple[Path, Database, Database],
    fake_detector: Detector,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data, _, _ = fixture_data
    (data / "mitdb" / "100.hea").write_bytes(b"tampered")
    assert (
        _run(script, fixture_data, FakeHarness(fake_detector, False), fake_detector, monkeypatch)
        == 1
    )
    assert "comparison failed" in capsys.readouterr().err


def _library_path() -> Path | None:
    given = os.environ.get("SINUS_DSP_HARNESS")
    candidates = (
        [Path(given)]
        if given
        else [BUILD / "sinus_dsp_harness.dll", BUILD / "libsinus_dsp_harness.so"]
    )
    return next((path for path in candidates if path.is_file()), None)


@pytest.mark.needs_harness
@pytest.mark.skipif(
    _library_path() is None, reason="the shared library sinus_dsp_harness is absent"
)
def test_real_library_detects_like_the_reference_on_a_synthetic_signal(
    synthetic_ecg: Callable[..., tuple[npt.NDArray[np.float64], npt.NDArray[np.int64]]],
) -> None:
    path = _library_path()
    assert path is not None
    harness = load_harness(path)
    signal, _ = synthetic_ecg(360.0, 75.0, "bw-mains60", 60.0)
    found = harness.detect(signal, 360.0, 60)
    assert found.size > 50
    assert found.tolist() == detect_beats(signal, 360.0, 60).tolist()
    version, digest = harness.identity().split(";")
    assert version
    assert len(digest) == 64
    with pytest.raises(InvalidInputError, match="invalid mains frequency"):
        harness.detect(signal, 360.0, 55)
    with pytest.raises(InvalidInputError, match="invalid sampling frequency"):
        harness.detect(signal, 50.0, 60)
