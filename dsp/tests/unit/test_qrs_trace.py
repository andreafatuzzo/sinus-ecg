"""Unit tests of the detection trace of ``sinus_dsp.qrs`` (architecture §13.3, §13.4).

The trace adds, to every detection of the Milestone 1 detector, its mark (start-up or
reliable), the sample at which the procedure reports it, its peak and the rule that found it.
These tests check the bookkeeping on hand-placed peaks, that the detections are those of the
Milestone 1 detector (whose outputs are pinned below by digest), the properties of the trace on
whole signals, and that the report sample is exactly the sample at which a detection becomes
known.
"""

import dataclasses
import hashlib
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from sinus_dsp import filters, pipeline, qrs
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.synthetic import synthetic_set

# --- helpers --------------------------------------------------------------------------------


def _digest(indices: npt.NDArray[Any]) -> str:
    """SHA-256 of the indices as little-endian 64-bit integers."""
    return hashlib.sha256(np.asarray(indices, dtype="<i8").tobytes()).hexdigest()


def _conditioned(raw_mv: Any, fs_hz: float, mains_hz: int = 50) -> Any:
    baseline = filters.apply_sos(filters.baseline_sos(fs_hz), np.asarray(raw_mv, dtype=np.float64))
    return filters.apply_sos(filters.mains_sos(fs_hz, mains_hz), baseline)


def _uniform_noise(fs_hz: float, seed: int, amplitude_mv: float, duration_s: float) -> Any:
    rng = np.random.default_rng(seed)
    return amplitude_mv * (rng.random(int(duration_s * fs_hz)) - 0.5)


def _latest_initialisation(detections: qrs.Detections, i: int) -> int:
    """The latest initialisation when detection ``i`` was accepted (architecture §13.3).

    A detection on the learning path is accepted by the initialisation at its report sample;
    the others are accepted before any initialisation of their report sample (step 1 of the
    procedure, and search-back before re-learning in step 3).
    """
    reported = int(detections.reported_at[i])
    inits = detections.initialisations
    if detections.paths[i] == qrs.PATH_LEARNING:
        assert reported in inits.tolist()
        return reported
    return int(inits[inits < reported][-1])


def _check_trace(detections: qrs.Detections, n_samples: int, fs_hz: float) -> None:
    """The properties of a trace that hold on every input (architecture §13.3, §13.4)."""
    s = qrs.detector_samples(fs_hz)
    k = detections.indices.shape[0]
    assert detections.indices.dtype == np.int64
    assert detections.startup.dtype == np.bool_
    assert detections.reported_at.dtype == detections.peaks.dtype == np.int64
    assert detections.initialisations.dtype == np.int64
    assert detections.startup.shape == detections.reported_at.shape == (k,)
    assert detections.peaks.shape == (k,)
    assert type(detections.paths) is tuple
    assert len(detections.paths) == k
    assert set(detections.paths) <= set(qrs.DETECTION_PATHS)
    assert bool(np.all(np.diff(detections.indices) >= s.refractory))
    assert bool(np.all(np.diff(detections.reported_at) >= 0))
    assert bool(np.all(detections.indices <= detections.peaks))
    assert bool(np.all(detections.peaks <= detections.reported_at))
    assert bool(np.all(detections.reported_at < n_samples))
    inits = detections.initialisations
    assert int(inits[0]) == s.learning - 1
    assert bool(np.all(np.diff(inits) > 0))
    bounds = {
        qrs.PATH_NORMAL: s.window + s.peak_timeout + s.band_delay + 2,
        qrs.PATH_SEARCH_BACK: s.relearn_after + s.window + s.band_delay + 1 - s.refractory,
    }
    for i in range(k):
        index = int(detections.indices[i])
        latest = _latest_initialisation(detections, i)
        in_stretch = max(0, latest - s.learning + 1) <= index <= latest
        assert bool(detections.startup[i]) == in_stretch, i
        # Only the latest initialisation can hold the detection (architecture §13.3).
        earlier = [int(v) for v in inits.tolist() if v <= latest]
        assert in_stretch == any(max(0, v - s.learning + 1) <= index <= v for v in earlier)
        delay = int(detections.reported_at[i]) - index
        path = detections.paths[i]
        if path == qrs.PATH_LEARNING:
            first = latest == s.learning - 1
            assert delay <= (s.learning - 1 if first else s.learning + s.window + s.band_delay)
        else:
            assert delay <= bounds[path], (i, path, delay)


