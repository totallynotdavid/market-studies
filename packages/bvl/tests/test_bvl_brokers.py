from contextlib import closing
from datetime import date
from pathlib import Path

import httpx2
import pandas as pd
import pytest

from bvl import brokers, fetch, smv, store


FIXTURES = Path(__file__).parent / "fixtures"


def test_fill_broker_amounts_stamps_each_row_with_its_day(tmp_path: Path) -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=(FIXTURES / "brokers.json").read_bytes())

    client = smv.SmvClient(None, transport=httpx2.MockTransport(answer))
    db = tmp_path / "bvl.sqlite"
    with closing(store.connect(db)) as connection:
        fetch.fill_broker_amounts(
            client, connection, [date(2025, 1, 6)], date(2026, 1, 1)
        )
    rows = store.read(db, "SELECT * FROM broker_amounts ORDER BY broker")

    assert list(rows["broker"]) == ["CRE", "GCO", "ITG"]
    assert set(rows["date"]) == {"2025-01-06"}
    assert rows["sold"].iloc[2] == 6944573.36


def frame(days: dict[str, dict[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp(day),
                "broker": broker,
                "name": broker,
                "total": total,
            }
            for day, totals in days.items()
            for broker, total in totals.items()
        ]
    )


def test_concentration_weights_a_year_by_amount_and_a_day_equally() -> None:
    # Day 1: A alone, HHI 10,000. Day 2: A 25% and B 75%, HHI 625 + 5,625.
    rows = frame({"2020-01-02": {"A": 60.0}, "2020-01-03": {"A": 10.0, "B": 30.0}})
    year = brokers.concentration_by_year(rows).loc[2020]

    # The year: A has 70 of 100, B 30, so 4,900 + 900.
    assert year["hhi"] == pytest.approx(5800)
    assert year["daily_hhi"] == pytest.approx((10_000 + 6_250) / 2)
    assert year["firms"] == 2
    assert year["days"] == 2
    assert year["top1"] == pytest.approx(0.7)
    assert year["top3"] == pytest.approx(1.0)
