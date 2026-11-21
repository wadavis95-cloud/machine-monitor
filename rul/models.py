import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


class LinearRUL:
    """Estimate remaining cycles from the current row's scaled readings."""

    def __init__(self):
        self._model = LinearRegression()

    def fit(self, train_df: pd.DataFrame, features: list[str]) -> None:
        self._model.fit(train_df[features], train_df["rul_true"])
        self._features = features.copy()

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self._model.predict(df[self._features])