def _decisions(fs_hz: float = 360.0, n: int = 20000) -> Any:
    """Decisions with TH_I1 = 2.0 and TH_F1 = 0.2, as after the first initialisation."""
    signals = qrs.QrsSignals(
        bandpassed_mv=np.zeros(n), derivative_mv_per_s=np.zeros(n), integrated=np.zeros(n)
    )
    decisions = qrs._Decisions(qrs.detector_samples(fs_hz), signals)
    decisions.spki, decisions.npki = 8.0, 0.0
    decisions.spkf, decisions.npkf = 0.8, 0.0
    decisions.init_n = qrs.detector_samples(fs_hz).learning - 1
    return decisions


def _peak(m: int, f: int, peak_i: float = 4.0, peak_f: float = 0.4, slope: float = 50.0) -> Any:
    return qrs._Peak(m=m, peak_i=peak_i, peak_f=peak_f, f=f, slope=slope)


def _traced(decisions: Any) -> list[tuple[int, bool, int, int, str]]:
    """``(index, start-up, reported at, peak, path)`` of every detection of ``decisions``."""
    return list(
        zip(
            decisions.output,
            decisions.output_startup,
            decisions.output_reported_at,
            decisions.output_peaks,
            decisions.output_paths,
            strict=True,
        )
    )


# --- interface --------------------------------------------------------------------------------


def test_path_names() -> None:
    assert qrs.PATH_NORMAL == "normal"
    assert qrs.PATH_SEARCH_BACK == "search_back"
    assert qrs.PATH_LEARNING == "learning"
    assert qrs.DETECTION_PATHS == ("normal", "search_back", "learning")


def test_fields_of_the_trace() -> None:
    assert [f.name for f in dataclasses.fields(qrs.Detections)] == [
        "indices",
        "startup",
        "reported_at",
        "peaks",
        "paths",
        "initialisations",
    ]
    assert [f.name for f in dataclasses.fields(qrs.QrsTrace)] == [
        "fs_hz",
        "samples",
        "signals",
        "detections",
    ]
    trace = qrs.trace_qrs(np.zeros(3600), 360)
    with pytest.raises(dataclasses.FrozenInstanceError):
        trace.fs_hz = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        trace.detections.paths = ()  # type: ignore[misc]


# --- the mark, on hand-placed detections ------------------------------------------------------


@pytest.mark.parametrize(("fs_hz", "learning"), [(360.0, 720), (250.0, 500)])
def test_mark_of_the_first_initialisation(fs_hz: float, learning: int) -> None:
    init_n = qrs.detector_samples(fs_hz).learning - 1
    assert init_n == learning - 1
    for index, expected in ((0, True), (1, True), (init_n, True), (init_n + 1, False)):
        assert qrs._startup_mark(index, init_n, learning) is expected


def test_mark_of_a_relearning() -> None:
    learning, init_n = 720, 5000  # stretch [4281, 5000]
    for index, expected in ((4280, False), (4281, True), (4700, True), (5000, True), (5001, False)):
        assert qrs._startup_mark(index, init_n, learning) is expected
    # Before the stretch can be complete, it starts at 0.
    assert qrs._startup_mark(0, 300, learning) is True


def test_normal_detection_marked_by_its_index_not_its_peak() -> None:
    # First initialisation at 719 (L = 720 at 360 Hz): an index inside the stretch whose peak
    # lies after it is start-up; an index after it is reliable.
    inside = _decisions()
    inside.classify(_peak(m=760, f=719), 800)
    assert _traced(inside) == [(719, True, 800, 760, "normal")]
    after = _decisions()
    after.classify(_peak(m=760, f=720), 801)
    assert _traced(after) == [(720, False, 801, 760, "normal")]


