"""Array types shared by the modules (architecture §8.2). Private: no public interface."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

#: A signal in mV (or an intermediate signal), one dimension, float64.
type FloatArray = npt.NDArray[np.float64]

#: Sample indices, int64, strictly increasing unless stated.
type IndexArray = npt.NDArray[np.int64]

#: One flag per element of another array, e.g. the mark of each detection (architecture §13.1).
type BoolArray = npt.NDArray[np.bool_]
