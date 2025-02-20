import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D


count = 60
azimuths = np.linspace(-180, 180, count)

fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')
ax.set_box_aspect([1,1,1])  # Aspect ratio is 1:1:1 to make the sphere look like a real sphere

elevation = 0
r = 1  # radius

x = r * np.cos(np.radians(azimuths)) * np.cos(np.radians(elevation))
y = r * np.sin(np.radians(azimuths)) * np.cos(np.radians(elevation))
z = r * np.sin(np.radians(elevation))

ax.scatter(x, y, z, label="Elevation 0")

elevation_45 = 30
x_45 = r * np.cos(np.radians(azimuths)) * np.cos(np.radians(elevation_45))
y_45 = r * np.sin(np.radians(azimuths)) * np.cos(np.radians(elevation_45))
z_45 = r * np.sin(np.radians(elevation_45))

ax.scatter(x_45, y_45, z_45, label="Elevation 30 (normal coordinates)")
# Create a translucent sphere
u = np.linspace(0, 2 * np.pi, count)
v = np.linspace(0, np.pi, count)
x_sphere = 0.99 * np.outer(np.cos(u), np.sin(v))
y_sphere = 0.99 * np.outer(np.sin(u), np.sin(v))
z_sphere = 0.99 * np.outer(np.ones(np.size(u)), np.cos(v))

ax.plot_surface(x_sphere, y_sphere, z_sphere, color='b', alpha=0.1)
ax.set_xlabel('X')
ax.set_ylabel('Y')
ax.set_zlabel('Z')
ax.set_xlim([-1, 1])
ax.set_ylim([-1, 1])
ax.set_zlim([-1, 1])


def draw_great_circle(ax, point):
    """Draw a great circle through the given point centered at the origin."""
    # Normalize the point to lie on the unit sphere
    point = point / np.linalg.norm(point)
    
    # Find two orthogonal vectors on the plane of the great circle
    if point[0] == 0 and point[1] == 0:
        ortho1 = np.array([1, 0, 0])
    else:
        ortho1 = np.array([-point[1], point[0], 0])
    ortho1 = ortho1 / np.linalg.norm(ortho1)
    ortho2 = np.cross(point, ortho1)
    
    phi = np.linspace(0, 2 * np.pi, count)
    
    # Parametric equation of the great circle
    x_circle = np.outer(np.cos(phi), ortho1) + np.outer(np.sin(phi), ortho2)
    x_circle = x_circle * r
    
    ax.scatter(x_circle[:, 0], x_circle[:, 1], x_circle[:, 2], label=f"Elevation 30 (turntable coordinates)")

# Example usage
point = np.array([1, 1, 3])
draw_great_circle(ax, point)


ax.view_init(elev=45, azim=45)
ax.legend()
plt.show()