class EngineReplayer:
    """Replay one engine's readings in cycle order."""

    def __init__(self, df, unit):
        rows = df.loc[df["unit"] == unit].sort_values("cycle", kind="stable")
        self._rows = iter(rows.to_dict(orient="records"))

    def next(self):
        """Return the next row, or None when playback is exhausted."""
        return next(self._rows, None)
