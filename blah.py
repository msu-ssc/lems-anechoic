import matplotlib.pyplot as plt
import numpy as np

# Sample data points (replace with your actual data)
x = np.array([1, 2, 3, 1, 2, 3, 1, 2, 3])
y = np.array([1, 1, 1, 2, 2, 2, 3, 3, 3])
z = np.array([5, 7, 6, 8, 9, 7, 6, 8, 5])

# Create the tricontourf plot
fig, ax = plt.subplots()
c = ax.tricontourf(x, y, z, levels=10)
fig.colorbar(c, ax=ax, label='Z values')
ax.set_xlabel('X')
ax.set_ylabel('Y')
ax.set_title('tricontourf from Points')
plt.show()