def test_ignored_and_noise_peaks_leave_no_trace() -> None:
    decisions = _decisions()
    decisions.classify(_peak(m=1000, f=960), 1010)
    decisions.classify(_peak(m=1050, f=1010), 1060)  # refractory
    decisions.classify(_peak(m=1100, f=1060, slope=10.0), 1110)  # T wave
    decisions.classify(_peak(m=1500, f=1460, peak_i=1.0, peak_f=0.1), 1510)  # noise
    assert _traced(decisions) == [(960, False, 1010, 1000, "normal")]


def _initialised_at_5719() -> Any:
    """Levels learned at 5719 from the stretch [5000, 5719], with two peaks stored in it."""
    samples = qrs.detector_samples(360.0)
    n = 8000
    signals = qrs.QrsSignals(
        bandpassed_mv=np.zeros(n), derivative_mv_per_s=np.zeros(n), integrated=np.zeros(n)
    )
    signals.integrated[5000:5720] = 1.0
    signals.bandpassed_mv[5000:5720] = 0.1
    decisions = qrs._Decisions(samples, signals)
    decisions.init_n = samples.learning - 1
    decisions.initialisations.append(samples.learning - 1)
    for peak in (_peak(m=4990, f=4950), _peak(m=5100, f=5060), _peak(m=5500, f=5460)):
        decisions.store(peak)
    decisions.initialise(5719)
    return decisions


def test_initialisation_records_its_sample_and_the_learning_path() -> None:
    decisions = _initialised_at_5719()
    assert decisions.initialisations == [719, 5719]
    assert _traced(decisions) == [
        (5060, True, 5719, 5100, "learning"),
        (5460, True, 5719, 5500, "learning"),
    ]
    assert decisions.path == qrs.PATH_NORMAL


def test_initialisation_is_recorded_before_its_peaks_are_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[list[int], int | None, str]] = []
    original = qrs._Decisions.classify

    def recording(self: Any, peak: Any, n: int) -> None:
        seen.append((list(self.initialisations), self.init_n, self.path))
        original(self, peak, n)

    monkeypatch.setattr(qrs._Decisions, "classify", recording)
    _initialised_at_5719()
    assert seen == [([719, 5719], 5719, "learning"), ([719, 5719], 5719, "learning")]


@pytest.mark.parametrize(("f", "expected"), [(5719, True), (5720, False)])
def test_after_a_relearning_the_index_decides_the_mark(f: int, expected: bool) -> None:
    decisions = _initialised_at_5719()
    decisions.classify(_peak(m=5770, f=f), 5800)  # peak after the stretch
    assert _traced(decisions)[-1] == (f, expected, 5800, 5770, "normal")


def _ready_for_search_back(init_n: int, last_m: int, candidate_m: int) -> tuple[Any, Any]:
    decisions = _decisions()
    decisions.init_n = init_n
    decisions.last = _peak(m=last_m, f=last_m - 40)
    decisions.rr_flag = True
    decisions.rr_intervals.append(300)  # search-back from last.m + 498
    candidate = _peak(m=candidate_m, f=candidate_m - 40, peak_i=1.5, peak_f=0.15)
    decisions.candidate = candidate
    return decisions, candidate


def test_search_back_records_its_path_and_restores_the_normal_path() -> None:
    decisions, _ = _ready_for_search_back(init_n=719, last_m=1000, candidate_m=1250)
    decisions.search_back(1497)
    assert _traced(decisions) == []
    decisions.search_back(1498)
    assert _traced(decisions) == [(1210, False, 1498, 1250, "search_back")]
    assert decisions.path == qrs.PATH_NORMAL
    decisions.classify(_peak(m=1600, f=1560), 1610)
    assert _traced(decisions)[-1] == (1560, False, 1610, 1600, "normal")


def test_search_back_detection_inside_a_learning_stretch_is_start_up() -> None:
    decisions, _ = _ready_for_search_back(init_n=5719, last_m=5300, candidate_m=5700)
    decisions.search_back(5798)
    assert _traced(decisions) == [(5660, True, 5798, 5700, "search_back")]


# --- whole signals: the detections of the Milestone 1 detector ---------------------------------

