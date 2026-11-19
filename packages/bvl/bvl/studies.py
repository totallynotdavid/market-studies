"""Runs each study on the panel and writes its figures and `numbers.json`.

A study's README cites the numbers file, so a rerun on a newer panel updates
the evidence and leaves the prose to be checked against it.
"""

import json

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from bvl import (
    brokers,
    disclosure,
    earnings,
    events,
    figures,
    issuers,
    liquidity,
    panel,
    politics,
)


if TYPE_CHECKING:
    from pathlib import Path

SOURCE = "Source: SMV open data API (mvnet.smv.gob.pe), BVL daily quotes."
# MSCI's review of Peru's Emerging Markets status, from its press releases.
MSCI_MARKS = {
    "2015-08-03": "MSCI consults on Frontier",
    "2015-09-30": "Peru kept, on review",
    "2016-06-14": "Peru stays Emerging",
}
# A year enters the brokers figures once the firms' bought amount, and every
# later year's, reaches this share of the quotes' traded amount.
BROKER_COVERAGE = 0.9


def run_liquidity(db: Path, out: Path) -> dict[str, object]:
    quotes = liquidity.local_quotes(db)
    coverage = liquidity.coverage_by_year(quotes)
    amihud = liquidity.monthly_amihud(quotes)
    yearly = liquidity.illiquidity_by_year(amihud)
    monthly = liquidity.time_effects(
        np.log(amihud["amihud"]), amihud["ticker"], amihud["month"]
    )
    monthly.index = pd.PeriodIndex(monthly.index).to_timestamp()
    complete = coverage.loc[coverage.index < pd.Timestamp.today().year]

    figures.lines(
        {"local stocks that traded": complete["stocks"]},
        out / "active-stocks.png",
        title="Local stocks with at least one trade, per year",
        ylabel="stocks",
        note=SOURCE,
    )
    figures.lines(
        {
            "traded on 80% or more of days": complete["daily_share"] * 100,
            "traded on under 20% of days": complete["rare_share"] * 100,
        },
        out / "coverage.png",
        title="How often a listed local stock trades",
        ylabel="% of active stocks",
        note=SOURCE + " Coverage counts days between a stock's first and last trade.",
    )
    figures.lines(
        {
            "monthly": monthly,
            "12-month mean": monthly.rolling(12, min_periods=6).mean(),
        },
        out / "illiquidity.png",
        title="Price impact of trading (Amihud), net of each stock's own level",
        ylabel="log illiquidity vs mean month",
        note=SOURCE + " Higher: the same amount traded moves the price more.",
        span=("2015-08-03", "2016-06-14", "MSCI review "),
    )

    window = monthly.loc["2014-01":"2017-12"]
    figures.lines(
        {"monthly": window},
        out / "illiquidity-msci.png",
        title="Illiquidity around MSCI's 2015-16 review of Peru",
        ylabel="log illiquidity vs mean month",
        note=SOURCE,
        marks=MSCI_MARKS,
    )

    numbers: dict[str, object] = {
        "first_day": quotes["date"].min().date().isoformat(),
        "last_day": quotes["date"].max().date().isoformat(),
        "local_tickers": int(quotes["ticker"].nunique()),
        "stock_months": len(amihud),
        "coverage_by_year": _records(complete.round(3)),
        "illiquidity_by_year": _records(yearly.round(3).rename("effect")),
        "msci": _msci_shift(monthly),
    }
    _write_numbers(out, numbers)
    return numbers


# Quotes this long before the first event give it a full baseline.
DISCLOSURE_QUOTES_FROM = "2008-01-01"
SEED = 20261114
# (measure, statistic, label) compared between events and placebo days.
EVENT_MEASURES = (
    ("abs_car_pre5", "mean", "|abnormal return|, days -5 to -1"),
    ("abs_car_pre1", "mean", "|abnormal return|, day -1"),
    ("abs_car_event", "mean", "|abnormal return|, days 0 to 1"),
    ("signed_pre5", "mean", "days -5 to -1 return in the direction of days 0 to 1"),
    ("signed_pre1", "mean", "day -1 return in the direction of days 0 to 1"),
    ("log_volume_pre5", "mean", "log(1 + amount / baseline), days -5 to -1"),
    ("log_volume_event", "mean", "log(1 + amount / baseline), days 0 to 1"),
    ("traded_pre5", "mean", "share of days -5 to -1 with a trade"),
    ("traded_event", "mean", "share of days 0 to 1 with a trade"),
)
# Measures repeated per topic, period and decision-to-filing gap.
FOCUS = ("abs_car_event", "signed_pre5", "log_volume_pre5")
PERIODS = {"2010-14": (2010, 2014), "2015-19": (2015, 2019), "2020-26": (2020, 2026)}
GAPS = {
    "same day": (0, 0),
    "next day": (1, 1),
    "2 to 7 days": (2, 7),
    "8+ days": (8, 10_000),
}
PROFILE_SPAN = (-10, 10)
# A group with fewer events gets a count and no estimates.
MIN_EVENTS = 30


