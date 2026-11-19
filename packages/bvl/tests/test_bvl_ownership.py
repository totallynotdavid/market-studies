from contextlib import closing
from datetime import date
from pathlib import Path

import httpx2
import numpy as np
import pandas as pd
import pytest

from bvl import fetch, ownership, smv, store


FIXTURES = Path(__file__).parent / "fixtures"


def test_a_fetched_register_gives_each_class_its_float_and_foreign_stake(
    tmp_path: Path,
) -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=(FIXTURES / "holders.json").read_bytes())

    db = tmp_path / "bvl.sqlite"
    client = smv.SmvClient(None, transport=httpx2.MockTransport(answer))
    with closing(store.connect(db)) as connection:
        fetch.fill_holders(client, connection, date(2026, 11, 19))

    holders = ownership.load(db)
    # AUNA files under RUC 0, shared by every foreign issuer.
    assert set(holders["company"]) == {
        "ALICORP S.A.A.",
        "VOLCAN COMPAÑIA MINERA S.A.A.",
    }
    assert set(holders["since"]) == {
        "2026-03-25",
        "2017-06-21",
        "2017-08-07",
        "2024-05-08",
    }

    frame = ownership.classes(holders).set_index("share_class")
    alicorp, volcan = frame.loc["common"], frame.loc["A"]
    assert alicorp["holders"] == 3
    assert alicorp["largest"] == 21.46
    assert alicorp["free_float"] == pytest.approx(100 - 52.29)
    assert alicorp["foreign"] == pytest.approx(19.24)
    assert not alicorp["largest_foreign"]
    assert volcan["holders"] == 5
    assert volcan["free_float"] == pytest.approx(100 - 94.821001)
    assert volcan["foreign"] == pytest.approx(63.41)
    assert volcan["largest_foreign"]


def test_register_spellings_map_to_a_share_class() -> None:
    cases = {
        "": "common",
        "COMUNES": "common",
        "comunes": "common",
        "Común": "common",
        "Acciones Comunes": "common",
        "ACC. COMUNES": "common",
        "CAPITAL": "common",
        "C1": "common",
        "MINCORC1": "common",
        "A": "A",
        "D": "D",
        "AyB": None,
        "A,B,C": None,
        "CLASE A Y B": None,
        "FUNDADORES": None,
        "S1": None,
    }
    got = {series: ownership.share_class(series) for series in cases}
    assert got == cases


def test_holder_names_map_to_a_kind() -> None:
    cases = {
        "ESTADO PERUANO": "state",
        "MUNICIPALIDAD PROVINCIAL DEL CUSCO": "state",
        "FONDO CONSOLIDADO DE RESERVAS PREVISIONALES - FCR": "state",
        "PRIMA AFP S.A.": "pension fund",
        "HA-FONDO 2": "pension fund",
        "IN - FONDO 2 (AFP INTEGRA)": "pension fund",
        "CILLONIZ CHAMPIN, RICARDO": "person",
        "BANCO SANTANDER, S.A.": "company",
        "LFLP HOLDINGS, LLC": "company",
        "ENFOCA DESCUBRIDOR 2 , FONDO DE INVERSION": "company",
        "TRANSITION METALS AG": "company",
    }
    got = {name: ownership.kind(name) for name in cases}
    assert got == cases


def test_listed_stakes_over_100_leave_no_float() -> None:
    holders = pd.DataFrame(
        {
            "ruc": ["1", "1"],
            "company": ["X", "X"],
            "percent": [60.01, 40.01],
            "share_class": ["common", "common"],
            "kind": ["company", "person"],
            "foreign": [False, False],
        }
    )
    assert ownership.classes(holders).iloc[0]["free_float"] == 0


def test_a_class_takes_the_most_traded_ticker_that_carries_its_letter() -> None:
    frame = pd.DataFrame(
        {"ruc": ["1", "1", "2", "3"], "share_class": ["A", "B", "common", "common"]}
    )
    links = pd.DataFrame(
        {
            "ruc": ["1", "1", "1", "2", "2"],
            "ticker": ["VOLCAAC1", "VOLCABC1", "VOLCABI1", "ALICORC1", "ALICORI1"],
        }
    )
    traded = pd.Series(
        {"VOLCAAC1": 30, "VOLCABC1": 240, "ALICORC1": 250, "ALICORI1": 251}
    )
    picked = ownership.class_tickers(frame, links, traded)
    assert picked.iloc[:3].tolist() == ["VOLCAAC1", "VOLCABC1", "ALICORC1"]
    assert pd.isna(picked.iloc[3])


def test_a_partial_rank_correlation_removes_a_shared_driver() -> None:
    rng = np.random.default_rng(0)
    size = pd.Series(rng.normal(size=500))
    x = size + 0.3 * pd.Series(rng.normal(size=500))
    y = size + 0.3 * pd.Series(rng.normal(size=500))
    assert ownership.rank_correlation(x, y) > 0.8
    assert abs(ownership.rank_correlation(x, y, size)) < 0.15