# Output of the Milestone 1 detector (``detect_beats``) on the inputs of SRS-006 and SRS-010
# (60 s, from the unit-test generator), the same for the three variants: (count, digest).
M1_DETECT_BEATS = {
    (250.0, 30): (30, "1bcb4b834e890a949a4f38a4c5a85c7dffd7f26a7684bac87c0bccd44db763cd"),
    (250.0, 40): (40, "52dea3d2c516b94ca60b5446dc815555c0137fcab62f399fba293e7216701968"),
    (250.0, 75): (74, "7738f11e69ee0666df229716be54bb3375d1cfb86cc799c3ce9ffc3985f6692e"),
    (250.0, 180): (178, "4bba6012291ec15fc47ebe99e490f7cfa573734ee5014f1c9151cbcc88654726"),
    (250.0, 200): (197, "b7b6869830b670f5f8ea9a9ac5dd9841735b5cdbfefcff19232d3a703ddb8d82"),
    (360.0, 30): (30, "f4b111124f8fc9832629262a01f9d2839549f642103d91fda40b166de6f71fb2"),
    (360.0, 40): (40, "d1f14c0c6f52932a0cbe558dd7a1dad3c90fb13a5f1720d924f8ab3e9d273269"),
    (360.0, 75): (74, "7665f8a955be3ae73ab8e093ced125c5036980c2d69af39cd20c2afd0461bb8f"),
    (360.0, 180): (178, "543b37303f6b003702917d239416bac6312b93c163fcf925260d7c3fd1ab9d74"),
    (360.0, 200): (197, "128568be65625caffdb29bc03d99be59e769c9d6e9d1c9fd0fba07e86773d017"),
}