def run_disclosure(db: Path, out: Path) -> dict[str, object]:
    rng = np.random.default_rng(SEED)
    quotes = liquidity.local_quotes(db)
    quotes = quotes[quotes["date"] >= DISCLOSURE_QUOTES_FROM]
    grid = disclosure.build_grid(quotes, panel.market_log_level(quotes))
    filings = events.load(db)
    sample, filing_days = _event_sample(grid, quotes, filings)
    placebos = disclosure.placebo_days(grid, sample, filing_days, rng)

    actual = _with_signed(
        disclosure.measure(grid, sample["column"].to_numpy(), sample["day0"].to_numpy())
    ).set_index(sample.index)
    placebo = _with_signed(
        disclosure.measure(
            grid, placebos["column"].to_numpy(), placebos["day0"].to_numpy()
        )
    ).set_index(pd.Index(placebos["event"]))
    clusters = sample["day0"]

    def compare(rows: pd.Index, measures: tuple[str, ...]) -> dict[str, Any]:
        kept = placebo[placebo.index.isin(rows)]
        result: dict[str, Any] = {"events": len(rows)}
        if len(rows) < MIN_EVENTS:
            return result
        for name, statistic, _ in EVENT_MEASURES:
            if name not in measures:
                continue
            point, low, high = disclosure.excess(
                actual.loc[rows, name], kept[name], clusters.loc[rows], statistic, rng
            )
            result[name] = {
                "events": round(_stat(actual.loc[rows, name], statistic), 5),
                "placebo": round(_stat(kept[name], statistic), 5),
                "excess": round(point, 5),
                "low": round(low, 5),
                "high": round(high, 5),
            }
        return result

    every = tuple(name for name, _, _ in EVENT_MEASURES)
    overall = compare(sample.index, every)
    by_topic = {
        name: compare(
            sample.index[sample["topics"].map(lambda t, n=name: n in t)], FOCUS
        )
        for name in events.TOPICS
    }
    year = sample["filed_at"].dt.year
    by_period = {
        name: compare(sample.index[year.between(a, b)], FOCUS)
        for name, (a, b) in PERIODS.items()
    }
    gap = (sample["filed_at"].dt.normalize() - sample["agreed_on"]).dt.days
    by_gap = {
        name: compare(sample.index[gap.between(a, b)], FOCUS)
        for name, (a, b) in GAPS.items()
    }
    gap_shares = _gap_shares(gap, year)

    _disclosure_figures(grid, sample, placebos, by_topic, gap_shares, out)
    numbers: dict[str, object] = {
        "filings": len(filings),
        "filings_in_events": int(sample["filings"].sum()),
        "events": len(sample),
        "issuers": int(sample["ruc"].nunique()),
        "tickers": int(sample["ticker"].nunique()),
        "first_event": sample["filed_at"].min().date().isoformat(),
        "last_event": sample["filed_at"].max().date().isoformat(),
        "placebo_days": len(placebos),
        "measures": {name: label for name, _, label in EVENT_MEASURES},
        "overall": overall,
        "by_topic": by_topic,
        "by_period": by_period,
        "by_gap": by_gap,
        "gap_shares_by_year": _records(gap_shares.round(3)),
    }
    _write_numbers(out, numbers)
    return numbers


