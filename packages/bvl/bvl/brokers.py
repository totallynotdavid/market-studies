"""Market shares and concentration of the BVL's brokerage firms (SABs).

The SMV reports each firm's bought and sold amounts for a day. A firm's share
is its bought plus sold amount over the day's total of both sides, so a firm
on both sides of a trade counts twice. The API's own percentages are not used:
on some days they sum to less than 100.

Concentration is the Herfindahl-Hirschman index (HHI), the sum of squared
shares in percent, from 0 to 10,000. A year's HHI uses the firm's share of the
year's total amount; the daily HHI uses each day's shares.
"""

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from bvl import store


if TYPE_CHECKING:
    from pathlib import Path


def amounts(db: Path) -> pd.DataFrame:
    """One row per firm and day with a positive amount: date, broker, name, total."""
    rows = store.read(
        db,
        "SELECT date, broker, name, bought + sold AS total FROM broker_amounts "
        "WHERE bought + sold > 0 ORDER BY date, broker",
    )
    rows["date"] = pd.to_datetime(rows["date"])
    return rows


def coverage(db: Path) -> pd.Series:
    """Each year's bought amount over the quotes' traded amount.

    Before 2010 the brokers' amounts cover well under the quotes' total, so
    some firms of those years are missing from the API.
    """
    years = store.read(
        db,
        "SELECT b.year, b.bought / q.amount AS coverage FROM "
        "(SELECT substr(date, 1, 4) AS year, sum(bought) AS bought "
        "FROM broker_amounts GROUP BY 1) AS b JOIN "
        "(SELECT substr(date, 1, 4) AS year, sum(amount) AS amount "
        "FROM quotes GROUP BY 1) AS q USING (year)",
    )
    return years.set_index(years["year"].astype(int))["coverage"].rename_axis("year")


def latest_names(rows: pd.DataFrame) -> pd.Series:
    """Each broker code's name on the last day it traded.

    The API gives a code the same name on every day, today's.
    """
    return rows.groupby("broker")["name"].last()


def hhi(shares: pd.Series) -> float:
    """HHI of shares that sum to 1, on the 0 to 10,000 scale."""
    return float(((shares * 100) ** 2).sum())


def yearly_shares(rows: pd.DataFrame) -> pd.DataFrame:
    """Share of each firm (columns) in each year's total amount (rows)."""
    totals = rows.pivot_table(
        index=rows["date"].dt.year, columns="broker", values="total", aggfunc="sum"
    ).fillna(0.0)
    totals.index.name = "year"
    return totals.div(totals.sum(axis=1), axis=0)


def daily_hhi(rows: pd.DataFrame) -> pd.Series:
    """The HHI of each day's shares."""
    shares = rows["total"] / rows.groupby("date")["total"].transform("sum")
    return ((shares * 100) ** 2).groupby(rows["date"]).sum().rename("hhi")


def concentration_by_year(rows: pd.DataFrame) -> pd.DataFrame:
    """Per year: market days, active firms, HHI, median daily HHI, top-1 and top-3 shares."""
    shares = yearly_shares(rows)
    daily = daily_hhi(rows)
    ranked = -np.sort(-shares.to_numpy(), axis=1)
    return pd.DataFrame(
        {
            "days": rows.groupby(rows["date"].dt.year)["date"].nunique(),
            "firms": (shares > 0).sum(axis=1),
            "hhi": shares.apply(hhi, axis=1),
            "daily_hhi": daily.groupby(pd.DatetimeIndex(daily.index).year).median(),
            "top1": pd.Series(ranked[:, 0], index=shares.index),
            "top3": pd.Series(ranked[:, :3].sum(axis=1), index=shares.index),
        }
    ).rename_axis("year")
