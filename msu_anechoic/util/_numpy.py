"""EXTREMELY simple numpy replacements for things."""

import math
from typing import List
from typing import TypeAlias

float64: TypeAlias = float
NDArray: TypeAlias = List


def linspace(start: float, stop: float, steps: int) -> List[float]:
    """Equivalent of `numpy.linspace`. Returns a list of floats"""
    return [start + i * (stop - start) / (steps - 1) for i in range(steps)]


def arange(start: float, stop: float, step: float) -> List[float]:
    """Equivalent of `numpy.arange`. Returns a list of floats"""
    step_count = math.ceil((stop - start) / step)
    return [start + i * step for i in range(step_count)]


if __name__ == "__main__":
    print(linspace(0, 1, 5))  # [0.0, 0.25, 0.5, 0.75, 1.0]
    step = 0.25
    print(arange(0, 1, step))  # [0.0, 0.25, 0.5, 0.75, 1.0]

    from numpy import arange as np_arange

    print([float(x) for x in np_arange(0, 1, step)])
    assert [float(x) for x in np_arange(0, 1, step)] == arange(0, 1, step)
