import csv
import dataclasses

import numpy as np
import pytest

from msu_anechoic import AzElSpherical
from msu_anechoic import AzElTurntable


@dataclasses.dataclass
class AzElTestCase:
    given_azimuth: float
    given_elevation: float
    azimuth_turntable: float
    elevation_turntable: float
    azimuth_spherical: float
    elevation_spherical: float
    azimuth_turntable_to_spherical: float
    elevation_turntable_to_spherical: float
    azimuth_spherical_to_turntable: float
    elevation_spherical_to_turntable: float

    def original_turntable(self) -> AzElTurntable:
        return AzElTurntable(self.given_azimuth, self.given_elevation)

    def original_spherical(self) -> AzElSpherical:
        return AzElSpherical(self.given_azimuth, self.given_elevation)

    def turntable_to_spherical(self) -> AzElSpherical:
        return AzElTurntable(self.azimuth_turntable, self.elevation_turntable).to_spherical()

    def spherical_to_turntable(self) -> AzElTurntable:
        return AzElSpherical(self.azimuth_spherical, self.elevation_spherical).to_turntable()

    def __str__(self) -> str:
        return f"az={self.given_azimuth:0.1f}, el={self.given_elevation:0.1f}"


def read_test_cases_from_csv(file_path: str) -> list[AzElTestCase]:
    test_cases = []
    with open(file_path, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            test_case = AzElTestCase(
                given_azimuth=float(row["given_azimuth"]),
                given_elevation=float(row["given_elevation"]),
                azimuth_turntable=float(row["azimuth_turntable"]),
                elevation_turntable=float(row["elevation_turntable"]),
                azimuth_spherical=float(row["azimuth_spherical"]),
                elevation_spherical=float(row["elevation_spherical"]),
                azimuth_turntable_to_spherical=float(row["azimuth_turntable_to_spherical"]),
                elevation_turntable_to_spherical=float(row["elevation_turntable_to_spherical"]),
                azimuth_spherical_to_turntable=float(row["azimuth_spherical_to_turntable"]),
                elevation_spherical_to_turntable=float(row["elevation_spherical_to_turntable"]),
            )
            test_cases.append(test_case)
    return test_cases


test_cases: list[AzElTestCase] = read_test_cases_from_csv("tests/coordinates.csv")


@pytest.mark.parametrize("test_case", test_cases, ids=str)
def test_turntable_to_spherical(test_case: AzElTestCase):
    original_turntable = test_case.original_turntable()

    expected_converted_to_spherical = test_case.turntable_to_spherical()
    actual_converted_to_spherical = original_turntable.to_spherical()

    assert actual_converted_to_spherical.azimuth == pytest.approx(expected_converted_to_spherical.azimuth, 1e-6)
    assert actual_converted_to_spherical.elevation == pytest.approx(expected_converted_to_spherical.elevation, 1e-6)


@pytest.mark.parametrize("test_case", test_cases, ids=str)
def test_spherical_to_turntable(test_case: AzElTestCase):
    original_spherical = test_case.original_spherical()

    expected_converted_to_turntable = test_case.spherical_to_turntable()
    actual_converted_to_turntable = original_spherical.to_turntable()

    assert actual_converted_to_turntable.azimuth == pytest.approx(expected_converted_to_turntable.azimuth, 1e-6)
    assert actual_converted_to_turntable.elevation == pytest.approx(expected_converted_to_turntable.elevation, 1e-6)


# @pytest.mark.parametrize("case", test_cases, ids=str)
# def test_spherical_to_turntable(case: AzElTestCase):
#     assert case.spherical_to_turntable().azimuth == pytest.approx(case.azimuth_turntable, 1e-6)
#     assert case.spherical_to_turntable().elevation == pytest.approx(case.elevation_turntable, 1e-6)


def test_azimuthal_plane_equivalence():
    """On the azimuthal plane (elevation = 0), the azimuth should be the same for both representations, even after conversion."""
    for azimuth in np.linspace(-180, 180, 361 * 5):
        azel_tt = AzElTurntable(azimuth, 0)
        azel_spherical = AzElSpherical(azimuth, 0)
        assert azel_tt.azimuth == pytest.approx(azel_spherical.azimuth, 1e-6)
        assert azel_tt.elevation == pytest.approx(azel_spherical.elevation, 1e-6)

        azel_tt_to_spherical = azel_tt.to_spherical()
        assert azel_tt_to_spherical.azimuth == pytest.approx(azel_spherical.azimuth, 1e-6)
        assert azel_tt_to_spherical.elevation == pytest.approx(azel_spherical.elevation, 1e-6)

        azel_spherical_to_tt = azel_spherical.to_turntable()
        assert azel_spherical_to_tt.azimuth == pytest.approx(azel_tt.azimuth, 1e-6)
        assert azel_spherical_to_tt.elevation == pytest.approx(azel_tt.elevation, 1e-6)


def test_elevation_plane_equivalence():
    """On the elevation plane (azimuth = 0), the elevation should be the same for both representations, even after conversion."""
    for elevation in np.linspace(-90, 90, 181 * 5):
        azel_tt = AzElTurntable(0, elevation)
        azel_spherical = AzElSpherical(0, elevation)
        assert azel_tt.azimuth == pytest.approx(azel_spherical.azimuth, 1e-6)
        assert azel_tt.elevation == pytest.approx(azel_spherical.elevation, 1e-6)

        azel_tt_to_spherical = azel_tt.to_spherical()
        assert azel_tt_to_spherical.azimuth == pytest.approx(azel_spherical.azimuth, 1e-6), f"Failed at {elevation=}"
        assert azel_tt_to_spherical.elevation == pytest.approx(azel_spherical.elevation, 1e-6)

        azel_spherical_to_tt = azel_spherical.to_turntable()
        assert azel_spherical_to_tt.azimuth == pytest.approx(azel_tt.azimuth, 1e-6)
        assert azel_spherical_to_tt.elevation == pytest.approx(azel_tt.elevation, 1e-6)


@dataclasses.dataclass
class AzElPair:
    turntable: AzElTurntable
    spherical: AzElSpherical
    description: str | None = None

    def __str__(self) -> str:
        if self.description is not None:
            return self.description
        else:
            return repr(self)


special_coordinates: list[AzElPair] = [
    AzElPair(
        turntable=AzElTurntable(azimuth=0, elevation=0),
        spherical=AzElSpherical(azimuth=0, elevation=0),
        description="Origin (int)",
    ),
    AzElPair(
        turntable=AzElTurntable(azimuth=0.0, elevation=0.0),
        spherical=AzElSpherical(azimuth=0.0, elevation=0.0),
        description="Origin (float)",
    ),
    AzElPair(
        turntable=AzElTurntable(azimuth=np.float64(0.0), elevation=np.float64(0.0)),
        spherical=AzElSpherical(azimuth=np.float64(0.0), elevation=np.float64(0.0)),
        description="Origin (np.float64)",
    ),
    AzElPair(
        turntable=AzElTurntable(azimuth=180, elevation=0),
        spherical=AzElSpherical(azimuth=180, elevation=0),
        description="0 UP/180 RIGHT",
    ),
    AzElPair(
        turntable=AzElTurntable(azimuth=-180, elevation=0),
        spherical=AzElSpherical(azimuth=-180, elevation=0),
        description="0 UP/180 CCW",
    ),
    AzElPair(
        turntable=AzElTurntable(azimuth=90, elevation=90),
        spherical=AzElSpherical(azimuth=90, elevation=0),
        description="90 UP/90 RIGHT",
    ),
    AzElPair(
        turntable=AzElTurntable(azimuth=90, elevation=-90),
        spherical=AzElSpherical(azimuth=90, elevation=0),
        description="90 DOWN/90 RIGHT",
    ),
    AzElPair(
        turntable=AzElTurntable(azimuth=45, elevation=30),
        spherical=AzElSpherical(azimuth=49.106605, elevation=20.704811),
        description="30 UP/45 RIGHT",
    ),
    AzElPair(
        turntable=AzElTurntable(azimuth=-45, elevation=30),
        spherical=AzElSpherical(azimuth=-49.106605, elevation=20.704811),
        description="30 UP/45 LEFT",
    ),
    AzElPair(
        turntable=AzElTurntable(azimuth=45, elevation=-30),
        spherical=AzElSpherical(azimuth=49.106605, elevation=-20.704811),
        description="30 DOWN/45 RIGHT",
    ),
    AzElPair(
        turntable=AzElTurntable(azimuth=-45, elevation=-30),
        spherical=AzElSpherical(azimuth=-49.106605, elevation=-20.704811),
        description="30 DOWN/45 LEFT",
    ),
]


@pytest.mark.parametrize("pair", special_coordinates, ids=str)
def test_turntable_to_spherical_special(pair: AzElPair):
    """Test conversion at known coordinates."""
    azel_tt = pair.turntable
    azel_spherical = pair.spherical

    assert azel_tt.to_spherical().azimuth == pytest.approx(azel_spherical.azimuth, 1e-6)
    assert azel_tt.to_spherical().elevation == pytest.approx(azel_spherical.elevation, 1e-6)


@pytest.mark.parametrize("pair", special_coordinates, ids=str)
def test_spherical_to_turntable_special(pair: AzElPair):
    """Test conversion at known coordinates."""
    azel_tt = pair.turntable
    azel_spherical = pair.spherical

    if abs(azel_spherical.azimuth) > 90 - 1e-6:
        # If the real azimuth is near the +Y/-Y axis, the conversion is not well-defined.
        #
        # I.E., there are infinite points that map to AzElTurntable(elevation=0, azimuth=0),
        # Such as AzElSpherical(azimuth=90, elevation=90), AzElSpherical(azimuth=90, elevation=-90), etc.
        pytest.skip("Spherical to turntable conversion has multiple solutions near +/- 90 degrees azimuth.")

    assert azel_spherical.to_turntable().azimuth == pytest.approx(azel_tt.azimuth, 1e-6)
    assert azel_spherical.to_turntable().elevation == pytest.approx(azel_tt.elevation, 1e-6)
