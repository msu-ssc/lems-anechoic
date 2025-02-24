import dataclasses

import numpy as np
import pytest

from msu_anechoic import AzElSpherical
from msu_anechoic import AzElTurntable


def test_azimuthal_plane_equivalence():
    """On the azimuthal plane (elevation = 0), the azimuth should be the same for both representations, even after conversion."""
    for azimuth in np.arange(-180, 181, 1):
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
    for elevation in np.arange(-90, 91, 1):
        azel_tt = AzElTurntable(0, elevation)
        azel_spherical = AzElSpherical(0, elevation)
        assert azel_tt.azimuth == pytest.approx(azel_spherical.azimuth, 1e-6)
        assert azel_tt.elevation == pytest.approx(azel_spherical.elevation, 1e-6)

        azel_tt_to_spherical = azel_tt.to_spherical()
        assert azel_tt_to_spherical.azimuth == pytest.approx(azel_spherical.azimuth, 1e-6)
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


coords: list[AzElPair] = [
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


@pytest.mark.parametrize("pair", coords, ids=str)
def test_conversion_to_spherical(pair: AzElPair):
    """Test conversion at known coordinates."""
    azel_tt = pair.turntable
    azel_spherical = pair.spherical

    assert azel_tt.to_spherical().azimuth == pytest.approx(azel_spherical.azimuth, 1e-6)
    assert azel_tt.to_spherical().elevation == pytest.approx(azel_spherical.elevation, 1e-6)


@pytest.mark.parametrize("pair", coords, ids=str)
def test_conversion_to_turntable(pair: AzElPair):
    """Test conversion at known coordinates."""
    azel_tt = pair.turntable
    azel_spherical = pair.spherical

    if abs(azel_tt.elevation) > 90 - 1e-6:
        # If the elevation is near the poles, the azimuth is not well-defined.
        pytest.skip("Azimuth is not well-defined near the poles.")

    assert azel_spherical.to_turntable().azimuth == pytest.approx(azel_tt.azimuth, 1e-6)
    assert azel_spherical.to_turntable().elevation == pytest.approx(azel_tt.elevation, 1e-6)
