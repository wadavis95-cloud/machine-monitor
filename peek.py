# Import Path to find the dataset relative to this script.
from pathlib import Path

# Import the C-MAPSS data loader.
from loader import load_data

# Load the FD001 training data.
data = load_data(Path(__file__).parent / "data" / "train_FD001.txt")
# Print the first five rows with every column visible.
print(data.head(5).to_string(index=False))
# Print the number of rows and columns.
print("Shape (rows, columns):", data.shape)
# Select the cycle numbers for engine 1.
cycles = data.loc[data["unit"] == 1, "cycle"]
# Print the first and last cycle numbers for engine 1.
print(f"Engine 1 cycles: first = {cycles.iloc[0]}, last = {cycles.iloc[-1]}")
