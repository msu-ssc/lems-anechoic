import dataclasses

import numpy as np
import pytest

from msu_anechoic.util.coordinate import Coordinate


@dataclasses.dataclass
class CoordinateTestCase:
    azimuth: float
    elevation: float
    neutral_elevation: float

    def __str__(self) -> str:
        return f"az={self.azimuth:0.1f}, el={self.elevation:0.1f}, neutral_el={self.neutral_elevation:0.1f}"


test_cases: list[CoordinateTestCase] = []

for azimuths in np.arange(-180, 181, 30):
    for elevations in np.arange(-90, 91, 30):
        for neutral_elevation in [-3.75, 0, 3.75]:
            test_case = CoordinateTestCase(
                azimuth=azimuths,
                elevation=elevations,
                neutral_elevation=neutral_elevation,
            )
            test_cases.append(test_case)


def convert_to(coord: Coordinate, target_kind: str) -> Coordinate:
    if target_kind == "turntable":
        return Coordinate.from_turntable(
            azimuth=coord.turntable_azimuth,
            elevation=coord.turntable_elevation,
            neutral_elevation=coord.neutral_elevation,
        )
    elif target_kind == "absolute_turntable":
        return Coordinate.from_absolute_turntable(
            azimuth=coord.absolute_turntable_azimuth,
            elevation=coord.absolute_turntable_elevation,
            neutral_elevation=coord.neutral_elevation,
        )
    elif target_kind == "antenna":
        return Coordinate.from_antenna(
            azimuth=coord.antenna_azimuth,
            elevation=coord.antenna_elevation,
            neutral_elevation=coord.neutral_elevation,
        )


def verify_conversion_and_inverse(test_case: CoordinateTestCase, original_kind: str, target_kind: str) -> None:
    if original_kind == "turntable":
        original = Coordinate.from_turntable(
            azimuth=test_case.azimuth,
            elevation=test_case.elevation,
            neutral_elevation=test_case.neutral_elevation,
        )
    elif original_kind == "absolute_turntable":
        original = Coordinate.from_absolute_turntable(
            azimuth=test_case.azimuth,
            elevation=test_case.elevation,
            neutral_elevation=test_case.neutral_elevation,
        )
    elif original_kind == "antenna":
        original = Coordinate.from_antenna(
            azimuth=test_case.azimuth,
            elevation=test_case.elevation,
            neutral_elevation=test_case.neutral_elevation,
        )

    converted = convert_to(original, target_kind)
    converted_back = convert_to(converted, original_kind)

    # Deal with some ill-defined cases

    # TT -> Antenna near +/-90 degrees elevation or +/- 90 degrees azimuth
    if abs(test_case.elevation) > 89.9:
        pytest.skip("Skipping test. All conversions near +/-90 degrees elevation are ill-defined.")
    if 89.9 < abs(test_case.azimuth) < 90.1:
        pytest.skip("Skipping test. All conversions near +/-90 degrees azimuth are ill-defined.")
    # if original_kind in {"turntable", "absolute_turntable"} and target_kind == "antenna" and (abs(test_case.elevation) > 89.9 or 89.9 < abs(test_case.azimuth) < 90.1):
    #     pytest.skip("Skipping test for turntable->antenna near +/-90 degrees elevation")

    _compare_all_values(
        original, converted_back, original_kind=original_kind, target_kind=target_kind, test_case=test_case
    )


@pytest.mark.parametrize("test_case", test_cases, ids=str)
def test_conversion_turntable_to_absolute_turntable(test_case: CoordinateTestCase) -> None:
    verify_conversion_and_inverse(test_case, "turntable", "absolute_turntable")


@pytest.mark.parametrize("test_case", test_cases, ids=str)
def test_conversion_turntable_to_antenna(test_case: CoordinateTestCase) -> None:
    verify_conversion_and_inverse(test_case, "turntable", "antenna")


@pytest.mark.parametrize("test_case", test_cases, ids=str)
def test_conversion_absolute_turntable_to_turntable(test_case: CoordinateTestCase) -> None:
    verify_conversion_and_inverse(test_case, "absolute_turntable", "turntable")


