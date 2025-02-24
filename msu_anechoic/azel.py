from __future__ import annotations

from typing import NamedTuple

import numpy as np
from matplotlib import pyplot as plt


class AzEl(NamedTuple):
    """Azimuth and elevation in degrees."""

    azimuth: float
    elevation: float

    @property
    def azimuth_degrees(self) -> float:
        """Return the azimuth in degrees."""
        return self.azimuth

    @property
    def elevation_degrees(self) -> float:
        """Return the elevation in degrees."""
        return self.elevation

    @property
    def azimuth_radians(self) -> float:
        """Return the azimuth in radians."""
        return float(np.radians(self.azimuth))

    @property
    def elevation_radians(self) -> float:
        """Return the elevation in radians."""
        return float(np.radians(self.elevation))

    def to_cartesian(self, radius: float = 1) -> tuple[float, float, float]:
        """Convert the azimuth and elevation to Cartesian coordinates on a spher with the given radius."""
        # DO NOT IMPLEMENT HERE!
        raise NotImplementedError("Subclasses must implement this method.")

    def to_turntable(self) -> "AzElTurntable":
        """Convert the current azimuth and elevation to turn-table coordinates."""
        # DO NOT IMPLEMENT HERE!
        raise NotImplementedError("Subclasses must implement this method.")

    def to_spherical(self) -> "AzElSpherical":
        """Convert the current azimuth and elevation to spherical coordinates."""
        # DO NOT IMPLEMENT HERE!
        raise NotImplementedError("Subclasses must implement this method.")


def turntable_to_traditional(*, turn_elevation_deg: float, turn_azimuth_deg: float) -> tuple[float, float]:
    """
    Convert turntable angles to traditional spherical coordinates.

    Parameters:
      turn_elevation_deg: the elevation rotation of the turntable (in degrees).
      turn_azimuth_deg: the azimuth rotation performed on the tilted plane (in degrees).

    Returns:
      A tuple (trad_azimuth_deg, trad_elevation_deg) representing the
      traditional azimuth (angle in the horizontal plane) and elevation (angle above horizontal).
    """
    # Convert degrees to radians
    turn_elevation_rad = np.radians(turn_elevation_deg)
    turn_azimuth_rad = np.radians(turn_azimuth_deg)

    # After the elevation rotation (about y by -E) and then azimuth rotation (about z by A),
    # the pointer vector becomes:
    #
    # v = R_y(-E) * (R_z(A) * [1, 0, 0])
    #
    # where R_z(A)*[1, 0, 0] = [cos(A), sin(A), 0] and
    # R_y(-E) rotates this vector to:
    x = np.cos(turn_elevation_rad) * np.cos(turn_azimuth_rad)
    y = np.sin(turn_azimuth_rad)
    z = np.sin(turn_elevation_rad) * np.cos(turn_azimuth_rad)

    # Compute traditional spherical angles:
    trad_azimuth_rad = np.atan2(y, x)  # azimuth: angle in x-y plane
    trad_elevation_rad = np.asin(z)  # elevation: arcsin(z) since |v| = 1

    # Convert results back to degrees
    trad_azimuth_deg = np.degrees(trad_azimuth_rad)
    trad_elevation_deg = np.degrees(trad_elevation_rad)

    return trad_azimuth_deg, trad_elevation_deg


# Example usage:
if __name__ == "__main__":
    # Turntable angles (example): Elevation 30° then Azimuth 40°
    tt_elev = 90.0  # turntable elevation in degrees
    tt_azim = -90.0  # turntable azimuth in degrees

    trad_azim, trad_elev = turntable_to_traditional(turn_elevation_deg=tt_elev, turn_azimuth_deg=tt_azim)
    print("Traditional azimuth: {:.2f}°".format(trad_azim))
    print("Traditional elevation: {:.2f}°".format(trad_elev))


