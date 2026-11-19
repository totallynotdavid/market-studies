from contextlib import closing
from datetime import date
from pathlib import Path

import httpx2
import numpy as np
import pandas as pd

from bvl import earnings, fetch, smv, store


FIXTURES = Path(__file__).parent / "fixtures"


def test_due_days_match_the_smv_2021_calendar() -> None:
    ends = ["2020-12-31", "2021-03-31", "2021-06-30", "2021-09-30", "2021-12-31"]
    statements = pd.DataFrame(
        {
            "quarter_end": pd.to_datetime(ends * 2),
            "quarter": [4, 1, 2, 3, 4] * 2,
            "consolidated": [False] * 5 + [True] * 5,
        }
    )
    published = [
        # Individual, then consolidated, as in the SMV calendar.
        "2021-02-15", "2021-04-30", "2021-08-02", "2021-11-02", "2022-02-15",
        "2021-03-01", "2021-05-17", "2021-08-16", "2021-11-15", "2022-03-01",
    ]  # fmt: skip
    assert list(earnings.due(statements)) == list(pd.to_datetime(published))


def test_due_days_match_the_smv_2026_calendar() -> None:
    statements = pd.DataFrame(
        {
            "quarter_end": pd.to_datetime(
                ["2025-12-31", "2026-06-30", "2026-09-30", "2026-12-31"]
            ),
            "quarter": [4, 2, 3, 4],
            "consolidated": [True, False, False, True],
        }
    )
    # BVL quotes have no market day from 27 July to 3 August 2026; the limit
    # still falls on 31 July.
    published = ["2026-03-02", "2026-07-31", "2026-11-02", "2027-03-01"]
    assert list(earnings.due(statements)) == list(pd.to_datetime(published))


def test_a_decreed_non_working_day_moves_the_limit() -> None:
    # DS 002-2019-PCM closed Thursday 31 October 2019; 1 November is a holiday.
    statements = pd.DataFrame(
        {
            "quarter_end": [pd.Timestamp("2019-09-30")],
            "quarter": [3],
            "consolidated": [False],
        }
    )
    assert earnings.due(statements).iloc[0] == pd.Timestamp("2019-11-04")


def test_news_needs_the_same_quarter_a_year_before_in_the_same_currency() -> None:
    statements = pd.DataFrame(
        {
            "rpj": ["A", "A", "B", "B", "C"],
            "consolidated": [False] * 5,
            "quarter": [2] * 5,
            "year": [2019, 2020, 2019, 2020, 2020],
            "currency": ["PEN", "PEN", "PEN", "USD", "PEN"],
            "net_income": [10.0, 30.0, 5.0, 6.0, 1.0],
            "assets": [200.0, 250.0, 100.0, 100.0, 50.0],
        }
    )
    news = earnings.news(statements)
    # A grew 20 on 200 of year-earlier assets; B switched to dollars; C is new.
    assert np.isnan(news.iloc[0])
    assert news.iloc[1] == 0.1
    assert news.iloc[2:].isna().all()


def test_fill_statements_skips_a_quarter_that_has_not_ended(tmp_path: Path) -> None:
    asked: list[tuple[str, str]] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        asked.append((request.url.params["sPeriodo"], request.url.params["sTipoInf"]))
        return httpx2.Response(200, content=(FIXTURES / "statements.json").read_bytes())

    client = smv.SmvClient(None, transport=httpx2.MockTransport(answer))
    with closing(store.connect(tmp_path / "bvl.sqlite")) as connection:
        fetch.fill_statements(
            client, connection, date(2025, 1, 1), date(2025, 12, 31), date(2025, 8, 1)
        )
    assert asked == [("1", "I"), ("1", "C"), ("2", "I"), ("2", "C")]
