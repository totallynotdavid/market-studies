# bvl

`bvl` fills one SQLite file with Lima Stock Exchange (BVL) data from the SMV
open data API and the central bank's (BCRP) statistics API, and runs the
studies in [`studies/`](../studies) on it.

```bash
uv run bvl fetch quotes      # BVL daily quotes, 1996 to today
uv run bvl fetch events      # SMV material events, 2010 to today
uv run bvl fetch indices     # BVL index levels, one request per market day
uv run bvl fetch brokers     # each brokerage firm's amounts, one request per market day
uv run bvl fetch bcrp        # BCRP sol per dollar and copper, 1997 to today
uv run bvl study liquidity   # writes studies/bvl-liquidity
uv run bvl study disclosure  # writes studies/bvl-disclosure
uv run bvl study politics    # writes studies/bvl-politics
uv run bvl study brokers     # writes studies/bvl-brokers
```

`--db` sets the database (default `data/bvl.sqlite`) and `--cache` the response
cache (default `~/.cache/bvl/smv`). `fetch` takes `--start` and `--end` as ISO
dates, and `study` takes `--out`. `-v` logs each query window.

A first fill of quotes and events sends about 190 queries. In November 2026 it
took several hours, mostly in retries. A rerun reads settled windows from the cache and asks
the API only for recent ones.

## The source

The SMV publishes its open data portal from a JSON API at
`https://mvnet.smv.gob.pe/SMV.OData.Api/api/`. It needs no key, but it turns away
clients that do not send a browser User-Agent.

| Query                      | Table          | Data                                                                                                     |
| -------------------------- | -------------- | -------------------------------------------------------------------------------------------------------- |
| `valores/Cotizaciones`     | `quotes`       | Daily open, high, low, close, average and traded amount per ticker, with the previous close and its date |
| `registro/HechosSMVEmisor` | `events`       | Material events: issuer RUC and name, event kind, agreement date, filing minute, sector                  |
| `valores/Indices`          | `index_levels` | Daily IGBVL, ISBVL and the other BVL indices                                                             |
| `valores/MontoNegociado`   | `broker_amounts` | Each brokerage firm's (SAB) bought and sold amount on one day                                          |

Quote and event queries cover at most 90 days, so a fill walks the span in
90-day windows. Index and broker queries answer one day each, so `fetch indices`
and `fetch brokers` ask for every quotes day the table lacks. A broker row
carries no date; the fill stamps it with the day it asked for. The API often fails with a server error about its own log file,
under code `-2147024864` or under `-1` with "being used by another process". The
client retries both with backoff. A window that closed more than 7 days ago
never changes, so its answer is kept gzipped in the cache.

What the data lack:

- **Currency.** The traded amount has no currency, and a stock trades in soles
  or US dollars. Sums across stocks are not comparable.
- **Adjustments.** Prices carry no split or dividend factors. A daily move
  larger than log 2 is dropped as an unrecorded split or a data error.
- **A ticker-to-issuer key.** Quotes name a ticker's company; events carry the
  issuer's RUC. [`issuers.py`](../packages/bvl/bvl/issuers.py) matches the two
  by normalised name, and `OVERRIDES` there lists renamed issuers and names the
  rule cannot match.
- **One index family across time.** The S&P/BVL indices (Peru General, Lima 25,
  the sector indices and others) end on 2025-08-29. From 2025-09-01 the API
  carries only the MSCI NUAM indices, with Peru General, Peru Select and Peru
  Select Capped 15% under new codes, so a series past August 2025 has to be
  joined across the two families.
- **Balanced broker amounts.** A day's bought and sold totals should match, and
  on recent days they do. On some older days they differ (2011-06-06: 51.2
  million bought, 55.2 million sold), and the API's percentages then sum to
  less than 100. A firm is keyed by its SAB code, and the API gives a code
  today's name on every day. Before 2010 the firms' bought amount covers well
  under the quotes' traded amount (42% in 1996), so the API lacks some firms of
  those years.

The BCRP publishes its series at
`https://estadisticas.bcrp.gob.pe/estadisticas/series/api/`, with no key. One
request returns a whole daily series, so a fill sends one request per series
and caches nothing. `bcrp.SERIES` lists the codes the studies read, and they
land in the `bcrp_series` table as (date, code, value):

| Code        | Series                                              |
| ----------- | --------------------------------------------------- |
| `PD04638PD` | Interbank exchange rate, soles per US dollar, sell  |
| `PD04701XD` | Copper, London, US cents per pound                  |

A day the BCRP has not yet published reads `n.d.` and is skipped. The BCRP
keeps its own holidays, so a study carries each value forward onto the BVL
calendar.

## The panel

[`panel.py`](../packages/bvl/bvl/panel.py) turns quotes into returns. A return
is the close against the quote's own previous close, so a stock that skipped
days gets one return across the gap. A local share is a ticker of the BVL form
(`ALICORC1`) whose name does not say fund or ETF.

The market is an equal-weighted index of local shares. A day's return is the
mean log return of the stocks that also traded on the market day before, so a
thin stock's move over several weeks does not land on one day. Trades alternate
between bid and ask, which gives this index a small upward drift; over the 2 to
10 days of an event window it is negligible.

## Modules

| Module          | Responsible for                                                |
| --------------- | -------------------------------------------------------------- |
| `smv.py`        | The API client: windows, envelope codes, retries and the cache |
| `bcrp.py`       | The BCRP API client and its period names                       |
| `records.py`    | API rows to table rows                                         |
| `store.py`      | The SQLite schema, writes and reads                            |
| `fetch.py`      | Filling each table one query at a time                         |
| `panel.py`      | Returns, local shares, market days and the market index        |
| `issuers.py`    | Ticker-to-RUC links                                            |
| `events.py`     | Event rows to filings with topics                              |
| `liquidity.py`  | Coverage and Amihud illiquidity                                |
| `disclosure.py` | The event-study grid, measures, placebos and bootstrap         |
| `politics.py`   | The chained Peru General index and the political event table   |
| `brokers.py`    | Brokerage firm shares and concentration (HHI)                  |
| `figures.py`    | Line and bar charts                                            |
| `studies.py`    | Each study end to end: numbers.json and figures                |
| `cli.py`        | The `bvl` command                                              |

Only `smv.py` and `bcrp.py` touch the network, and only `store.py` opens the
database. A study writes
`numbers.json` and its figures; its README cites them and is checked by hand
after a rerun.