# Output of the Milestone 1 detector on uniform noise (30 s) and on a noisy synthetic ECG
# (60 s, 75 bpm, interference at 50 Hz): ``detect_qrs`` on the raw input, then
# ``detect_beats`` (mains 50 Hz), each as (count, digest).
M1_NOISE = {
    ("noise", 125.0, 1, 1.0): (
        (85, "6e489be4c578169e0a6c4eaf420161c45e532cff27c7b1366f495a1b48e7df2a"),
        (84, "510d97eb2386d963d4694e5001762227cb19f51df99dd040b871ed142de683c9"),
    ),
    ("noise", 125.0, 2, 0.05): (
        (76, "85df6950fed19b0d0d8f23a4955f9dc33ecaafd95d95027532698a05b6a4576e"),
        (75, "e8804b75dd1f0ea58762a21d1914d046527a4354c73079a0fb9ee7d01e20aec1"),
    ),
    ("noise", 125.0, 3, 3.0): (
        (79, "914553cb05f323a5554338d22c04e6a1068f927729e83745ff8be99a54da6546"),
        (80, "d5fd3210cc0be9bd0306f8f874f34bc25fdb40fceb0c6cb415e586ee51c70563"),
    ),
    ("noise", 250.0, 1, 1.0): (
        (75, "3e743d884470c749f96c524dfe6575d39ef8c3ee02a79302ec5f152c7844c147"),
        (75, "c2460932df0d134437b56e1589edf99947067bc431152908afccbf29230dc445"),
    ),
    ("noise", 250.0, 2, 0.05): (
        (79, "7cc6b27e30926bd105ecac606bb6b6089c7e776ec3298cfcad1c467b35f5e14d"),
        (77, "f7b927adcdc1dbf76d1c5686523a93b26fe175b2ae1a369760ee8fba61ec62ad"),
    ),
    ("noise", 250.0, 3, 3.0): (
        (84, "690131b231bc552d2d2bc133bfaeb297130e933c4a153e9d77ed3bf14a1844b8"),
        (87, "ff7102d004ae85d8461bd7ada6c996a4f469559627e337a58d7da116f9b4968e"),
    ),
    ("noise", 360.0, 1, 1.0): (
        (83, "44609855cd745ef37700229895c17f1776464a107b45881d97f5dae5210063e3"),
        (84, "eb71aeb71016e7834c485c81fe3265bf0ffaca3809b58ada516012659023303d"),
    ),
    ("noise", 360.0, 2, 0.05): (
        (88, "ba9aa13fb9d1909d5c5a4fefef145c1aa54c56413ed4a68ac5262cdae6815aaa"),
        (86, "a236a3282edcdf7e2095a88eb14ab466ab9339a16a56dfda3df8e0fe3f110f14"),
    ),
    ("noise", 360.0, 3, 3.0): (
        (86, "94791c9b974c6da0d16d38c6c6cd429505654cb129876a96d396a298cf8e76fe"),
        (84, "e6a0d2c4885c7eedbb911fa9798478f0608f7a9465f6979201e900f8e651e17f"),
    ),
    ("noise", 1000.0, 1, 1.0): (
        (86, "0221297a7d53c7466b0021790de1409e8ecb06f263488b85cd50f185f629e586"),
        (81, "3ea40e8cd5b60701022302045d75972204848a0308ad9ab69ecbb16036772745"),
    ),
    ("noise", 1000.0, 2, 0.05): (
        (86, "cf5c8231f2a749901e33d556f01cca46079600397ba15bf974143ce31afa8308"),
        (84, "501c2083938ee7eda05865e574e28cbcb1b698b3e3f9c0c1a90c7c1563d0a1fe"),
    ),
    ("noise", 1000.0, 3, 3.0): (
        (88, "9aecd819096004a78412cd44ee2eec15e23b16ca5cd80276cafb80200a72fcab"),
        (86, "8f4bf6a1fcb27519fc86d6c52c1f1c0cb46e743ae03479a5dd53abc54dacccbc"),
    ),
    ("noisy-ecg", 250.0, 4, 0.3): (
        (74, "9633b986c7c09b2a55d02467726d0a0a948a7023e8e3d22bb712bae58fc6466b"),
        (74, "0416e23a4e73146fe2d28c5b712411b52de96d3b1219b6295e7857612bc19836"),
    ),
    ("noisy-ecg", 250.0, 5, 0.8): (
        (74, "a1dd01fc8bce706aa8714956e33ff35f7c6aa8450f5ac8282e43ebe7411ca5cb"),
        (74, "d57dabe5140361f1756a0d85e9a4a26bc1c5c73e286432b245de677f686b5b98"),
    ),
    ("noisy-ecg", 250.0, 6, 1.5): (
        (149, "68f2a7c11940321846b746d2865f45912b33bee4c307f685a92fcf67337c21b4"),
        (148, "9ad2ca9828bb76fa943bf26246b2919a5f7694637254b0739f52d9cff68eb756"),
    ),
    ("noisy-ecg", 360.0, 4, 0.3): (
        (74, "6b8c0ccb358aea7f2d9b9fcd72e1dec641cbd5de49e394316d00492287d4f15d"),
        (74, "68080df135ce3f83beb339e4252d23495bec7ee782ed74d85e1bd931259e2ef1"),
    ),
    ("noisy-ecg", 360.0, 5, 0.8): (
        (87, "3f254716a30956226bb6741a7d27f9c6b5450b06ba04f8c5e2e6f0af63e89503"),
        (75, "35fdf67eea90636bd9258d3706bd7aadd544dd0d916eb956b48d26e75760082e"),
    ),
    ("noisy-ecg", 360.0, 6, 1.5): (
        (155, "2b3e829c82a765be3222356d9a70bac34b718d3367b3541882c361796be4a05a"),
        (148, "3509d3914803ff9fe85e325fdf80db5852a7b084b5140bbd493513001bf25c51"),
    ),
}


@pytest.mark.parametrize("ecg", synthetic_set(), ids=lambda ecg: ecg.input_id)
def test_synthetic_set_trace_equals_the_milestone_1_detections(ecg: Any) -> None:
    # Milestone 1: one detection per beat, 8 ms after the R-wave centre (§8.7.4).
    expected = ecg.r_peaks + {360.0: 3, 250.0: 2}[ecg.fs_hz]
    trace = qrs.trace_qrs(_conditioned(ecg.signal_mv, ecg.fs_hz, ecg.mains_hz), ecg.fs_hz)
    marked = pipeline.detect_marked(ecg.signal_mv, ecg.fs_hz, ecg.mains_hz)
    assert trace.detections.indices.tolist() == expected.tolist()
    assert marked.indices.tolist() == expected.tolist()
    n = ecg.signal_mv.shape[0]
    _check_trace(marked, n, ecg.fs_hz)
    learning = qrs.detector_samples(ecg.fs_hz).learning
    assert marked.startup.tolist() == (marked.indices <= learning - 1).tolist()
    assert marked.initialisations.tolist() == [learning - 1]