class AzElTurntable(AzEl):
    """Azimuth and elevation in turn-table coordinates.

    The turn-table uses a different coordinate system than the "normal" spherical coordinates, because
    the turn-table moves in elevation FIRST, then azimuth moves around a plane within a plane that is
    inclined at the elevation angle."""

    def to_spherical(self) -> "AzElSpherical":
        """Convert this turn-table coordinate to a "normal" spherical coordinate."""
        az, el = turntable_to_traditional(turn_elevation_deg=self.elevation, turn_azimuth_deg=self.azimuth)
        return AzElSpherical(azimuth=az, elevation=el)

    def to_cartesian(self, radius: float = 1) -> tuple[float, float, float]:
        return self.to_spherical.to_cartesian(radius=radius)

    def to_turntable(self) -> "AzElTurntable":
        return self


class AzElSpherical(AzEl):
    """Azimuth and elevation in "normal" spherical coordinates."""

    def to_cartesian(self, radius: float = 1) -> tuple[float, float, float]:
        x = radius * np.cos(self.azimuth_radians) * np.cos(self.elevation_radians)
        y = radius * np.sin(self.azimuth_radians) * np.cos(self.elevation_radians)
        z = radius * np.sin(self.elevation_radians)
        return x, y, z

    def to_turntable(self) -> "AzElTurntable":
        az, el = traditional_to_turntable_numpy(trad_azimuth_deg=self.azimuth, trad_elevation_deg=self.elevation)
        return AzElTurntable(azimuth=az, elevation=el)

    def to_spherical(self) -> "AzElSpherical":
        return self


def turntable_to_traditional_numpy(turn_elevation_deg: float, turn_azimuth_deg: float) -> tuple[float, float]:
    """
    Convert turntable azimuth and elevation to traditional azimuth and elevation
    using only NumPy.

    Parameters:
      turn_elevation_deg (float): Elevation angle of the turntable in degrees.
      turn_azimuth_deg (float): Azimuth angle of the turntable in degrees.

    Returns:
      tuple[float, float]: Traditional azimuth and elevation in degrees.
    """
    # Convert degrees to radians
    E: float = np.radians(turn_elevation_deg)  # Elevation angle
    A: float = np.radians(turn_azimuth_deg)  # Azimuth angle

    # Define rotation matrices
    R_elev: np.ndarray = np.array(
        [[np.cos(-E), 0, np.sin(-E)], [0, 1, 0], [-np.sin(-E), 0, np.cos(-E)]]
    )  # Rotation about y-axis (tilt down by -E)

    R_azim: np.ndarray = np.array(
        [[np.cos(A), -np.sin(A), 0], [np.sin(A), np.cos(A), 0], [0, 0, 1]]
    )  # Rotation about the new z-axis (pan by A)

    # Initial direction vector (pointing along x-axis)
    initial_vector: np.ndarray = np.array([1, 0, 0])

    # Apply the rotations: first azimuth, then elevation
    final_vector: np.ndarray = R_elev @ (R_azim @ initial_vector)

    # Extract the new x, y, z coordinates
    x, y, z = final_vector

    # Compute traditional azimuth and elevation
    trad_azimuth_rad: float = np.arctan2(y, x)  # atan2(y, x) for azimuth
    trad_elevation_rad: float = np.arcsin(z)  # arcsin(z) for elevation

    # Convert to degrees
    trad_azimuth_deg: float = np.degrees(trad_azimuth_rad)
    trad_elevation_deg: float = np.degrees(trad_elevation_rad)

    return trad_azimuth_deg, trad_elevation_deg


# Example usage
trad_azim, trad_elev = turntable_to_traditional_numpy(30, 40)
print(f"Traditional Azimuth: {trad_azim:.2f}°")
print(f"Traditional Elevation: {trad_elev:.2f}°")


# import matplotlib.pyplot as plt
# import numpy as np
# from mpl_toolkits.mplot3d.axes3d import Axes3D

# fig = plt.figure()
# ax: Axes3D = fig.add_subplot(111, projection="3d")

# # print(f"{type(ax)=}")
# # # Generate points for the circle
# # theta = np.linspace(0, 2 * np.pi, 30)
# # r = 1  # radius
# # elevation = 0  # elevation in radians

# # # Convert spherical to Cartesian coordinates
# # x = r * np.cos(theta) * np.cos(elevation)
# # y = r * np.sin(theta) * np.cos(elevation)
# # z = r * np.sin(elevation) * (theta / theta)

