"""Who holds BVL issuers, from the SMV's register of holders, and whether a
concentrated register trades less.

The SMV lists each holder of an issuer's shares with a stake of about 4% or
more (the smallest in the 2026-11-19 snapshot is 4.02%) and the share class it
holds. A class is the issuer's common shares when the register leaves the
class blank or names it common, or one lettered class (`A`, `B`) of an issuer
with several. The listed stakes summed are the class's block holdings, and
100 less that sum is its free float: what holders under the listing threshold
own. That float is an upper bound, since several small stakes may move
together.
"""

import itertools
import re

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from bvl import issuers, liquidity, panel, politics, store


if TYPE_CHECKING:
    from pathlib import Path

COMMON = "common"
# Register spellings of the common class: blank, `COMUNES`, `Acciones Comunes`,
# `Común`, `CAPITAL`, and the common ticker or its suffix (`MINCORC1`, `C1`).
_COMMON_SERIES = re.compile(r"^((ACC(IONES|\.)?\s*)?COMUN(ES)?|CAPITAL|[A-Z]*C1)?$")
_LETTER_SERIES = re.compile(r"^[A-D]$")
LOCAL = {"PERU", "NO INDICA", ""}

_STATE = re.compile(r"\bESTADO\b|MUNICIPALIDAD|FONAFE|RESERVAS PREVISIONALES")
_PENSION = re.compile(r"\bAFP\b|^[A-Z]{2} ?- ?FONDO \d|^[A-Z]{2}-FONDO")
# A legal form or word that marks a company even when the name has a comma,
# as in `BANCO SANTANDER, S.A.` or `LFLP HOLDINGS, LLC`.
_COMPANY = re.compile(
    r"\b(S\.?A\.?|INC|LLC|LTD|S\.?L\.?|N\.?A\.?|CORPORATION|FONDO|SOCIOS|BANCO)\b"
)
KINDS = ("state", "pension fund", "person", "company")

FREE_FLOAT_BANDS = (0, 10, 25, 50, 100)
WINDOW = pd.DateOffset(years=1)


def load(db: Path) -> pd.DataFrame:
    """The latest snapshot of holders, with a class and a kind for each row.

    Foreign issuers file under no Peruvian RUC, so they cannot be told apart
    and are left out.
    """
    rows = store.read(
        db,
        "SELECT * FROM holders WHERE fetched_on = (SELECT max(fetched_on) FROM holders)",
    )
    rows = rows[rows["ruc"] != issuers.NO_RUC].reset_index(drop=True)
    return rows.assign(
        share_class=rows["series"].map(share_class),
        kind=rows["holder"].map(kind),
        foreign=~rows["nationality"].isin(LOCAL),
    )


def share_class(series: str) -> str | None:
    """`common`, a class letter, or None for a register entry naming several."""
    plain = issuers.ascii_upper(series).strip()
    if _COMMON_SERIES.match(plain):
        return COMMON
    if _LETTER_SERIES.match(plain):
        return plain
    return None


def kind(holder: str) -> str:
    """State, pension fund, person (`SURNAME, NAMES`) or company."""
    name = issuers.ascii_upper(holder)
    if _STATE.search(name):
        return "state"
    if _PENSION.search(name):
        return "pension fund"
    if "," in name and not _COMPANY.search(name):
        return "person"
    return "company"


def classes(holders: pd.DataFrame) -> pd.DataFrame:
    """One row per issuer and class: holders, the largest stake and its kind,
    block holdings capped at 100, free float, and the foreign stake."""
    rows = holders.dropna(subset=["share_class"])
    rows = rows.sort_values("percent", ascending=False)
    grouped = rows.groupby(["ruc", "share_class"], sort=True)
    largest = grouped.head(1).set_index(["ruc", "share_class"])
    blocks = grouped["percent"].sum()
    frame = pd.DataFrame(
        {
            "company": largest["company"],
            "holders": grouped.size(),
            "largest": largest["percent"],
            "largest_kind": largest["kind"],
            "largest_foreign": largest["foreign"],
            # Stakes rounded in the register can sum past 100.
            "blocks": blocks.clip(upper=100),
            "foreign": rows[rows["foreign"]]
            .groupby(["ruc", "share_class"])["percent"]
            .sum()
            .clip(upper=100),
        }
    )
    frame["foreign"] = frame["foreign"].fillna(0.0)
    frame["free_float"] = 100 - frame["blocks"]
    return frame.reset_index()


def class_tickers(
    frame: pd.DataFrame, links: pd.DataFrame, traded: pd.Series
) -> pd.Series:
    """The ticker of each class: among the issuer's `...C1` tickers, those ending
    in the class letter for a lettered class, the one with most days in `traded`.
    NaN for a class with no such ticker."""
    common = links[links["ticker"].str.endswith("C1")]
    common = common.assign(days=common["ticker"].map(traded).fillna(0))
    common = common.sort_values(["days", "ticker"], ascending=[False, True])
    picked = []
    for ruc, letter in zip(frame["ruc"], frame["share_class"], strict=True):
        tickers = common.loc[common["ruc"] == ruc, "ticker"]
        if letter != COMMON:
            tickers = tickers[tickers.str.endswith(f"{letter}C1")]
        picked.append(tickers.iloc[0] if len(tickers) else np.nan)
    return pd.Series(picked, index=frame.index, dtype=object)