@pytest.mark.parametrize(("fs_hz", "heart_rate_bpm"), sorted(M1_DETECT_BEATS))
def test_srs_006_and_srs_010_inputs_trace_equals_the_milestone_1_detections(
    fs_hz: float, heart_rate_bpm: int, synthetic_ecg: Any
) -> None:
    count, digest = M1_DETECT_BEATS[(fs_hz, heart_rate_bpm)]
    s = qrs.detector_samples(fs_hz)
    for variant in ("clean", "bw-mains50", "bw-mains60"):
        raw, r_peaks = synthetic_ecg(fs_hz, heart_rate_bpm, variant, duration_s=60.0)
        mains_hz = 60 if variant == "bw-mains60" else 50
        marked = pipeline.detect_marked(raw, fs_hz, mains_hz)
        assert marked.indices.shape == (count,)
        assert _digest(marked.indices) == digest
        assert np.array_equal(marked.indices, pipeline.detect_beats(raw, fs_hz, mains_hz))
        if heart_rate_bpm <= 180:
            assert marked.indices.tolist() == (r_peaks + {360.0: 3, 250.0: 2}[fs_hz]).tolist()
        _check_trace(marked, raw.shape[0], fs_hz)
        # Start-up exactly for the indices in the first L samples; after them, a regular rhythm
        # is found by the normal thresholds, within 0.35 s (architecture §13.4).
        assert marked.startup.tolist() == (marked.indices <= s.learning - 1).tolist()
        reliable = ~marked.startup
        assert {p for p, r in zip(marked.paths, reliable, strict=True) if r} == {"normal"}
        delays = marked.reported_at[reliable] - marked.indices[reliable]
        assert int(np.max(delays)) <= int(0.35 * fs_hz)
        assert marked.initialisations.tolist() == [s.learning - 1]


@pytest.mark.parametrize("key", sorted(M1_NOISE), ids=str)
def test_noise_trace_equals_the_milestone_1_detections(
    key: tuple[str, float, int, float], synthetic_ecg: Any
) -> None:
    kind, fs_hz, seed, amplitude_mv = key
    if kind == "noise":
        raw = _uniform_noise(fs_hz, seed, amplitude_mv, 30.0)
    else:
        ecg, _ = synthetic_ecg(fs_hz, 75, "bw-mains50", duration_s=60.0)
        raw = ecg + _uniform_noise(fs_hz, seed, amplitude_mv, 60.0)
    (raw_count, raw_digest), (beats_count, beats_digest) = M1_NOISE[key]
    trace = qrs.trace_qrs(raw, fs_hz)
    assert trace.detections.indices.shape == (raw_count,)
    assert _digest(trace.detections.indices) == raw_digest
    assert np.array_equal(qrs.detect_qrs(raw, fs_hz), trace.detections.indices)
    marked = pipeline.detect_marked(raw, fs_hz, 50)
    assert marked.indices.shape == (beats_count,)
    assert _digest(marked.indices) == beats_digest
    _check_trace(trace.detections, raw.shape[0], fs_hz)
    _check_trace(marked, raw.shape[0], fs_hz)


def test_noise_exercises_every_path(synthetic_ecg: Any) -> None:
    paths = qrs.trace_qrs(_uniform_noise(250.0, 1, 1.0, 30.0), 250.0).detections.paths
    assert set(paths) == set(qrs.DETECTION_PATHS)


# --- whole signals: inputs with events (as the event inputs of architecture §13.9) -------------