# # # Plot the circle
# # # ax.plot(x, y, z, label='Circle at elevation 0', marker="o")
# # for px, py, pz in zip(x, y, z):
# #     ax.plot([0, px], [0, py], [0, pz], color='orange', linestyle='-', marker='o')
# # ax.legend()
# # Create a mesh grid for the sphere
# u = np.linspace(0, 2 * np.pi, 25)
# ax.set_box_aspect([1, 1, 1])  # Aspect ratio is 1:1:1 to make the sphere look circular
# v = np.linspace(0, np.pi, 25)
# r = 1
# x_sphere = r * np.outer(np.cos(u), np.sin(v))
# y_sphere = r * np.outer(np.sin(u), np.sin(v))
# z_sphere = r * np.outer(np.ones(np.size(u)), np.cos(v))

# # Plot the sphere
# ax.plot_surface(x_sphere, y_sphere, z_sphere, color="b", alpha=0.1)
# # Set labels
# ax.set_xlabel("X")
# ax.set_ylabel("Y")
# ax.set_zlabel("Z")

# # azimuths = list(np.linspace(-175, 175, 50))
# azimuths = list(np.arange(-85, 85 + 5, 5))
# # elevations = list(np.linspace(-20, 20, 9))
# elevations = list(np.arange(-30, 30 + 5, 5))

# for azimuth in azimuths:
#     for elevation in elevations:
#         # If neither azimuth nor elevation is an edge pooint, skip
#         # is_top_point = abs(elevation - 20) < 1e-2
#         # is_bottom_point = abs(elevation + 20) < 1e-2
#         # is_left_point = abs(azimuth + 60) < 1e-2
#         # is_right_point = abs(azimuth - 60) < 1e-2
#         # if not any([is_top_point, is_bottom_point, is_left_point, is_right_point]):
#         #     continue

#         x, y, z = AzElSpherical(azimuth, elevation).to_cartesian(radius=1)
#         # ax.scatter(x, y, z, color='red', marker='o')
#         # ax.plot([0, x], [0, y], [0, z], color='red', linestyle=' ', marker='o', label="Normal coordinates", markersize=2)
#         x, y, z = AzElTurntable(azimuth, elevation).to_cartesian(radius=1)
#         ax.plot(
#             [0, x], [0, y], [0, z], color="blue", linestyle=" ", marker="o", label="Turntable coordinates", markersize=2
#         )
#         # ax.plot([0, x], [0, y], [0, z], color='black', alpha=0.1, linestyle='-', marker=' ', label="Turntable coordinates")

#         # ax.plot([0, x], [0, y], [0, z], color='blue', linestyle='-', marker='', label="turntable")

# # Remove duplicate labels from the legend
# handles, labels = ax.get_legend_handles_labels()
# unique_labels = dict(zip(labels, handles))
# ax.legend(unique_labels.values(), unique_labels.keys())
# # ax.legend()

# # Draw a translucent plane for the XY plane
# xx, yy = np.meshgrid(range(-1, 2), range(-1, 2))
# zz = np.zeros_like(xx)
# ax.plot_surface(xx, yy, zz, color="gray", alpha=0.2)

# # Draw a translucent plane for the YZ plane
# yy, zz = np.meshgrid(range(-1, 2), range(-1, 2))
# xx = np.zeros_like(yy)
# ax.plot_surface(xx, yy, zz, color="gray", alpha=0.2)

# # Draw a translucent plane for the XZ plane
# xx, zz = np.meshgrid(range(-1, 2), range(-1, 2))
# yy = np.zeros_like(xx)
# ax.plot_surface(xx, yy, zz, color="gray", alpha=0.2)

# print(f"{max(azimuths)=}")
# print(f"{min(azimuths)=}")
# print(f"{max(elevations)=}")
# print(f"{min(elevations)=}")

# plt.show()


