import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("lab_data.csv", parse_dates=["timestamp_utc"])

print(df.head())

print(df.dtypes)

fig, (ax_azimuth, ax_elevation) = plt.subplots(1, 2, subplot_kw={'projection': 'polar'}, layout='constrained')
ax_azimuth: plt.Axes
ax_elevation: plt.Axes

azimuth_cut_df = df[df["cut_id"] == "azimuth-cut"]
elevation_cut_df = df[df["cut_id"] == "elevation-cut"]

azimuth_cut_angles = azimuth_cut_df["actual_azimuth"].to_numpy()
azimuth_cut_angles_radians = np.radians(azimuth_cut_angles)
azimuth_cut_center_frequency_amplitude = azimuth_cut_df["center_amplitude"].to_numpy()
azimuth_cut_peak_amplitude = azimuth_cut_df["peak_amplitude"].to_numpy()

elevation_cut_angles = elevation_cut_df["actual_elevation"].to_numpy()
elevation_cut_angles_radians = np.radians(elevation_cut_angles)
elevation_cut_center_frequency_amplitude = elevation_cut_df["center_amplitude"].to_numpy()
elevation_cut_peak_amplitude = elevation_cut_df["peak_amplitude"].to_numpy()



# azimuths = df["actual_azimuth"].to_numpy()
# elevations = df["actual_elevation"].to_numpy()

# azimuths_radians = np.radians(azimuths)
# elevations_radians = np.radians(elevations)

# peak_amplitude = df["peak_amplitude"].to_numpy()
# center_frequency_amplitude = df["center_amplitude"].to_numpy()

ax_azimuth.plot(azimuth_cut_angles_radians, azimuth_cut_peak_amplitude, label="Peak")
ax_azimuth.plot(azimuth_cut_angles_radians, azimuth_cut_center_frequency_amplitude, label="CF")
ax_azimuth.set_title("Azimuth\nCut", fontsize=20, loc="left")

ax_elevation.plot(elevation_cut_angles_radians, elevation_cut_peak_amplitude, label="Peak")
ax_elevation.plot(elevation_cut_angles_radians, elevation_cut_center_frequency_amplitude, label="CF")
ax_elevation.set_title("Elevation\nCut", fontsize=20, loc="right")

for ax in [ax_azimuth, ax_elevation]:
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)
    # ax.set_thetagrids(range(0, 360, 15))
    ax.set_thetalim(-np.pi, np.pi)
    x_ticks = list(np.arange(-180, 180, 15))
    ax.set_xticks(np.radians(x_ticks))
    ax.set_xticklabels([f"{int(t)}°" for t in x_ticks])
    ax.legend()
plt.show()