@pytest.mark.parametrize(("fs_hz", "delay"), [(250.0, 156), (360.0, 224)])
def test_small_beat_is_found_by_search_back(fs_hz: float, delay: int, synthetic_ecg: Any) -> None:
    # Beat 12 at 0.4 times the amplitude: below the first thresholds, found by search-back
    # 0.62 s after its index; every beat detected.
    raw, r_peaks = synthetic_ecg(fs_hz, 75, duration_s=40.0, beat_gains={12: 0.4})
    marked = pipeline.detect_marked(raw, fs_hz, 50)
    offset = {360.0: 3, 250.0: 2}[fs_hz]
    assert marked.indices.tolist() == (r_peaks + offset).tolist()
    found = [i for i, path in enumerate(marked.paths) if path == qrs.PATH_SEARCH_BACK]
    assert found == [12]
    assert int(marked.reported_at[12] - marked.indices[12]) == delay
    assert round(delay / fs_hz, 2) == 0.62
    assert marked.initialisations.tolist() == [qrs.detector_samples(fs_hz).learning - 1]
    _check_trace(marked, raw.shape[0], fs_hz)


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
def test_large_artefact_gives_start_up_detections_after_a_relearning(
    fs_hz: float, synthetic_ecg: Any
) -> None:
    # Beat 12 at 20 times the amplitude: the next beats are missed until detection learns its
    # levels again; the beats of that learning stretch are detected and marked start-up.
    raw, r_peaks = synthetic_ecg(fs_hz, 75, duration_s=40.0, beat_gains={12: 20.0})
    marked = pipeline.detect_marked(raw, fs_hz, 50)
    _check_trace(marked, raw.shape[0], fs_hz)
    s = qrs.detector_samples(fs_hz)
    first, relearning = marked.initialisations.tolist()
    assert first == s.learning - 1
    late = marked.indices[marked.startup & (marked.indices > first)].tolist()
    assert len(late) == 3
    assert all(relearning - s.learning + 1 <= index <= relearning for index in late)
    assert int(marked.indices[-1]) > relearning
    after = marked.indices > relearning
    assert not bool(np.any(marked.startup[after]))
    assert int(np.count_nonzero(after)) >= 20
    if fs_hz == 360.0:
        # Re-learning at 18.2 s. The last start-up detection has its index in the stretch, but
        # its peak is confirmed after the re-learning: it is found by the normal thresholds,
        # and marked start-up by its index.
        assert round(relearning / fs_hz, 1) == 18.2
        last = int(np.flatnonzero(marked.indices == late[-1])[0])
        assert int(marked.reported_at[last]) > relearning
        assert marked.paths[last] == qrs.PATH_NORMAL
        assert [marked.paths[i] for i in range(last - 2, last)] == ["learning", "learning"]
        assert qrs.PATH_SEARCH_BACK not in marked.paths
    else:
        # One detection by search-back, reported 5.8 s after its index.
        found = [i for i, path in enumerate(marked.paths) if path == qrs.PATH_SEARCH_BACK]
        assert len(found) == 1
        delay = int(marked.reported_at[found[0]] - marked.indices[found[0]])
        assert round(delay / fs_hz, 1) == 5.8
        assert int(r_peaks[12]) < int(marked.indices[found[0]]) < int(r_peaks[13])
        indices = marked.indices.tolist()
        startup_paths = [p for p, i in zip(marked.paths, indices, strict=True) if i in late]
        assert startup_paths == ["learning"] * 3


def test_flat_stretch_relearns_without_start_up_detections_after_it(
    synthetic_ecg: Any,
) -> None:
    # Architecture §13.3, edge cases: the re-learning stretch lies in the flat stretch, so the
    # detections after the signal returns are reliable.
    fs_hz = 360.0
    before, _ = synthetic_ecg(fs_hz, 75, duration_s=12.0)
    after, r_after = synthetic_ecg(fs_hz, 120, duration_s=30.0)
    gap = np.zeros(int(20 * fs_hz))
    raw = np.concatenate([before, gap, after])
    marked = pipeline.detect_marked(raw, fs_hz, 50)
    _check_trace(marked, raw.shape[0], fs_hz)
    assert marked.initialisations.size == 3
    start = before.shape[0] + gap.shape[0]
    assert marked.indices[marked.indices >= start].tolist() == (r_after + start + 3).tolist()
    assert not bool(np.any(marked.startup[marked.indices > qrs.detector_samples(fs_hz).learning]))


# --- the report sample is the sample at which a detection becomes known ----------------------