def traditional_to_turntable_numpy(trad_azimuth_deg: float, trad_elevation_deg: float) -> tuple[float, float]:
    """
    Convert traditional spherical coordinates (azimuth and elevation) to turntable coordinates.

    The traditional spherical coordinates are defined as:
      x = cos(φ)*cos(θ)
      y = cos(φ)*sin(θ)
      z = sin(φ)
    and are related to the turntable coordinates by:
      x = cos(E)*cos(A)
      y = sin(A)
      z = sin(E)*cos(A)

    Solving for the turntable angles:
      - Turntable elevation (E):
          tan E = tan(φ) / cos(θ)
          E = arctan(tan(φ)/cos(θ))
      - Turntable azimuth (A):
          tan A = cos(E) * tan(θ)
          A = atan2(sin(θ), cos(θ)/cos(E))

    Parameters:
      trad_azimuth_deg (float): Traditional azimuth (θ) in degrees.
      trad_elevation_deg (float): Traditional elevation (φ) in degrees.

    Returns:
      tuple[float, float]: (turntable_elevation_deg, turntable_azimuth_deg)
    """
    # Convert input angles from degrees to radians.
    theta: float = np.radians(trad_azimuth_deg)  # traditional azimuth θ
    phi: float = np.radians(trad_elevation_deg)  # traditional elevation φ

    # Compute turntable elevation E from:
    # tan(E) = tan(φ)/cos(θ)
    E: float = np.arctan(np.tan(phi) / np.cos(theta))

    # Compute turntable azimuth A.
    # One robust way is to use the relation: tan A = cos(E)*tan(θ)
    # This is equivalent to:
    A: float = np.arctan2(np.sin(theta), np.cos(theta) / np.cos(E))

    # Convert the results back to degrees.
    turntable_elevation_deg: float = np.degrees(E)
    turntable_azimuth_deg: float = np.degrees(A)

    return turntable_azimuth_deg, turntable_elevation_deg


# Example usage:
if __name__ == "__main__":
    # Traditional spherical coordinates (example values):
    trad_az = 45.0  # Traditional azimuth in degrees
    trad_el = 30.0  # Traditional elevation in degrees

    tt_elev, tt_azim = traditional_to_turntable_numpy(trad_az, trad_el)
    print(f"Turntable Elevation: {tt_elev:.2f}°")
    print(f"Turntable Azimuth: {tt_azim:.2f}°")

