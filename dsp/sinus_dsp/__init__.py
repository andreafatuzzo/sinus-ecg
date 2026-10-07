"""Sinus reference signal-processing algorithms (Python).

This package is the reference implementation that the portable C++ library
(libs/sinus-dsp) is verified against, with golden vectors. Code that implements a
requirement cites its ID
(``SRS-`` followed by three digits) in a comment or docstring so it appears in the
traceability matrix.
"""

# Equal to [project] version in dsp/pyproject.toml; follows the milestone register
# (docs/regulatory/sdp.md §4). Checked by scripts/traceability.py --check.
__version__ = "0.2.0.dev0"
