import csv

from msu_anechoic import AzElSpherical
from msu_anechoic import AzElTurntable

output_file = "tests/coordinates.csv"

columns = [
    "given_azimuth",
    "given_elevation",
    "elevation_turntable",
    "azimuth_turntable",
    "elevation_turntable_to_spherical",
    "azimuth_turntable_to_spherical",
    "elevation_spherical",
    "azimuth_spherical",
    "elevation_spherical_to_turntable",
    "azimuth_spherical_to_turntable",
]
with open(output_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=columns, dialect="unix")
    writer.writeheader()

    for azimuth in range(-180, 181, 15):
        for elevation in range(-90, 91, 15):
            azel_tt = AzElTurntable(azimuth, elevation)
            azel_spherical = AzElSpherical(azimuth, elevation)

            writer.writerow(
                {
                    "azimuth_turntable": azel_tt.azimuth,
                    "elevation_turntable": azel_tt.elevation,
                    "azimuth_spherical": azel_spherical.azimuth,
                    "elevation_spherical": azel_spherical.elevation,
                    "azimuth_turntable_to_spherical": azel_tt.to_spherical().azimuth,
                    "elevation_turntable_to_spherical": azel_tt.to_spherical().elevation,
                    "azimuth_spherical_to_turntable": azel_spherical.to_turntable().azimuth,
                    "elevation_spherical_to_turntable": azel_spherical.to_turntable().elevation,
                    "given_azimuth": azimuth,
                    "given_elevation": elevation
                }
            )