@pytest.mark.parametrize("test_case", test_cases, ids=str)
def test_conversion_absolute_turntable_to_antenna(test_case: CoordinateTestCase) -> None:
    verify_conversion_and_inverse(test_case, "absolute_turntable", "antenna")


@pytest.mark.parametrize("test_case", test_cases, ids=str)
def test_conversion_antenna_to_turntable(test_case: CoordinateTestCase) -> None:
    verify_conversion_and_inverse(test_case, "antenna", "turntable")


@pytest.mark.parametrize("test_case", test_cases, ids=str)
def test_conversion_antenna_to_absolute_turntable(test_case: CoordinateTestCase) -> None:
    verify_conversion_and_inverse(test_case, "antenna", "absolute_turntable")


# def test_conversions(test_case: CoordinateTestCase) -> None:
#     assert test_case
#     original_turntable = Coordinate.from_turntable(
#         azimuth=test_case.azimuth,
#         elevation=test_case.elevation,
#         neutral_elevation=test_case.neutral_elevation,
#     )

#     original_absolute_turntable = Coordinate.from_absolute_turntable(
#         azimuth=test_case.azimuth,
#         elevation=test_case.elevation,
#         neutral_elevation=test_case.neutral_elevation,
#     )

#     original_antenna = Coordinate.from_antenna(
#         azimuth=test_case.azimuth,
#         elevation=test_case.elevation,
#         neutral_elevation=test_case.neutral_elevation,
#     )


#     originals = {
#         "turntable": original_turntable,
#         "absolute_turntable": original_absolute_turntable,
#         "antenna": original_antenna,
#     }

#     pairs = list(itertools.permutations(originals, 2))

#     # for pair in pairs:
#     original_kind = test_case.original_kind
#     target_kind = test_case.conversion_kind
#     original = originals[original_kind]
#     converted = convert_to(original, target_kind)
#     converted_back = convert_to(converted, original_kind)

#     _compare_all_values(original, converted_back)


def _compare_all_values(
    original: Coordinate,
    converted_back: Coordinate,
    original_kind: str,
    target_kind: str,
    test_case: CoordinateTestCase,
) -> None:
    assert original.turntable_azimuth == pytest.approx(converted_back.turntable_azimuth), (
        f"Error converting {test_case} ({original_kind}->{target_kind}->{original_kind})"
    )
    assert original.turntable_elevation == pytest.approx(converted_back.turntable_elevation), (
        f"Error converting {test_case} ({original_kind}->{target_kind}->{original_kind})"
    )
    assert original.absolute_turntable_azimuth == pytest.approx(converted_back.absolute_turntable_azimuth), (
        f"Error converting {test_case} ({original_kind}->{target_kind}->{original_kind})"
    )
    assert original.absolute_turntable_elevation == pytest.approx(converted_back.absolute_turntable_elevation), (
        f"Error converting {test_case} ({original_kind}->{target_kind}->{original_kind})"
    )
    assert original.antenna_azimuth == pytest.approx(converted_back.antenna_azimuth), (
        f"Error converting {test_case} ({original_kind}->{target_kind}->{original_kind})"
    )
    assert original.antenna_elevation == pytest.approx(converted_back.antenna_elevation), (
        f"Error converting {test_case} ({original_kind}->{target_kind}->{original_kind})"
    )
    assert original.neutral_elevation == pytest.approx(converted_back.neutral_elevation), (
        f"Error converting {test_case} ({original_kind}->{target_kind}->{original_kind})"
    )
    assert original.kind == converted_back.kind


if __name__ == "__main__":
    point = Coordinate.from_absolute_turntable(azimuth=-30, elevation=-30, neutral_elevation=0)
    # point = Coordinate.from_turntable(azimuth=-30, elevation=-30, neutral_elevation=0)
    print(f"{point         =!s}")
    converted = convert_to(point, "antenna")
    print(f"{converted     =!s}")
    print(f"{converted.absolute_turntable_elevation=}")
    converted_back = convert_to(converted, point.kind)
    print(f"{converted_back=!s}")
    pass