def trading(quotes: pd.DataFrame, last_day: pd.Timestamp) -> pd.DataFrame:
    """Per ticker over the year to `last_day`: the share of market days it traded
    and its median monthly Amihud illiquidity, from months with enough days."""
    window = quotes[(quotes["date"] > last_day - WINDOW) & (quotes["date"] <= last_day)]
    days = len(panel.market_days(window))
    amihud = liquidity.monthly_amihud(window)
    return pd.DataFrame(
        {
            "days": window.groupby("ticker").size(),
            "coverage": window.groupby("ticker").size() / days,
            "amihud": amihud.groupby("ticker")["amihud"].median(),
        }
    )


def traded_classes(
    db: Path, frame: pd.DataFrame, snapshot: str
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """`frame`'s classes with a local ticker, each with its trading over the
    year to the last market day of the snapshot, and the issuer's total assets.
    Returns the rows and that day."""
    quotes = liquidity.local_quotes(db)
    last_day = quotes.loc[quotes["date"] <= pd.Timestamp(snapshot), "date"].max()
    names = quotes.sort_values("date", ascending=False).drop_duplicates(
        ["ticker", "name"]
    )[["ticker", "name"]]
    links = issuers.link(names, frame.drop_duplicates("ruc")[["ruc", "company"]])
    measured = trading(quotes, last_day)
    rows = frame.assign(ticker=class_tickers(frame, links, measured["days"]))
    rows = rows.dropna(subset=["ticker"]).join(measured, on="ticker")
    rows["days"] = rows["days"].fillna(0).astype(int)
    rows["coverage"] = rows["coverage"].fillna(0.0)
    rows["assets"] = rows["ruc"].map(assets(db))
    return rows.reset_index(drop=True), last_day


def assets(db: Path) -> pd.Series:
    """Total assets in thousands of soles from each RUC's latest individual
    statement.

    Dollar statements are converted at the BCRP sol per dollar on the
    quarter's last quoted day.
    """
    rows = store.read(
        db,
        "SELECT ruc, year, quarter, currency, assets FROM statements "
        "WHERE consolidated = 0 AND assets > 0",
    )
    rows = rows.sort_values(["year", "quarter"]).drop_duplicates("ruc", keep="last")
    sol = store.read(
        db, f"SELECT date, value FROM bcrp_series WHERE code = '{politics.SOL}'"
    )
    rates = sol.assign(date=pd.to_datetime(sol["date"])).set_index("date")["value"]
    first = pd.to_datetime(
        pd.DataFrame({"year": rows["year"], "month": rows["quarter"] * 3, "day": 1})
    )
    ends = first + pd.offsets.MonthEnd(0)
    rate = rates.sort_index().reindex(ends, method="ffill").to_numpy()
    usd = (rows["currency"] == "USD").to_numpy()
    soles = np.where(usd, rows["assets"].to_numpy() * rate, rows["assets"].to_numpy())
    return pd.Series(soles, index=rows["ruc"].to_numpy())


def rank_correlation(x: pd.Series, y: pd.Series, z: pd.Series | None = None) -> float:
    """Spearman correlation of `x` and `y`, or, given `z`, the correlation of
    their ranks once each is regressed on the ranks of `z`."""
    rx, ry = x.rank().to_numpy(), y.rank().to_numpy()
    if z is not None:
        rz = z.rank().to_numpy()
        rx = rx - np.polyval(np.polyfit(rz, rx, 1), rz)
        ry = ry - np.polyval(np.polyfit(rz, ry, 1), rz)
    return float(np.corrcoef(rx, ry)[0, 1])


def correlation(
    frame: pd.DataFrame,
    x: str,
    y: str,
    rng: np.random.Generator,
    *,
    control: str | None = None,
    draws: int = 2000,
) -> dict[str, int | float]:
    """`rank_correlation` over the rows of `frame`, with a 95% bootstrap interval
    that resamples rows."""

    def estimate(rows: pd.DataFrame) -> float:
        return rank_correlation(rows[x], rows[y], rows[control] if control else None)

    estimates = [
        estimate(frame.iloc[rng.integers(0, len(frame), len(frame))])
        for _ in range(draws)
    ]
    low, high = np.nanpercentile(estimates, [2.5, 97.5])
    return {
        "rows": len(frame),
        "rho": estimate(frame),
        "low": float(low),
        "high": float(high),
    }


def bands(frame: pd.DataFrame) -> pd.DataFrame:
    """Classes, median coverage and median Amihud, as |return| per million
    traded, by band of free float."""
    edges = list(FREE_FLOAT_BANDS)
    band = pd.cut(frame["free_float"], edges, include_lowest=True, right=False)
    band = band.cat.rename_categories(
        [f"{a}-{b}%" for a, b in itertools.pairwise(edges)]
    )
    grouped = frame.groupby(band, observed=False)
    return pd.DataFrame(
        {
            "classes": grouped.size(),
            "median_coverage": grouped["coverage"].median(),
            "median_amihud_per_million": grouped["amihud"].median() * 1e6,
        }
    )
