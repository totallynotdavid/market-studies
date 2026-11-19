"""When BVL issuers file their quarterly statements, and how prices take the news.

The limits come from article 7 of Resolución CONASEV 103-99-EF/94.10 as
amended by Resolución SMV 013-2014-SMV/01, in force from 1 July 2014: 30 days
after the quarter for individual statements and 45 for consolidated ones, 45
and 60 days for the fourth quarter. The SMV's own calendars read the first two
counts as months: a 30-day limit is the last day of the month after the
quarter and a 45-day one the 15th of the second month. The 60-day limit is 60
calendar days, 1 March or 29 February in a leap year. A limit on a closed day
moves to the next business day.

Earnings news is the change in quarterly net income from the same quarter a
year before, over the year-earlier total assets. It needs no forecast, which
the BVL lacks for most issuers, but it also counts a change the market
expected as news.
"""

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from bvl import disclosure, store


if TYPE_CHECKING:
    from pathlib import Path

RULE_FROM = pd.Timestamp("2014-07-01")
ISSUER = "EMPRESAS EMISORAS"

# Peru's national holidays as (month, day, first year). Holy Thursday and Good
# Friday are left out: they fall by 23 April at the latest, never near a limit.
HOLIDAYS = [
    (1, 1, 0), (5, 1, 0), (6, 7, 2022), (6, 29, 0), (7, 23, 2024), (7, 28, 0),
    (7, 29, 0), (8, 6, 2024), (8, 30, 0), (10, 8, 0), (11, 1, 0), (12, 8, 0),
    (12, 9, 2024), (12, 25, 0),
]  # fmt: skip

# Public-sector non-working days that moved a filing limit: DS 019-2011-PCM,
# DS 002-2019-PCM and DS 033-2022-PCM. DS 161-2021-PCM also closed 2 November
# 2021, but the SMV's 2021 calendar kept that day as a limit, so it stays open.
CLOSED = pd.to_datetime(["2011-05-02", "2011-10-31", "2019-10-31", "2022-10-31"])


def load(db: Path) -> pd.DataFrame:
    rows = store.read(db, "SELECT * FROM statements WHERE filed_on IS NOT NULL")
    rows["filed_on"] = pd.to_datetime(rows["filed_on"])
    first = pd.to_datetime(
        pd.DataFrame({"year": rows["year"], "month": rows["quarter"] * 3, "day": 1})
    )
    rows["quarter_end"] = first + pd.offsets.MonthEnd(0)
    rows["consolidated"] = rows["consolidated"].astype(bool)
    return rows


def limit(
    quarter_end: pd.Timestamp, *, fourth: bool, consolidated: bool
) -> pd.Timestamp:
    """The calendar limit for one statement, before a closed day moves it."""
    if consolidated and fourth:
        return quarter_end + pd.Timedelta(days=60)
    if consolidated or fourth:
        return (quarter_end + pd.offsets.MonthBegin(2)).replace(day=15)
    return quarter_end + pd.offsets.MonthEnd(1)


def business_days(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """Weekdays from `start` to `end` that are neither a holiday nor CLOSED."""
    days = pd.bdate_range(start, end)
    holiday = pd.Series(
        [(day.month, day.day) for day in days], index=days, dtype=object
    ).map(
        {(month, day): first for month, day, first in HOLIDAYS},
    )
    closed = (holiday <= days.year).to_numpy() | days.isin(CLOSED)
    return days[~closed]


def due(statements: pd.DataFrame) -> pd.Series:
    """Each statement's limit moved to the first business day on or after it."""
    limits = pd.DatetimeIndex(
        [
            limit(end, fourth=quarter == 4, consolidated=consolidated)
            for end, quarter, consolidated in zip(
                statements["quarter_end"],
                statements["quarter"],
                statements["consolidated"],
                strict=True,
            )
        ]
    )
    days = business_days(limits.min(), limits.max() + pd.Timedelta(days=14))
    return pd.Series(days[days.searchsorted(limits)], index=statements.index)


def timing(statements: pd.DataFrame) -> pd.DataFrame:
    """Add each statement's lag in days, its due day and whether it beat it."""
    due_on = due(statements)
    return statements.assign(
        lag=(statements["filed_on"] - statements["quarter_end"]).dt.days,
        due_on=due_on,
        on_due_day=statements["filed_on"] == due_on,
        late=statements["filed_on"] > due_on,
    )


def news(statements: pd.DataFrame) -> pd.Series:
    """Change in net income from the same quarter a year before, over its assets.

    A filer that changed its reporting currency in between gets no value, and
    neither does one with no positive year-earlier assets.
    """
    keys = ["rpj", "consolidated", "quarter"]
    earlier = statements[[*keys, "year", "currency", "net_income", "assets"]].copy()
    earlier["year"] += 1
    paired = statements[[*keys, "year", "currency", "net_income"]].merge(
        earlier, on=[*keys, "year"], how="left", suffixes=("", "_before")
    )
    usable = (paired["currency"] == paired["currency_before"]) & (paired["assets"] > 0)
    change = (paired["net_income"] - paired["net_income_before"]) / paired["assets"]
    return pd.Series(np.where(usable, change, np.nan), index=statements.index)


def car(
    grid: disclosure.Grid, columns: np.ndarray, day0: np.ndarray, span: tuple[int, int]
) -> np.ndarray:
    """Cumulative abnormal return over `span`, NaN for an event that cannot be
    measured. A day whose price is unknown adds nothing."""
    returns, _, _ = disclosure.profile(grid, columns, day0, span)
    measured = ~np.isnan(returns).all(axis=1)
    return np.where(measured, np.nansum(returns, axis=1), np.nan)