def _cut_points(detections: qrs.Detections) -> list[int]:
    points = {int(v) for v in detections.reported_at.tolist()}
    points |= {v + 1 for v in points}
    points |= {int(v) for v in detections.initialisations.tolist()}
    points |= {int(v) + 1 for v in detections.initialisations.tolist()}
    return sorted(points)


@pytest.mark.parametrize("case", ["artefact-250", "small-beat-360", "noise-250"])
def test_a_truncated_input_reports_exactly_the_detections_reported_before_its_end(
    case: str, synthetic_ecg: Any
) -> None:
    if case == "artefact-250":
        fs_hz = 250.0
        raw, _ = synthetic_ecg(fs_hz, 75, duration_s=40.0, beat_gains={12: 20.0})
    elif case == "small-beat-360":
        fs_hz = 360.0
        raw, _ = synthetic_ecg(fs_hz, 75, duration_s=40.0, beat_gains={12: 0.4})
    else:
        fs_hz = 250.0
        raw = _uniform_noise(fs_hz, 1, 1.0, 30.0)
    x = np.asarray(_conditioned(raw, fs_hz), dtype=np.float64)
    whole = qrs._trace(x, fs_hz).detections
    assert set(whole.paths) >= {qrs.PATH_LEARNING, qrs.PATH_SEARCH_BACK, qrs.PATH_NORMAL}
    for end in _cut_points(whole):
        part = qrs._trace(x[:end].copy(), fs_hz).detections
        known = whole.reported_at < end
        assert part.indices.tolist() == whole.indices[known].tolist(), end
        assert part.startup.tolist() == whole.startup[known].tolist(), end
        assert part.reported_at.tolist() == whole.reported_at[known].tolist(), end
        assert part.peaks.tolist() == whole.peaks[known].tolist(), end
        assert part.paths == tuple(p for p, k in zip(whole.paths, known, strict=True) if k)
        expected_inits = whole.initialisations[whole.initialisations < end]
        assert part.initialisations.tolist() == expected_inits.tolist(), end


# --- trace_qrs and detect_qrs -----------------------------------------------------------------


def test_trace_holds_the_parameters_and_the_signals(synthetic_ecg: Any) -> None:
    raw, _ = synthetic_ecg(250.0, 75, "bw-mains60")
    x = _conditioned(raw, 250.0, 60)
    trace = qrs.trace_qrs(x.tolist(), 250)
    assert type(trace.fs_hz) is float
    assert trace.fs_hz == 250.0
    assert trace.samples == qrs.detector_samples(250.0)
    expected = qrs.qrs_signals(x, 250.0)
    assert np.array_equal(trace.signals.bandpassed_mv, expected.bandpassed_mv)
    assert np.array_equal(trace.signals.derivative_mv_per_s, expected.derivative_mv_per_s)
    assert np.array_equal(trace.signals.integrated, expected.integrated)
    assert np.array_equal(qrs.detect_qrs(x, 250.0), trace.detections.indices)


@pytest.mark.parametrize(
    ("signal", "fs_hz", "message"),
    [
        (np.zeros(3599), 360.0, "shorter than"),
        (np.full(3600, -1000.0000000000001), 360.0, "magnitude exceeds 1000.0 mV"),
        (np.zeros(3600), 124.9, "sampling frequency is outside"),
        (np.full(3600, np.nan), 360.0, "non-finite"),
    ],
)
def test_trace_qrs_validates_its_input(
    signal: Any, fs_hz: float, message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the detector ran on a rejected input")

    monkeypatch.setattr(qrs, "_trace", fail)
    with pytest.raises(InvalidInputError, match=message):
        qrs.trace_qrs(signal, fs_hz)
    with pytest.raises(InvalidInputError, match=message):
        qrs.detect_qrs(signal, fs_hz)


def test_trace_does_not_modify_its_input_and_is_repeatable(synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(360.0, 75)
    before = x.copy()
    first = qrs.trace_qrs(x, 360.0).detections
    second = qrs.trace_qrs(x, 360.0).detections
    assert np.array_equal(x, before)
    for name in ("indices", "startup", "reported_at", "peaks", "initialisations"):
        assert np.array_equal(getattr(first, name), getattr(second, name))
        assert getattr(first, name) is not getattr(second, name)
    assert first.paths == second.paths