def _event_sample(
    grid: disclosure.Grid, quotes: pd.DataFrame, filings: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """Clean events, one per stock and day 0, and every issuer filing day per ticker.

    Filings that share an issuer's day 0 merge into one event with every
    topic among them. A filing after the last market day is dropped.
    """
    names = quotes.sort_values("date", ascending=False).drop_duplicates(
        ["ticker", "name"]
    )[["ticker", "name"]]
    links = issuers.link(names, filings.drop_duplicates("ruc")[["ruc", "company"]])
    linked = filings.merge(links[["ticker", "ruc"]], on="ruc")
    linked["day0"] = disclosure.day_zero(linked["filed_at"], grid.days)
    linked = linked[linked["day0"] < len(grid.days)]
    picked = disclosure.most_traded(
        grid, linked.rename(columns={"filing": "event"})[["event", "ticker", "day0"]]
    ).rename(columns={"event": "filing"})
    chosen = filings.merge(picked, on="filing")
    filing_days = {
        str(ticker): np.unique(days.to_numpy())
        for ticker, days in linked.groupby("ticker")["day0"]
    }
    merged = chosen.groupby(["ticker", "day0"], as_index=False).agg(
        ruc=("ruc", "first"),
        column=("column", "first"),
        filed_at=("filed_at", "min"),
        agreed_on=("agreed_on", "min"),
        filings=("filing", "size"),
        topics=("topics", lambda t: frozenset().union(*t)),
    )
    return merged[disclosure.clean(merged)].reset_index(drop=True), filing_days


def _with_signed(measures: pd.DataFrame) -> pd.DataFrame:
    """Add |CAR|, pre-event returns signed by the day 0 to 1 reaction, and log volume.

    The amount ratio is zero on most days of a thin stock and very large on a
    few, so its log(1 + ratio) is averaged instead.

    A leak moves the price before the filing in the direction the filing then
    moves it, so the signed return is positive on average; on a placebo day it
    is the plain autocorrelation of returns.
    """
    direction = np.sign(measures["car_event"])
    return measures.assign(
        abs_car_pre5=measures["car_pre5"].abs(),
        abs_car_pre1=measures["car_pre1"].abs(),
        abs_car_event=measures["car_event"].abs(),
        signed_pre5=measures["car_pre5"] * direction,
        signed_pre1=measures["car_pre1"] * direction,
        log_volume_pre5=np.log1p(measures["volume_pre5"]),
        log_volume_event=np.log1p(measures["volume_event"]),
    )


def _stat(values: pd.Series, statistic: str) -> float:
    return float(values.median() if statistic == "median" else values.mean())


def _gap_shares(gap: pd.Series, year: pd.Series) -> pd.DataFrame:
    """Per year, the share of events in each decision-to-filing gap."""
    known = gap.notna() & (gap >= 0)
    label = pd.Series(pd.NA, index=gap.index, dtype="object")
    for name, (a, b) in GAPS.items():
        label[gap.between(a, b)] = name
    table = pd.crosstab(year[known].rename("year"), label[known], normalize="index")
    return table.reindex(columns=list(GAPS), fill_value=0.0)


def _disclosure_figures(
    grid: disclosure.Grid,
    sample: pd.DataFrame,
    placebos: pd.DataFrame,
    by_topic: dict[str, dict[str, Any]],
    gap_shares: pd.DataFrame,
    out: Path,
) -> None:
    note = SOURCE + " Events: SMV material-event filings, 2010 on."
    event_returns, event_amount, event_traded = disclosure.profile(
        grid, sample["column"].to_numpy(), sample["day0"].to_numpy(), PROFILE_SPAN
    )
    placebo_returns, placebo_amount, placebo_traded = disclosure.profile(
        grid, placebos["column"].to_numpy(), placebos["day0"].to_numpy(), PROFILE_SPAN
    )
    offsets = pd.Index(range(PROFILE_SPAN[0], PROFILE_SPAN[1] + 1), name="day")
    figures.lines(
        {
            "filing": pd.Series(
                np.nanmean(np.abs(event_returns), axis=0) * 100, offsets
            ),
            "placebo day": pd.Series(
                np.nanmean(np.abs(placebo_returns), axis=0) * 100, offsets
            ),
        },
        out / "abs-return-profile.png",
        title="Size of the daily abnormal move around a material-event filing",
        ylabel="mean |abnormal return|, %",
        note=note + " Day 0: first market day on or after the filing date.",
    )
    figures.lines(
        {
            "filing": pd.Series(np.nanmean(event_traded, axis=0) * 100, offsets),
            "placebo day": pd.Series(np.nanmean(placebo_traded, axis=0) * 100, offsets),
        },
        out / "traded-profile.png",
        title="Share of stocks that trade on each day around a filing",
        ylabel="% of events with a trade",
        note=note,
    )
    figures.lines(
        {
            "filing": pd.Series(np.nanmean(np.log1p(event_amount), axis=0), offsets),
            "placebo day": pd.Series(
                np.nanmean(np.log1p(placebo_amount), axis=0), offsets
            ),
        },
        out / "amount-profile.png",
        title="Traded amount around a filing, against the stock's own baseline",
        ylabel="mean log(1 + amount / baseline)",
        note=note + " Baseline: mean daily amount over days -250 to -30.",
    )
    signed = {
        topic: result["signed_pre5"]
        for topic, result in by_topic.items()
        if isinstance(result.get("signed_pre5"), dict)
    }
    excess = pd.Series({t: v["excess"] * 100 for t, v in signed.items()})
    figures.bars(
        excess,
        out / "pre-run-up-by-topic.png",
        title="Pre-filing move in the direction of the reaction, over placebo",
        ylabel="excess signed return, days -5 to -1, %",
        note=note + " Bars: 95% bootstrap interval clustered by day 0.",
        errors=(
            pd.Series({t: v["low"] * 100 for t, v in signed.items()}),
            pd.Series({t: v["high"] * 100 for t, v in signed.items()}),
        ),
    )
    figures.lines(
        {name: gap_shares[name] * 100 for name in ("same day", "next day")},
        out / "filing-gap.png",
        title="When the decision behind a filing was taken",
        ylabel="% of events",
        note=note + " Gap: agreement date to filing date.",
    )


BCRP_SOURCE = "Sources: SMV API (BVL index levels), BCRP API (sol per dollar, copper)."
POLITICS_LEVEL_FROM = "2010-01-01"


def run_politics(db: Path, out: Path) -> dict[str, object]:
    index = politics.peru_general(db)
    daily = index.join(politics.bcrp_returns(db, pd.DatetimeIndex(index.index)))
    table = politics.event_table(daily)
    labels = pd.Index([e.label for e in politics.EVENTS], name="event")
    note = BCRP_SOURCE + " Day 0: first session after the news."

    level = daily.loc[POLITICS_LEVEL_FROM:, "level"]
    figures.lines(
        {"Peru General": level / level.iloc[0] * 100},
        out / "index-events.png",
        title="Peru General index and the political events studied",
        ylabel=f"index, {level.index[0].date()} = 100",
        note=BCRP_SOURCE + " Marks: event numbers in the README.",
        marks={e.day0: str(n) for n, e in enumerate(politics.EVENTS, 1)},
    )
    abnormal = pd.Series(table["abnormal"].to_numpy() * 100, labels)
    band = pd.Series(1.96 * table["sd"].to_numpy() * 100, labels)
    figures.bars(
        abnormal,
        out / "day0-abnormal.png",
        title="Day-0 index return net of copper",
        ylabel="abnormal log return, %",
        note=note + " Whiskers: ±1.96 residual sd.",
        errors=(abnormal - band, abnormal + band),
        rotate=True,
    )
    car = pd.Series(table["car"].to_numpy() * 100, labels)
    car_band = band * np.sqrt(politics.REACTION_DAYS)
    figures.bars(
        car,
        out / "car.png",
        title="Index return net of copper over days 0 to +5",
        ylabel="cumulative abnormal log return, %",
        note=note + " Whiskers: ±1.96 sd of a 6-day sum.",
        errors=(car - car_band, car + car_band),
        rotate=True,
    )
    figures.bars(
        pd.Series(table["sol"].to_numpy() * 100, labels),
        out / "sol-day0.png",
        title="Change in soles per dollar on day 0",
        ylabel="log change, % (up: weaker sol)",
        note=note,
        rotate=True,
    )

    returns = daily["r"]
    numbers: dict[str, object] = {
        "first_day": returns.index.min().date().isoformat(),
        "last_day": returns.index.max().date().isoformat(),
        "market_days": len(returns),
        "daily_sd": round(float(returns.std()), 5),
        "estimation_window": list(politics.ESTIMATION),
        "reaction_days": politics.REACTION_DAYS,
        "events": json.loads(table.round(5).to_json(orient="records")),
    }
    _write_numbers(out, numbers)
    return numbers


def run_brokers(db: Path, out: Path) -> dict[str, object]:
    rows = brokers.amounts(db)
    names = brokers.latest_names(rows)
    by_year = brokers.concentration_by_year(rows).join(brokers.coverage(db))
    by_year["leader"] = brokers.yearly_shares(rows).idxmax(axis=1)
    short = by_year["coverage"] < BROKER_COVERAGE
    first = (
        int(by_year.index[short].max()) + 1 if short.any() else int(by_year.index[0])
    )
    shown = by_year.loc[first:]
    shares = brokers.yearly_shares(rows).loc[first:]
    note = SOURCE.replace("BVL daily quotes", "amounts traded by each SAB")
    last_year = int(shares.index.max())

    figures.lines(
        {"yearly shares": shown["hhi"], "median day": shown["daily_hhi"]},
        out / "hhi.png",
        title="Concentration of BVL brokerage, Herfindahl-Hirschman index",
        ylabel="HHI, 0 to 10,000",
        note=note + f" {last_year} is partial.",
    )
    figures.lines(
        {"largest firm": shown["top1"] * 100, "three largest": shown["top3"] * 100},
        out / "top-shares.png",
        title="Share of the amount traded through the largest firms",
        ylabel="% of bought plus sold",
        note=note + " Each year's ranking.",
    )
    figures.lines(
        {"firms": shown["firms"]},
        out / "firms.png",
        title="Brokerage firms with any amount traded in the year",
        ylabel="firms",
        note=note,
    )
    leaders = shares.iloc[-1].nlargest(3)
    figures.lines(
        {f"{names[code]} ({code})": shares[code] * 100 for code in leaders.index},
        out / "leaders.png",
        title=f"Yearly share of the three largest firms in {last_year}",
        ylabel="% of bought plus sold",
        note=note,
    )

    numbers: dict[str, object] = {
        "first_day": rows["date"].min().date().isoformat(),
        "last_day": rows["date"].max().date().isoformat(),
        "market_days": int(rows["date"].nunique()),
        "firms_ever": int(rows["broker"].nunique()),
        "coverage_threshold": BROKER_COVERAGE,
        "first_covered_year": first,
        "by_year": _records(by_year.round(4)),
        "shares": {
            str(year): [
                {"broker": code, "name": names[str(code)], "share": round(float(s), 4)}
                for code, s in year_shares[year_shares > 0]
                .sort_values()
                .iloc[::-1]
                .items()
            ]
            for year, year_shares in shares.iterrows()
        },
    }
    _write_numbers(out, numbers)
    return numbers


STATEMENTS_SOURCE = "Source: SMV open data API, quarterly statements."
EVENTS_SOURCE = "Source: SMV open data API, quarterly statements and BVL quotes."
# How far before and after the filing the reaction profile runs, in market days.
EARNINGS_SPAN = (-5, 60)
EARNINGS_WINDOWS = {"pre": (-5, -1), "reaction": (0, 1), "drift": (2, 60)}
EARNINGS_PERIODS = {
    "2002-09": (2002, 2009),
    "2010-14": (2010, 2014),
    "2015-19": (2015, 2019),
    "2020-26": (2020, 2026),
}
# Days from the due day shown in the filing-day histogram.
DUE_OFFSETS = range(-20, 11)


def run_earnings(db: Path, out: Path) -> dict[str, object]:
    rng = np.random.default_rng(SEED)
    quotes = liquidity.local_quotes(db)
    days = panel.market_days(quotes)
    statements = earnings.load(db)
    links = _statement_links(quotes, statements)
    statements["traded_share"] = statements["ruc"].isin(links["ruc"])
    # A quarter counts once every limit has passed in the panel.
    complete = statements["quarter_end"] + pd.offsets.MonthEnd(3) < days[-1]
    timed = earnings.timing(statements[complete])
    individual = timed[
        ~timed["consolidated"] & (timed["company_type"] == earnings.ISSUER)
    ]

    by_quarter = _timing_by_quarter(individual)
    ruled = individual[individual["filed_on"] >= earnings.RULE_FROM]
    offsets = (ruled["filed_on"] - ruled["due_on"]).dt.days
    shares = offsets.value_counts(normalize=True).reindex(DUE_OFFSETS, fill_value=0.0)
    by_traded = {
        "traded share": _timing_summary(ruled[ruled["traded_share"]]),
        "no traded share": _timing_summary(ruled[~ruled["traded_share"]]),
    }

    grid = disclosure.build_grid(quotes, panel.market_log_level(quotes))
    sample = _earnings_sample(grid, statements, links)
    reaction = _earnings_reaction(grid, sample, rng)
    _earnings_figures(grid, by_quarter, shares, sample, out)

    numbers: dict[str, object] = {
        "statements": len(statements),
        "filers": int(statements["rpj"].nunique()),
        "first_quarter": str(statements["quarter_end"].min().to_period("Q")),
        "last_quarter": str(timed["quarter_end"].max().to_period("Q")),
        "issuer_statements": len(individual),
        "issuers": int(individual["rpj"].nunique()),
        "rule_from": earnings.RULE_FROM.date().isoformat(),
        "since_rule": _timing_summary(ruled),
        "since_rule_by_traded": by_traded,
        "by_quarter": _records(
            by_quarter.round(3)
            .set_axis(pd.DatetimeIndex(by_quarter.index).to_period("Q").astype(str))
            .rename_axis("quarter")
        ),
        "filed_vs_due_day": {str(k): round(float(v), 4) for k, v in shares.items()},
        "events": len(sample),
        "event_issuers": int(sample["ruc"].nunique()),
        "event_tickers": int(sample["ticker"].nunique()),
        "first_event": sample["filed_on"].min().date().isoformat(),
        "last_event": sample["filed_on"].max().date().isoformat(),
        "windows": {k: list(v) for k, v in EARNINGS_WINDOWS.items()},
        "reaction": reaction,
    }
    _write_numbers(out, numbers)
    return numbers


def _statement_links(quotes: pd.DataFrame, statements: pd.DataFrame) -> pd.DataFrame:
    names = quotes.sort_values("date", ascending=False).drop_duplicates(
        ["ticker", "name"]
    )[["ticker", "name"]]
    filers = statements.sort_values("filed_on", ascending=False).drop_duplicates("ruc")
    return issuers.link(names, filers[["ruc", "company"]])


def _timing_summary(rows: pd.DataFrame) -> dict[str, object]:
    return {
        "statements": len(rows),
        "median_lag": float(rows["lag"].median()),
        "on_due_day": round(float(rows["on_due_day"].mean()), 4),
        "late": round(float(rows["late"].mean()), 4),
        "late_over_30_days": round(
            float((rows["filed_on"] - rows["due_on"]).dt.days.gt(30).mean()), 4
        ),
    }


def _timing_by_quarter(rows: pd.DataFrame) -> pd.DataFrame:
    """Per fiscal quarter: statements, median lag and the share on and after the due day."""
    grouped = rows.groupby("quarter_end")
    return pd.DataFrame(
        {
            "statements": grouped.size(),
            "median_lag": grouped["lag"].median(),
            "on_due_day": grouped["on_due_day"].mean(),
            "late": grouped["late"].mean(),
        }
    )


def _earnings_sample(
    grid: disclosure.Grid, statements: pd.DataFrame, links: pd.DataFrame
) -> pd.DataFrame:
    """Individual statements of share issuers with earnings news, on their busiest
    ticker, each with its day 0 and cumulative abnormal return in every window."""
    individual = statements[~statements["consolidated"]].reset_index(drop=True)
    individual["news"] = earnings.news(individual)
    rows = individual.dropna(subset=["news"]).merge(links[["ticker", "ruc"]], on="ruc")
    rows["day0"] = disclosure.day_zero(rows["filed_on"], grid.days)
    rows = rows[rows["day0"] < len(grid.days)]
    rows["event"] = rows["rpj"] + " " + rows["quarter_end"].dt.date.astype(str)
    picked = disclosure.most_traded(grid, rows[["event", "ticker", "day0"]])
    sample = (
        rows.drop(columns=["ticker"])
        .drop_duplicates("event")
        .merge(picked[["event", "ticker", "column"]], on="event")
    )
    for name, span in EARNINGS_WINDOWS.items():
        sample[f"car_{name}"] = earnings.car(
            grid, sample["column"].to_numpy(), sample["day0"].to_numpy(), span
        )
    sample = sample.dropna(subset=["car_reaction"]).reset_index(drop=True)
    sample["tercile"] = pd.qcut(sample["news"], 3, labels=["bad", "middle", "good"])
    return sample


def _earnings_reaction(
    grid: disclosure.Grid, sample: pd.DataFrame, rng: np.random.Generator
) -> dict[str, object]:
    """Mean CAR of good-news less bad-news events in each window, by tercile and
    by sign, with a bootstrap that resamples day 0."""

    def gap(rows: pd.DataFrame, good: pd.Series, bad: pd.Series) -> dict[str, Any]:
        result: dict[str, Any] = {"good": int(good.sum()), "bad": int(bad.sum())}
        if min(good.sum(), bad.sum()) < MIN_EVENTS:
            return result
        for name in EARNINGS_WINDOWS:
            column = rows[f"car_{name}"]
            point, low, high = disclosure.excess(
                column[good], column[bad], rows["day0"], "mean", rng
            )
            result[name] = {
                "good": round(float(column[good].mean()), 5),
                "bad": round(float(column[bad].mean()), 5),
                "difference": round(point, 5),
                "low": round(low, 5),
                "high": round(high, 5),
            }
        return result

    def split(rows: pd.DataFrame) -> dict[str, Any]:
        return {
            "terciles": gap(rows, rows["tercile"] == "good", rows["tercile"] == "bad"),
            "sign": gap(rows, rows["news"] > 0, rows["news"] < 0),
        }

    year = sample["filed_on"].dt.year
    return {
        "overall": split(sample),
        "by_period": {
            name: split(sample[year.between(a, b)])
            for name, (a, b) in EARNINGS_PERIODS.items()
        },
    }


def _earnings_figures(
    grid: disclosure.Grid,
    by_quarter: pd.DataFrame,
    shares: pd.Series,
    sample: pd.DataFrame,
    out: Path,
) -> None:
    note = STATEMENTS_SOURCE + " Individual statements of issuers."
    rule = {earnings.RULE_FROM.date().isoformat(): "SMV 013-2014 in force"}
    figures.lines(
        {"median days after quarter end": by_quarter["median_lag"]},
        out / "lag.png",
        title="How long issuers take to file a quarterly statement",
        ylabel="days",
        note=note + " One point per fiscal quarter, by quarter end.",
        marks=rule,
    )
    figures.lines(
        {
            "filed on the due day": by_quarter["on_due_day"] * 100,
            "filed after it": by_quarter["late"] * 100,
        },
        out / "due-day.png",
        title="Share of statements filed on the due day and after it",
        ylabel="% of statements",
        note=note + " Due day: the SMV limit moved past closed days.",
        marks=rule,
    )
    figures.bars(
        shares * 100,
        out / "filing-day.png",
        title="Filing day against the due day, since July 2014",
        ylabel="% of statements",
        note=note + " 0 is the due day.",
    )
    returns, _, _ = disclosure.profile(
        grid, sample["column"].to_numpy(), sample["day0"].to_numpy(), EARNINGS_SPAN
    )
    offsets = pd.Index(range(EARNINGS_SPAN[0], EARNINGS_SPAN[1] + 1), name="day")
    figures.lines(
        {
            f"{name} news": pd.Series(
                np.nancumsum(
                    np.nanmean(returns[(sample["tercile"] == name).to_numpy()], axis=0)
                )
                * 100,
                offsets,
            )
            for name in ("good", "middle", "bad")
        },
        out / "drift.png",
        title="Mean cumulative abnormal return around a quarterly filing",
        ylabel="cumulative %, from the close of day -6",
        note=EVENTS_SOURCE + " Terciles of the change in net income from a year"
        " before, over assets.",
    )


def _msci_shift(monthly: pd.Series) -> dict[str, float]:
    """Mean monthly illiquidity in the year before the consultation and after."""
    before = monthly.loc["2014-08":"2015-07"].mean()
    during = monthly.loc["2015-08":"2016-06"].mean()
    after = monthly.loc["2016-07":"2017-06"].mean()
    return {
        "before_2014_08_to_2015_07": round(float(before), 3),
        "review_2015_08_to_2016_06": round(float(during), 3),
        "after_2016_07_to_2017_06": round(float(after), 3),
    }


def _records(frame: pd.DataFrame | pd.Series) -> list[dict[str, object]]:
    table = frame.to_frame() if isinstance(frame, pd.Series) else frame
    records: list[dict[str, object]] = json.loads(
        table.reset_index().to_json(orient="records")
    )
    return records


def _write_numbers(out: Path, numbers: dict[str, object]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(numbers, indent=2, ensure_ascii=False) + "\n"
    (out / "numbers.json").write_text(text, encoding="utf-8")