if __name__ == "__main__":
    # Turntable angles (example): Elevation 30° then Azimuth 40°
    az_size = 85
    az_step = (az_size * 2) / 50
    az_step = 5
    azimuths = list(np.arange(-az_size, az_size + az_step, az_step))
    # azimuths = list(np.linspace(-60, 60, 20))
    el_size = 20
    el_step = 5
    elevations = list(reversed(np.arange(-el_size, el_size + el_step, el_step)))
    # elevations = list(reversed(list(np.arange(-20, 20 + 5, 5))))
    print(f"{len(azimuths)=}")
    print(f"{len(elevations)=}")
    print(f"{min(azimuths)=}")
    print(f"{max(azimuths)=}")
    print(f"{min(elevations)=}")
    print(f"{max(elevations)=}")

    fig, [ax_real, ax_turn] = plt.subplots(1, 2)
    ax_real: plt.Axes
    ax_turn: plt.Axes

    spherical_points = []
    turntable_points = []

    for elevation_index, elevation in enumerate(elevations):
        this_row_azimuths = azimuths if elevation_index % 2 == 0 else reversed(azimuths)
        for azimuth in this_row_azimuths:
            turntable = AzElTurntable(azimuth, elevation)
            spherical = turntable.to_spherical()

            spherical = AzElSpherical(azimuth, elevation)
            turntable = spherical.to_turntable()
            # turntable = spherical.as_turntable()
            spherical_points.append(spherical)
            turntable_points.append(turntable)
            # x, y, z = AzElSpherical(azimuth, elevation).to_cartesian(radius=1)
            # # print(f"{x=}, {y=}, {z=}")
            # x, y, z = AzElTurntable(azimuth, elevation).to_cartesian(radius=1)
            # # print(f"{x=}, {y=}, {z=}")
            # print()

    # Plot the spherical coordinates

    spherical_xs = [point.azimuth for point in spherical_points]
    spherical_ys = [point.elevation for point in spherical_points]
    ax_real.plot(spherical_xs, spherical_ys, color="black", label="Spherical coordinates", marker="o")

    # Plot the turn-table coordinates
    turntable_xs = [point.azimuth for point in turntable_points]
    turntable_ys = [point.elevation for point in turntable_points]
    ax_turn.plot(
        turntable_xs,
        turntable_ys,
        color="black",
        label="Turn-table coordinates",
        marker="o",
        # linestyle=" ",
        # markersize=0.5 * plt.rcParams["lines.markersize"],
    )

    ax_real.set_xlabel("Azimuth (degrees)")
    ax_real.set_ylabel("Elevation (degrees)")
    ax_real.grid(True)

    # Make a green dot at the first point
    ax_real.plot(
        spherical_xs[0],
        spherical_ys[0],
        color="#00ff00",
        marker="o",
        label="Start",
        markersize=2.5 * plt.rcParams["lines.markersize"],
        alpha=0.5,
    )

    # Make a red dot at the last point
    ax_real.plot(
        spherical_xs[-1],
        spherical_ys[-1],
        color="#ff0000",
        marker="o",
        label="End",
        markersize=2.5 * plt.rcParams["lines.markersize"],
        alpha=0.5,
    )

    ax_turn.set_xlabel("Azimuth (degrees)")
    ax_turn.set_ylabel("Elevation (degrees)")
    ax_turn.grid(True)

    # Make a green dot at the first point
    ax_turn.plot(
        turntable_xs[0],
        turntable_ys[0],
        color="#00ff00",
        alpha=0.5,
        marker="o",
        label="Start",
        markersize=2.5 * plt.rcParams["lines.markersize"],
    )

    # Make a red dot at the last point
    ax_turn.plot(
        turntable_xs[-1],
        turntable_ys[-1],
        color="#ff0000",
        alpha=0.5,
        marker="o",
        label="End",
        markersize=2.5 * plt.rcParams["lines.markersize"],
    )

    spherical_total_distance = 0
    for point1, point2 in zip(spherical_points[1:], spherical_points[:-1]):
        az_dist = abs(point1.azimuth - point2.azimuth)
        el_dist = abs(point1.elevation - point2.elevation)
        dist = max(az_dist, el_dist)
        spherical_total_distance += dist
    # ax_real.set_title("Spherical Coordinates")
    ax_real.set_title(
        f"Spherical Coordinates (N={len(spherical_xs):,})\nAzimuth range: [{min(spherical_xs):.2f}, {max(spherical_xs):.2f}]\nElevation range: [{min(spherical_ys):.2f}, {max(spherical_ys):.2f}]\n(total distance: {spherical_total_distance:.2f} deg)\n"
    )

    turntable_total_distance = 0
    for point1, point2 in zip(turntable_points[1:], turntable_points[:-1]):
        az_dist = abs(point1.azimuth - point2.azimuth)
        el_dist = abs(point1.elevation - point2.elevation)
        dist = max(az_dist, el_dist)
        turntable_total_distance += dist

    increase_percentage = (turntable_total_distance - spherical_total_distance) / spherical_total_distance
    ax_turn.set_title(
        f"Turn-table Coordinates (N={len(turntable_xs):,})\nAzimuth range: [{min(spherical_xs):.2f}, {max(spherical_xs):.2f}]\nElevation range: [{min(spherical_ys):.2f}, {max(spherical_ys):.2f}]\n(total distance: {turntable_total_distance:.2f} deg)\n{increase_percentage:.2%} increase"
    )

    for ax in [ax_real, ax_turn]:
        ax.set_xlim(-90, 90)
        ax.set_ylim(-90, 90)
        # ax.legend()
        ax.set_aspect("equal", adjustable="box")
        ax.set_xticks(np.arange(-90, 91, 15))
        ax.set_yticks(np.arange(-90, 91, 15))
    plt.show()

    points: list[AzElTurntable] = []
    for tt_azimuth in range(-180, 181, 10):
        for tt_elevation in range(-90, 45, 5):
            tt_point = AzElTurntable(azimuth=tt_azimuth, elevation=tt_elevation)
            points.append(tt_point)
    spherical_points = [point.to_spherical for point in points]

    points: list[AzElSpherical] = []
    for real_azimuth in range(-180, 181, 15):
        for real_elevation in range(-90, 90, 5):
            real_point = AzElSpherical(azimuth=real_azimuth, elevation=real_elevation)
            points.append(real_point)

    spherical_points = points[:]
    # spherical_points = [point.to_spherical for point in points]

    fig = plt.figure()
    ax: plt.Axes = fig.add_subplot(111, projection="3d")
    print(type(ax))

    # Plot the spherical points
    xs, ys, zs = [], [], []
    for point in spherical_points:
        x, y, z = point.to_cartesian(radius=1)
        xs.append(x)
        ys.append(y)
        zs.append(z)

        tt_coord = point.to_turntable()
        if tt_coord.elevation >= 45:
            color = "red"
            # ax.scatter(x, y, z, color=color, marker='o')
        else:
            color = "blue"

    # sc = ax.scatter(xs, ys, zs, c=zs, cmap='coolwarm', marker='o')
    # # Add color bar
    # cbar = plt.colorbar(sc, ax=ax, shrink=0.5, aspect=5)
    # cbar.set_label('Z value')
    # sc.set_cmap('coolwarm')
    # Set labels
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")

    # Set aspect ratio
    ax.set_box_aspect([1, 1, 1])

    # Create a mesh grid for the sphere
    u = np.linspace(0, 2 * np.pi, 30)
    v = np.linspace(0, np.pi, 30)
    r = 0.98
    x_sphere = r * np.outer(np.cos(u), np.sin(v))
    y_sphere = r * np.outer(np.sin(u), np.sin(v))
    z_sphere = r * np.outer(np.ones(np.size(u)), np.cos(v))

    # Plot the sphere
    ax.plot_surface(x_sphere, y_sphere, z_sphere, color="gray", alpha=0.2)

    # Create an arrow from the origin to the point (2, 0, 0)
    ax.quiver(0, 0, 0, 1.5, 0, 0, color="red", arrow_length_ratio=0.1)

    # Add text at the tip of the arrow
    ax.text(1.5, 0, 0, "horizontal", color="red")

    # Create an arrow tilted up 3 degrees from horizontal
    tilt_angle_deg = 3
    tilt_angle_rad = np.radians(tilt_angle_deg)

    # Calculate the components of the arrow
    arrow_length = 1.5
    x_tilted = arrow_length * np.cos(tilt_angle_rad)
    z_tilted = arrow_length * np.sin(tilt_angle_rad)

    # Create the tilted arrow
    ax.quiver(0, 0, 0, x_tilted, 0, z_tilted, color="green", arrow_length_ratio=0.1)

    # Add text at the tip of the tilted arrow
    ax.text(x_tilted, 0, z_tilted, f"source", color="green")

    # Add black circles along the xy plane
    theta = np.linspace(0, 2 * np.pi, 100)
    r = 1
    x_circle = r * np.cos(theta)
    y_circle = r * np.sin(theta)
    z_circle = np.zeros_like(theta)
    ax.plot(x_circle, y_circle, z_circle, color="black", linestyle="-", linewidth=0.5)

    # Add black circles along the yz plane
    y_circle = r * np.cos(theta)
    z_circle = r * np.sin(theta)
    x_circle = np.zeros_like(theta)
    ax.plot(x_circle, y_circle, z_circle, color="red", linestyle="-", linewidth=1.5)

    # Add black circles along the xz plane
    x_circle = r * np.cos(theta)
    z_circle = r * np.sin(theta)
    y_circle = np.zeros_like(theta)
    ax.plot(x_circle, y_circle, z_circle, color="black", linestyle="-", linewidth=0.5)

    # Add red circle through the points (1, 0, 1) and (0, 1, 0), centered at the origin
    theta = np.linspace(0, 2 * np.pi, 100)
    r = 1  # radius for the circle passing through (1, 0, 1) and (0, 1, 0)
    x_circle = r * np.cos(theta) * 1 / np.sqrt(2)
    y_circle = r * np.sin(theta)
    z_circle = r * np.cos(theta) * 1 / np.sqrt(2)
    ax.plot(x_circle, y_circle, z_circle, color="red", linestyle="-", linewidth=1.5)

    plt.show()
