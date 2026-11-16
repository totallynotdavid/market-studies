import numpy as np
import pandas as pd
import pytest

from bvl import politics


def synthetic(shock: float, beta: float = 0.5) -> pd.DataFrame:
    """An index driven by copper with `beta`, plus one shock on day 300."""
    rng = np.random.default_rng(7)
    days = pd.bdate_range("2020-01-01", periods=320)
    copper = rng.normal(0, 0.02, len(days))
    sol = rng.normal(0, 0.003, len(days))
    r = 0.0002 + beta * copper + rng.normal(0, 0.01, len(days))
    r[300] += shock
    return pd.DataFrame({"r": r, "copper": copper, "sol": sol}, index=days)


def test_event_table_removes_copper_and_keeps_the_shock() -> None:
    daily = synthetic(shock=-0.06)
    day0 = daily.index[300].date().isoformat()
    row = politics.event_table(daily, (politics.Event(day0, "shock"),)).iloc[0]

    assert row["beta"] == pytest.approx(0.5, abs=0.1)
    assert row["sd"] == pytest.approx(0.01, rel=0.15)
    assert row["fit_days"] == 250
    # The abnormal return is the shock plus that day's own noise.
    assert row["abnormal"] == pytest.approx(-0.06, abs=0.025)
    assert row["z"] < -3
    assert row["share_as_large"] < 0.01


def test_event_table_refuses_a_day_off_the_calendar() -> None:
    daily = synthetic(shock=0.0)
    with pytest.raises(KeyError):
        politics.event_table(daily, (politics.Event("2020-01-04", "Saturday"),))
