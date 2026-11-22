from copy import deepcopy

import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from rul.data import RUL_CAP, SEED, make_windows, validation_cutoffs


def _window_features(df: pd.DataFrame, features: list[str]) -> np.ndarray:
    windows = make_windows(df, [*features, "cycle"])
    readings = windows[:, :, :-1]
    cycles = windows[:, :, -1]
    means = readings.mean(axis=1)

    # Slope is the change in a reading per cycle along its best-fit line.
    centered_cycles = cycles - cycles.mean(axis=1, keepdims=True)
    cycle_spread = (centered_cycles**2).sum(axis=1, keepdims=True)
    trend = (readings * centered_cycles[:, :, None]).sum(axis=1)
    # A window with only one observed cycle has no trend yet.
    slopes = np.divide(
        trend, cycle_spread, out=np.zeros_like(trend), where=cycle_spread > 0
    )
    return np.concatenate((means, slopes), axis=1)


class LinearRUL:
    """Estimate remaining cycles from the current row's scaled readings."""

    def __init__(self):
        self._model = LinearRegression()

    def fit(self, train_df: pd.DataFrame, features: list[str]) -> None:
        self._model.fit(train_df[features], train_df["rul_true"])
        self._features = features.copy()

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self._model.predict(df[self._features])


class TreesRUL:
    """Use gradient boosting on window means and slopes.

    Its validation RMSE was 13.96 cycles versus 18.89 for random forest.
    The gap was larger than the variation across seeds.
    """

    def __init__(self):
        self._model = GradientBoostingRegressor(
            n_estimators=100, max_depth=5, random_state=SEED
        )

    def fit(self, train_df: pd.DataFrame, features: list[str]) -> None:
        self._model.fit(_window_features(train_df, features), train_df["rul_true"])
        self._features = features.copy()

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self._model.predict(_window_features(df, self._features))


class _LSTMNetwork(nn.Module):
    def __init__(self, inputs: int, hidden: int):
        super().__init__()
        self.lstm = nn.LSTM(inputs, hidden, batch_first=True)
        self.head = nn.Linear(hidden, 1)

    def forward(self, windows: torch.Tensor) -> torch.Tensor:
        steps, _ = self.lstm(windows)
        # The last step has read the whole window.
        return self.head(steps[:, -1, :]).squeeze(-1)


class LSTMRUL:
    """Estimate remaining cycles from each row's recent readings on CPU."""

    def __init__(self, epochs: int = 20, hidden: int = 16, lr: float = 0.003):
        self.epochs = epochs
        self.hidden = hidden
        self.lr = lr

    def fit(
        self,
        train_df: pd.DataFrame,
        features: list[str],
        val_df: pd.DataFrame | None = None,
    ) -> None:
        """Train on scaled readings, with optional full validation histories."""
        torch.manual_seed(SEED)
        self._features = features.copy()
        self._model = _LSTMNetwork(len(features), self.hidden)
        batches = DataLoader(
            TensorDataset(self._windows(train_df), self._targets(train_df)),
            batch_size=256,
            shuffle=True,
        )

        validation = None
        if val_df is not None:
            val_df = val_df.reset_index(drop=True)
            cutoffs = validation_cutoffs(val_df)
            # Build history from every row, then keep only the windows at cutoffs.
            windows = self._windows(val_df)[cutoffs.index.to_numpy(copy=True)]
            validation = windows, self._targets(cutoffs)
        self._train(batches, validation)

    def _train(self, batches, validation) -> None:
        optimizer = torch.optim.Adam(self._model.parameters(), lr=self.lr)
        mse = nn.MSELoss()
        best_rmse = float("inf")
        best_weights = None
        stale_epochs = 0

        for _ in range(self.epochs):
            self._model.train()
            for windows, targets in batches:
                optimizer.zero_grad()
                # Forward: predict from the windows in this batch.
                predictions = self._model(windows)
                # Loss: measure how far the predictions are from the targets.
                loss = mse(predictions, targets)
                # Backward: calculate how each weight contributed to the error.
                loss.backward()
                # Step: update the weights using those gradients.
                optimizer.step()

            if validation is not None:
                self._model.eval()
                windows, targets = validation
                with torch.no_grad():
                    cutoff_rmse = (
                        mse(self._model(windows), targets).sqrt().item() * RUL_CAP
                    )
                if cutoff_rmse < best_rmse:
                    best_rmse = cutoff_rmse
                    best_weights = deepcopy(self._model.state_dict())
                    stale_epochs = 0
                else:
                    stale_epochs += 1
                    if stale_epochs == 4:
                        break

        if best_weights is not None:
            self._model.load_state_dict(best_weights)

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        self._model.eval()
        with torch.no_grad():
            predictions = [self._model(batch) for batch in self._windows(df).split(256)]
        return torch.cat(predictions).numpy() * RUL_CAP

    def _windows(self, df: pd.DataFrame) -> torch.Tensor:
        return torch.as_tensor(make_windows(df, self._features), dtype=torch.float32)

    @staticmethod
    def _targets(df: pd.DataFrame) -> torch.Tensor:
        # Learn on a 0–1 scale and convert back to cycles at prediction time.
        return torch.as_tensor(df["rul_true"].to_numpy() / RUL_CAP, dtype=torch.float32)
