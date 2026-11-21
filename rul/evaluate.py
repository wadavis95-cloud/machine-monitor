import numpy as np


def rmse(y_true, y_pred) -> float:
    """Measure prediction error in cycles, giving larger errors more weight."""
    error = np.asarray(y_pred, dtype=float) - np.asarray(y_true, dtype=float)
    return float(np.sqrt(np.mean(error ** 2)))


def nasa_score(y_true, y_pred) -> float:
    """Sum the NASA penalties across predictions. Lower is better."""
    error = np.asarray(y_pred, dtype=float) - np.asarray(y_true, dtype=float)
    # Predicting too many cycles left can delay maintenance.
    # Dividing that error by 10 instead of 13 makes the penalty grow faster.
    exponent = np.where(error < 0, -error / 13, error / 10)
    return float(np.expm1(exponent).sum())
