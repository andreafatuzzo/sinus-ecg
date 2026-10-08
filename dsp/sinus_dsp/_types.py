"""Array types shared by the modules (architecture §8.2). Private: no public interface."""

from __future__ import annotations

from typing import TypeAlias

import numpy as np
import numpy.typing as npt

#: A signal in mV (or an intermediate signal), one dimension, float64.
FloatArray: TypeAlias = npt.NDArray[np.float64]

#: Sample indices, int64, strictly increasing unless stated.
IndexArray: TypeAlias = npt.NDArray[np.int64]

#: One flag per element of another array, e.g. the mark of each detection (architecture §13.1).
BoolArray: TypeAlias = npt.NDArray[np.bool_]
