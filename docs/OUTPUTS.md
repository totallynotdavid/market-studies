# Outputs

A run reaches readers as JSON files in three shapes:
[`ScoresReport`](../packages/core/index_core/report.py) for the scores,
`TickerReport` for one ticker and `EvidenceReport` for the backtest that backs
the scores.

## scores.json

`eq run` and `eq export` write `outputs/scores.json` unless `--out` says
otherwise ([CLI](CLI.md)). The [ledger](LEDGER.md) publishes files of this
shape.

| Field                             | Meaning                                                                       |
| --------------------------------- | ----------------------------------------------------------------------------- |
| `status`                          | Always `experimental, not validated`                                          |
| `as_of`                           | The trading day the scores are for                                            |
| `universe`                        | The universe file's name without its extension                                |
| `price_source`                    | Where the prices came from: `tiingo` or `synthetic`                           |
| `facts_source`                    | Where the filings came from: `edgar` or `synthetic`                           |
| `horizon_days`                    | The label horizon, 63 trading days                                            |
| `model.train_rows`                | Rows the model was fitted on                                                  |
| `model.holdout_rows`              | Rows in the later holdout the model was measured on                           |
| `model.holdout_auc`               | Pooled AUC on the holdout, `null` when it holds only one outcome              |
| `model.holdout_auc_per_date`      | Equal-weighted mean cross-sectional AUC by holdout date, when measured        |
| `model.holdout_auc_per_date_low`  | Lower end of the 95% date-block bootstrap interval for `holdout_auc_per_date` |
| `model.holdout_auc_per_date_high` | Upper end of the 95% date-block bootstrap interval for `holdout_auc_per_date` |
| `rows[].ticker`                   | The ticker                                                                    |
| `rows[].rank`                     | 1 is the highest probability. Ranks are unique                                |
| `rows[].score`                    | Decile from 1 to 10. 10 is the top tenth                                      |
| `rows[].prob`                     | The model's probability of beating SPY over `horizon_days`                    |
| `left_out[].ticker`               | A member of the run that is not in `rows`                                     |
| `left_out[].reason`               | `no prices`, `no filings` or `other company`                                  |

Rows are ordered by rank. How the score derives from `prob` is in
[Model](MODEL.md#the-score).

The two sources are separate fields, and a run stores the ones it was made from
([CLI](CLI.md#the-database)). A run with `--prices tiingo --filings synthetic`
has `price_source` `tiingo` and `facts_source` `synthetic`. A file may omit
`left_out`, which means none.

## Ticker reports

`eq run` and `eq export` write one file per ticker, `tickers/<TICKER>.json`
beside `--out` unless `--tickers` says otherwise ([CLI](CLI.md)), on one line.
A ticker with no filings has none.

| Field                    | Meaning                                                                                                                                                                                            |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ticker`, `universe`     | The ticker and the universe file's name                                                                                                                                                            |
| `as_of`                  | The trading day. Only filings made before it are used                                                                                                                                              |
| `facts_source`           | Where the filings came from: `edgar` or `synthetic`                                                                                                                                                |
| `name`, `cik`            | The company and its SEC identifier                                                                                                                                                                 |
| `sic`, `sic_description` | The SEC's industry code and its title                                                                                                                                                              |
| `sector`                 | The GICS sector from the universe's companies file, `null` without one                                                                                                                             |
| `series[]`               | One per metric the company has ([Fundamentals](FUNDAMENTALS.md#ticker-reports)): `metric`, `group`, `label`, `unit` (`USD`, `USD/share`, `shares` or `ratio`)                                      |
| `series[].pct_universe`  | Percent of the universe at or below the latest value, `null` if too few                                                                                                                            |
| `series[].pct_sector`    | The same within the sector                                                                                                                                                                         |
| `series[].points[]`      | The latest twelve periods, oldest first: `end`, `value`, `formula`, `parts`                                                                                                                        |
| `valuation`              | What the price implies ([Valuation](VALUATION.md)): `status` is `ok` with a `model`, or `not_meaningful` with a `reason`. A file made before it has none                                           |
| `risk`                   | How the stock behaves ([Risk](RISK.md)): `status` is `ok` with a `fit`, or `insufficient_history` or `not_estimable` with a `reason`. A file made before it has none                               |
| `parts[]`                | A filed figure: `metric`, `sign` (1 or -1), `tag`, `start` (`null` for a balance), `end`, `value` and its `filing`                                                                                 |
| `filing`                 | `accn`, `form`, `fy`, `fp`, `filed` and `url`, the EDGAR page that lists the filing's documents                                                                                                    |

The `value` of a point is the sum of `sign * value` over its `parts`, or, where
`formula` is set, that formula over the parts. Every figure in the report is a
part, so it can be checked against the filing it links to.

## evidence.json

`eq run` and `eq export` write the stored backtest of the scored universe to
`evidence.json` beside `--out`, or to `--evidence` for `eq export`.
`eq backtest` stores the backtest and `eq export` reads it back, so the file
holds exactly what the backtest measured
([Backtest](BACKTEST.md#the-stored-backtest)). When the universe has no stored
backtest, the command deletes the file and says so, so an earlier universe's
evidence is never published beside new scores.

| Field      | Meaning                                                                                                                                                                                                               |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run`      | What was measured: `universe`, `period` (`development` or `holdout`), the dates, the counts of snapshot dates, months, stock-dates and independent windows, the base rate, the horizon, the cost and the data sources |
| `verdict`  | `candidate`, `lightgbm_stays`, `decided` (a held-out run), the three `checks` with their `value` and `passed`, and `shown`                                                                                            |
| `models`   | For each model: mean rank IC, t-statistic, AUC, top-decile hit rate and spread, each with a 95% interval; the top and spread portfolios; the cost ladder; the Deflated Sharpe; the five-factor alpha                  |
| `by_year`  | The mean rank IC of each model in each calendar year                                                                                                                                                                  |
| `by_score` | The hit rate and mean excess return for each LightGBM score                                                                                                                                                           |
| `features` | The rank IC of each feature alone, with its family, and `feature_hurdle_t`, the t-statistic a new factor needs                                                                                                        |
| `trials`   | The ledger of every specification measured on the database, with its Sharpe ratio                                                                                                                                     |

`verdict.shown` is computed: it is true only when the run is `holdout`, the
candidate is `lightgbm` and every check passed. The score is the one LightGBM
makes, so a baseline that passes the checks does not show it. A development run
has no verdict, because the months it measures chose the candidate. Every other
number in the file is rounded only where it is printed.
