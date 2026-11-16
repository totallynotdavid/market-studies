from contextlib import closing
from datetime import date
from pathlib import Path

import httpx2

from bvl import bcrp, fetch, store


FIXTURES = Path(__file__).parent / "fixtures"


def test_period_day_reads_spanish_months_across_the_century() -> None:
    assert bcrp.period_day("02.Ene.97") == date(1997, 1, 2)
    assert bcrp.period_day("30.Set.19") == date(2019, 9, 30)


def test_fill_bcrp_stores_each_series_without_unpublished_days(tmp_path: Path) -> None:
    requests: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=(FIXTURES / "bcrp.json").read_bytes())

    client = bcrp.BcrpClient(transport=httpx2.MockTransport(answer))
    db = tmp_path / "bvl.sqlite"
    with closing(store.connect(db)) as connection:
        fetch.fill_bcrp(client, connection, date(2026, 11, 10), date(2026, 11, 16))
    rows = store.read(db, "SELECT * FROM bcrp_series WHERE code = 'PD04638PD'")

    assert requests[0].url.path.endswith("/PD04638PD/json/2026-11-10/2026-11-16")
    assert len(requests) == len(bcrp.SERIES)
    # The fixture's 13 and 16 Nov read "n.d.".
    assert list(rows["date"]) == ["2026-11-10", "2026-11-11", "2026-11-12"]
    assert rows["value"].iloc[-1] == 3.40585714285714
