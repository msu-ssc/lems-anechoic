# Import necessary libraries
import matplotlib.pyplot as plt  # For plotting graphs
import numpy as np  # For numerical operations
import pandas as pd  # For data manipulation

# Read the CSV file into a DataFrame
df = pd.read_csv(R"C:\Users\ssc\dev\lems-anechoic\lab_data.known_good.csv", parse_dates=["timestamp_utc"])

# # Filter out points where commanded azimuth and actual azimuth differ by more than 1.0 degree
# df = df[np.abs(df["commanded_azimuth"] - df["actual_azimuth"]) <= 1.0]
# # Filter out points where commanded elevation and actual elevation differ by more than 1.0 degree
# df = df[np.abs(df["commanded_elevation"] - df["actual_elevation"]) <= 1.0]
# Print the first few rows of the DataFrame to understand its structure
print(df.head())

# Print the data types of each column in the DataFrame
print(df.dtypes)

# Create a figure with two polar subplots
fig, (ax_azimuth, ax_elevation) = plt.subplots(1, 2, subplot_kw={'projection': 'polar'}, layout='constrained')
ax_azimuth: plt.Axes  # Type hint for the azimuth axis
ax_elevation: plt.Axes  # Type hint for the elevation axis

# Filter the DataFrame for azimuth and elevation cuts
azimuth_cut_df = df[df["cut_id"] == "azimuth-cut"]
elevation_cut_df = df[df["cut_id"] == "elevation-cut"]

# Extract azimuth angles and convert them to radians
azimuth_cut_angles = azimuth_cut_df["actual_azimuth"].to_numpy()
azimuth_cut_angles_radians = np.radians(azimuth_cut_angles)
# Extract center frequency amplitude and peak amplitude for azimuth cut
azimuth_cut_center_frequency_amplitude = azimuth_cut_df["center_amplitude"].to_numpy()
azimuth_cut_peak_amplitude = azimuth_cut_df["peak_amplitude"].to_numpy()

# Extract elevation angles and convert them to radians
elevation_cut_angles = elevation_cut_df["actual_elevation"].to_numpy()
elevation_cut_angles_radians = np.radians(elevation_cut_angles)
# Extract center frequency amplitude and peak amplitude for elevation cut
elevation_cut_center_frequency_amplitude = elevation_cut_df["center_amplitude"].to_numpy()
elevation_cut_peak_amplitude = elevation_cut_df["peak_amplitude"].to_numpy()

# Plot azimuth cut data on the azimuth axis
ax_azimuth.plot(azimuth_cut_angles_radians, azimuth_cut_peak_amplitude, "o-", label="Peak")
ax_azimuth.plot(azimuth_cut_angles_radians, azimuth_cut_center_frequency_amplitude, "o-", label="CF")
ax_azimuth.set_title("Azimuth\nCut", fontsize=20, loc="left")

# Plot elevation cut data on the elevation axis
ax_elevation.plot(elevation_cut_angles_radians, elevation_cut_peak_amplitude, "o-", label="Peak")
ax_elevation.plot(elevation_cut_angles_radians, elevation_cut_center_frequency_amplitude, "o-", label="CF")
ax_elevation.set_title("Elevation\nCut", fontsize=20, loc="right")

# Customize the appearance of both polar plots
for ax in [ax_azimuth, ax_elevation]:
    ax.set_theta_zero_location('N')  # Set the zero location to the top (North)
    ax.set_theta_direction(-1)  # Set the direction of the angle to clockwise
    # ax.set_thetagrids(range(0, 360, 15))  # Optional: set the grid lines for every 15 degrees
    ax.set_thetalim(-np.pi, np.pi)  # Set the limit for theta from -pi to pi
    x_ticks = list(np.arange(-180, 180, 15))  # Create a list of x-ticks from -180 to 180 degrees
    ax.set_xticks(np.radians(x_ticks))  # Set the x-ticks in radians
    ax.set_xticklabels([f"{int(t)}°" for t in x_ticks])  # Label the x-ticks with degree symbols
    ax.legend()  # Add a legend to the plot

# Display the plots
plt.show()