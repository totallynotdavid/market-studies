"""The Peru General index and the sol around Peruvian political events.

The index is one chain of three codes that never overlap in the data: the
IGBVL to 2015-04-30, the S&P/BVL Peru General to 2025-08-29 and the MSCI NUAM
Peru General after it. A day's return is the log of its close over the code's
own previous close, so the switch days chain without a jump. A return beyond
`panel.MAX_ABS_LOG_RETURN` is a bad print (the IGBVL closes at 3174.71 on
1997-01-28 between two days near 1525) and is dropped.

An event's abnormal return is the index return less a market model on copper,
fitted by least squares over days -260 to -11. Copper is the largest export and
moves the index on most days; a political shock is what is left.
"""

from typing import TYPE_CHECKING, NamedTuple

import numpy as np
import pandas as pd

from bvl import panel, store


if TYPE_CHECKING:
    from pathlib import Path

CHAIN = ("IGBVL", "SPBLPGPT", "MXNUAMPEGEN")
COPPER = "PD04701XD"
SOL = "PD04638PD"
ESTIMATION = (-260, -11)
# Days 0 to REACTION_DAYS - 1 form the cumulative window.
REACTION_DAYS = 6


class Event(NamedTuple):
    day0: str
    label: str


# Day 0 is the first session that could react to the news, from the timings in
# the comment beside each event. BVL trades from about 8:30 to 15:00 Lima time.
EVENTS = (
    Event("2011-04-11", "2011 first round"),  # Sunday vote, 10 Apr
    Event("2011-06-06", "2011 runoff"),  # Sunday vote, 5 Jun; trading halted twice
    Event("2016-04-11", "2016 first round"),  # Sunday vote, 10 Apr
    Event("2016-06-06", "2016 runoff"),  # Sunday vote, 5 Jun
    Event("2017-12-22", "2017 PPK survives vacancy vote"),  # vote after 23:00, 21 Dec
    # The vote-buying videos came out on 20 Mar; the resignation aired at 14:40.
    Event("2018-03-21", "2018 PPK resigns"),
    Event("2019-10-01", "2019 Vizcarra dissolves Congress"),  # about 17:45, 30 Sep
    Event("2020-11-10", "2020 Congress removes Vizcarra"),  # evening vote, 9 Nov
    Event("2020-11-16", "2020 Merino resigns"),  # Sunday, 15 Nov
    Event("2021-04-12", "2021 first round"),  # Sunday vote, 11 Apr
    Event("2021-06-07", "2021 runoff"),  # Sunday vote, 6 Jun
    Event("2022-12-07", "2022 Castillo's self-coup, removal"),  # during the session
    Event("2025-10-10", "2025 Congress removes Boluarte"),  # vote ended 00:08, 10 Oct
    Event("2026-04-13", "2026 first round"),  # Sunday vote, 12 Apr
    Event("2026-06-08", "2026 runoff"),  # Sunday vote, 7 Jun
)


class Fit(NamedTuple):
    alpha: float
    beta: float
    sd: float
    days: int


def peru_general(db: Path) -> pd.DataFrame:
    """Daily log return of the chained Peru General index and its level from 1."""
    codes = ", ".join(f"'{code}'" for code in CHAIN)
    levels = store.read(
        db,
        "SELECT date, code, prev_close, close FROM index_levels "
        f"WHERE code IN ({codes}) AND close > 0 AND prev_close > 0 ORDER BY date",
    )
    if levels["date"].duplicated().any():
        raise ValueError("two Peru General codes quote the same day")
    levels.index = pd.DatetimeIndex(levels.pop("date"), name="date")
    returns: pd.Series = (levels["close"] / levels["prev_close"]).pipe(np.log)
    returns = returns[returns.abs() <= panel.MAX_ABS_LOG_RETURN]
    return pd.DataFrame(
        {"code": levels["code"].loc[returns.index], "r": returns}
    ).assign(level=np.exp(returns.cumsum()))


def bcrp_returns(db: Path, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Daily log changes of copper and the sol per dollar on each of `days`.

    The BCRP and the BVL keep different holidays, so each series carries its
    last value forward onto the BVL calendar before it is differenced.
    """
    rows = store.read(
        db,
        f"SELECT date, code, value FROM bcrp_series WHERE code IN ('{COPPER}', '{SOL}')",
    )
    rows["date"] = pd.to_datetime(rows["date"])
    wide = rows.pivot(index="date", columns="code", values="value")
    aligned = wide.reindex(wide.index.union(days)).ffill().reindex(days)
    logs = pd.DataFrame(np.log(aligned.to_numpy()), index=days, columns=aligned.columns)
    changes = logs.diff()
    return pd.DataFrame({"copper": changes[COPPER], "sol": changes[SOL]})


def market_model(y: np.ndarray, x: np.ndarray) -> Fit:
    """Least squares of `y` on `x`, skipping days where either is missing."""
    kept = np.isfinite(y) & np.isfinite(x)
    y, x = y[kept], x[kept]
    beta, alpha = np.polyfit(x, y, 1)
    residuals = y - alpha - beta * x
    return Fit(float(alpha), float(beta), float(residuals.std(ddof=2)), int(kept.sum()))


def event_table(
    daily: pd.DataFrame, events: tuple[Event, ...] = EVENTS
) -> pd.DataFrame:
    """One row per event: raw and abnormal index returns, sol changes and rarity.

    `daily` holds the index return `r` and the `copper` and `sol` changes on
    every market day. A z score divides by the estimation window's sd, scaled
    by the square root of the window length for a cumulative change.
    """
    r = daily["r"].to_numpy()
    copper = daily["copper"].to_numpy()
    sol = daily["sol"].to_numpy()
    magnitude = np.abs(r[np.isfinite(r)])
    rows = []
    for event in events:
        i = daily.index.get_loc(pd.Timestamp(event.day0))
        if not isinstance(i, int):
            raise TypeError(f"{event.day0} is not one market day")
        first, last = i + ESTIMATION[0], i + ESTIMATION[1] + 1
        fit = market_model(r[first:last], copper[first:last])
        window = slice(i, i + REACTION_DAYS)
        abnormal = r[window] - fit.alpha - fit.beta * np.nan_to_num(copper[window])
        sol_sd = float(np.nanstd(sol[first:last], ddof=1))
        root = np.sqrt(REACTION_DAYS)
        rows.append(
            {
                "day0": event.day0,
                "event": event.label,
                "return": r[i],
                "abnormal": abnormal[0],
                "z": abnormal[0] / fit.sd,
                "car": abnormal.sum(),
                "car_z": abnormal.sum() / (fit.sd * root),
                "sol": sol[i],
                "sol_z": sol[i] / sol_sd,
                "sol_cum": np.nansum(sol[window]),
                "sol_cum_z": np.nansum(sol[window]) / (sol_sd * root),
                "share_as_large": float((magnitude >= abs(r[i])).mean()),
                "beta": fit.beta,
                "sd": fit.sd,
                "fit_days": fit.days,
            }
        )
    return pd.DataFrame(rows)
