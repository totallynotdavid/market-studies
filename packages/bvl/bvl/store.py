"""The SQLite panel of BVL quotes, index levels, broker amounts, SMV material
events, SMV quarterly statements and BCRP series.

A fetch writes each answer whole, so a second fetch of the same span replaces
rows and never duplicates them. One filing lists every event kind it reports
as its own row, and the API repeats some of them; `(filing, kind)` keeps one.
"""

import sqlite3

from contextlib import closing
from typing import TYPE_CHECKING

import pandas as pd


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from bvl.records import Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    prev_date TEXT,
    prev_close REAL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    average REAL,
    amount REAL,
    PRIMARY KEY (date, ticker)
);
CREATE TABLE IF NOT EXISTS index_levels (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    prev_close REAL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    PRIMARY KEY (date, code)
);
CREATE TABLE IF NOT EXISTS events (
    filing TEXT NOT NULL,
    kind TEXT NOT NULL,
    ruc TEXT NOT NULL,
    rpj TEXT NOT NULL,
    company TEXT NOT NULL,
    agreed_on TEXT,
    filed_at TEXT,
    description TEXT NOT NULL,
    sector TEXT NOT NULL,
    subsector TEXT NOT NULL,
    company_type TEXT NOT NULL,
    PRIMARY KEY (filing, kind)
);
CREATE TABLE IF NOT EXISTS broker_amounts (
    date TEXT NOT NULL,
    broker TEXT NOT NULL,
    name TEXT NOT NULL,
    bought REAL NOT NULL,
    sold REAL NOT NULL,
    PRIMARY KEY (date, broker)
);
CREATE TABLE IF NOT EXISTS statements (
    rpj TEXT NOT NULL,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    consolidated INTEGER NOT NULL,
    ruc TEXT NOT NULL,
    company TEXT NOT NULL,
    company_type TEXT NOT NULL,
    sector TEXT NOT NULL,
    currency TEXT NOT NULL,
    assets REAL,
    liabilities REAL,
    equity REAL,
    revenue REAL,
    net_income REAL,
    filed_on TEXT,
    PRIMARY KEY (rpj, year, quarter, consolidated)
);
CREATE TABLE IF NOT EXISTS bcrp_series (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (date, code)
);
"""

TABLES = (
    "quotes",
    "index_levels",
    "events",
    "broker_amounts",
    "statements",
    "bcrp_series",
)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    return connection


def write(connection: sqlite3.Connection, table: str, rows: Iterable[Row]) -> int:
    """Insert or replace `rows` in `table` and return how many were given."""
    if table not in TABLES:
        raise ValueError(f"unknown table {table}")
    batch = list(rows)
    if not batch:
        return 0
    columns = list(batch[0])
    placeholders = ", ".join(f":{column}" for column in columns)
    with connection:
        connection.executemany(
            f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            batch,
        )
    return len(batch)


def read(path: Path, query: str) -> pd.DataFrame:
    with closing(sqlite3.connect(path)) as connection:
        return pd.read_sql_query(query, connection)
