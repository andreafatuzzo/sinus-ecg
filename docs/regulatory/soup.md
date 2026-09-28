# SOUP list (Software Of Unknown Provenance)

_Inspired by IEC 62304 §8.1.2. Every new runtime dependency must be added here in the same change that introduces it._

| Name | Component | Version constraint | Purpose | Known anomalies reviewed |
|---|---|---|---|---|
| NumPy | dsp | `>=1.26` | Array math for signal processing | TBD |
| SciPy | dsp | `>=1.11` | Filter design and application | TBD |
| wfdb | dsp | `>=4.1` | Reading PhysioNet WFDB records and annotations | TBD |

Development-only tools (pytest, ruff, mypy) are not part of the software item and are not listed as SOUP.
