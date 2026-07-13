# Sovereign Conviction Engine — Function Reference

Every function and class across the project, grouped by file. Pure/reusable
logic lives in `structural_grid.py` and `engines/`; the `pages/` files are
Streamlit UI on top of that logic (plus a few page-local helpers that never
got promoted to a shared engine).

---

## `structural_grid.py`

Pure data (no functions besides one helper) encoding your uploaded
allocation grid image: sections → layers → tickers → target weights →
accumulation protocol notes.

| Function | Signature | What it does |
|---|---|---|
| `flatten_universe` | `flatten_universe() -> list[dict]` | Flattens `SECTIONS` (+ `SATELLITE`, currently empty -- see below) into one row per ticker: `{ticker, section, layer, layer_weight, section_target_pct, effective_weight, protocol, group}`. `effective_weight = section_target_pct × layer_weight` — this is a **ceiling for the whole layer**, not an automatic even split across every ticker inside it (exception: the four "Business & Futuristic Overlay" layers each contain exactly one ticker with an explicit weight, so `effective_weight` there IS the real per-ticker target). |

**Module-level data (not functions, but referenced everywhere):**
- `SECTIONS` — the core 100% portfolio (INFRA, ENERGY & COMMODITY, AI/SEMIS, EM, Business & Futuristic Overlay, BTC, GOLD, CASH).
- `SATELLITE` — empty dict; the old watchlist tier has been fully merged into the core sections above.
- `NON_EQUITY_TICKERS` — `{"BTC", "GOLD", "CASH"}`, skipped by engines that need P/S data.
- `CORE_ELIGIBLE_TICKERS` — tickers flagged as core-eligible per your notes (drives `is_core` in the Valuation Engine).

---

## `engines/expectations_engine.py`

### `class SovereignExpectationsEngine`
Standalone, decoupled engine that measures how much forward revenue growth
is already priced into a ticker's valuation, and how much would be
*required* to justify the current multiple.

| Method | Signature | What it does |
|---|---|---|
| `__init__` | `(self, ticker: str, is_core: bool = False)` | Validates the ticker string, stores it uppercased/stripped, opens a `yfinance.Ticker` handle. |
| `_parse_estimate_number` | `(self, value) -> float` | Converts raw or string analyst estimates (e.g. `"12.5B"`) into plain floats, handling T/B/M/K suffixes and `N/A`-style strings. |
| `_safe_get_df` | `(self, attr_name: str) -> pd.DataFrame` | Safely pulls a DataFrame off a volatile `yfinance` attribute/method, swallowing exceptions and returning an empty frame on failure. |
| `_align_index_tz` | `(self, series, reference_tz) -> pd.Series` | Single choke-point for all timezone handling — aligns a series' `DatetimeIndex` to a reference tz (or strips tz entirely if `reference_tz` is `None`). |
| `_select_forward_revenue_row` | `(self, index_labels) -> str \| None` | Picks the analyst-estimate row representing the **next fiscal year** of revenue, explicitly avoiding false matches on the current-year (`"0y"`) or trailing-year (`"-1y"`) rows. |
| `hydrate_standalone_data` | `(self) -> pd.DataFrame` | Builds the full `Revenue_TTM` / `Market_Cap` / `PS_Ratio` history from scratch (5y price history + quarterly/annual financials + shares outstanding), with cadence-aware TTM construction and confidence flags (`market_cap_confidence`, `revenue_cadence` in `df.attrs`). Raises `ValueError` on degenerate inputs (no revenue, no market cap, non-positive revenue) instead of producing silent garbage. |
| `fetch_analyst_revenue_estimate` | `(self) -> dict` | **Priority 1** forward-growth source: parses Yahoo's institutional analyst revenue estimate table for the next-fiscal-year figure. |
| `estimate_historical_revenue_growth` | `(self, df_data) -> dict` | **Priority 2–4** fallback: blends 1Y trailing growth (50% weight), 2Y CAGR (30%), and a cadence-aware recent-momentum window (20%) into a single clipped growth estimate when no analyst estimate is available. |
| `execute` | `(self, df_data=None) -> dict` | Runs the full pipeline: current P/S vs. historical percentile/median/75th/90th, forward revenue (analyst → historical fallback → neutral 0% baseline), required growth to "normalize" the multiple, years-to-normalize, and the final **Expectations Burden Score (0–100)** + classification (`✅`/`🟡`/`🟠`/`🔴`). Returns the full `self.metrics` dict. |

**Class constants:** `EXPECTATIONS_STATUS_LEGEND` (status → plain-English meaning), `GROWTH_CLIP_BOUNDS = (-0.50, 1.50)`, `MIN_VALID_PS_OBSERVATIONS = 30`.

---

## `engines/valuation_engine.py`

Extracted, unchanged-logic functions from the original Valuation & Discipline
Engine — shared by `Home.py` and `pages/2_Valuation_Engine.py` so there's one
copy instead of two that could drift apart.

| Function | Signature | What it does |
|---|---|---|
| `calculate_data_quality` | `(df, report_freq, fx_note) -> str` | Builds a one-line health summary: sample thickness (Strong/Moderate/Thin), reporting frequency (annual vs. quarterly), and whether FX conversion was applied. |
| `classify_action` | `(multiplier: float) -> str` | Maps a 0–1.5x deployment multiplier to a human posture label, from `🛑 Pause` up to `⚡ Accelerated Opportunity Mode`. |
| `style_batch_status` | `(val) -> str` | Returns a CSS `background-color` string keyed off keywords in the status text (`Value`, `Scarcity`, `Premium`, `Halt`, `Normal`) — used for `DataFrame.style` in the batch scanner. |
| `calculate_distribution_diagnostics` | `(series, current_val) -> dict` | Returns `{skewness, percentile, shape}` — where the current value ranks in its own P/S history and whether that history is symmetric, moderately skewed, or fat-tailed (skew ≥ 1.0). Returns a neutral placeholder if fewer than 30 clean observations exist. |
| `calculate_robust_z_score` | `(series, current_val) -> (robust_z, median, mad)` | Median-Absolute-Deviation-anchored z-score (`0.6745 × (x − median) / MAD`), more resistant to outliers than a standard z-score. Returns `(0.0, median, mad)` if MAD is zero/NaN or fewer than 30 observations. |
| `sovereign_allocation_engine` | `(ticker, is_core, z_score, robust_z_score, z_threshold, percentile, skewness, macro_mode, floors) -> (status_stance, allocation_multiplier, explanation, distribution_reliability)` | The core regime-aware decision function. Cross-validates standard z-score, robust z-score, and percentile rank against each other and against the macro liquidity mode (Expansion / Transition / Crunch) to produce a status label, a 0–1.5x multiplier, a plain-English explanation, and a distribution-trust label. Core assets get protective floors (`floors['crunch']`/`['transition']`/`['expansion']`) instead of being cut to zero. |
| `get_hardened_valuation_data` | `(ticker, years) -> (df_daily, error, report_freq, fx_note)` — `@st.cache_data(ttl=86400)` | The full data pipeline: pulls daily price history, quarterly + annual revenue (auto-splicing older annual data onto the front of a shorter quarterly series), shares-outstanding history (with `get_shares_full`, falling back to static `sharesOutstanding`), applies FX normalization when `financialCurrency != currency`, and builds a daily `PS_Ratio` series. Returns a descriptive error string instead of raising on any failure point. Contains three private helpers used only inside it: `find_revenue_row`, `classify_frequency`, `apply_fx_normalization`. |

**Module constants:** `MODEL_VERSION`, `STATUS_LEGEND`, `DEFAULT_CORE`.

---

## `engines/quality_engine.py`

Answers a question the other three engines don't: **is this a good
business**, independent of what it costs (Valuation), how much growth is
priced in (Expectations), or whether now is a good time to deploy capital
at all (Macro). Scores ROIC, gross margin, FCF margin, net debt/EBITDA,
and share dilution against an explicit, editable threshold table.

| Function | Signature | What it does |
|---|---|---|
| `score_metric` | `(value, metric_name) -> float` | Maps a raw metric value to a 0–100 score using `QUALITY_THRESHOLDS[metric_name]`'s band table (first matching band wins). Returns `NaN` if the value is missing, so a missing metric is excluded from the blend rather than silently scored as zero. |
| `classify_quality` | `(score) -> str` | Maps a blended 0–100 Quality Score to a status label, from `⚪ Insufficient Data` through `🟢 Fortress Quality`. |
| `_first_present` | `(df, candidates) -> str \| None` | Returns the first row label from `candidates` that actually exists in a financial statement DataFrame's index — handles `yfinance`'s inconsistent row naming across tickers/versions. |
| `_latest_value` | `(df, row_label) -> float` | Returns the most recent non-NaN column's value for a statement row. |
| `_prior_year_value` | `(df, row_label) -> float` | Returns the second-most-recent column's value for a statement row — used for the YoY dilution comparison. |
| `get_quality_data` | `(ticker) -> (metrics: dict \| None, error: str \| None)` — `@st.cache_data(ttl=86400)` | Pulls annual income statement, balance sheet, and cash flow via `yfinance`, then derives: `roic` (NOPAT ÷ Invested Capital, with an effective-tax-rate estimate from Tax Provision/Pretax Income, falling back to the 21% US statutory rate), `gross_margin`, `fcf_margin` (Operating Cash Flow − \|CapEx\|, ÷ Revenue), `net_debt_to_ebitda`, and `dilution_rate` (YoY change in diluted/basic average shares). Also returns raw components (prefixed `_`) for the standalone page's transparency panel. Returns a descriptive error instead of raising on any failure point, matching the other engines' pattern. |
| `compute_quality_score` | `(ticker, metrics) -> dict` | Scores each available metric via `score_metric`, re-normalizes `QUALITY_WEIGHTS` over whichever metrics were actually resolvable (a ticker missing 2 of 5 metrics doesn't get penalized as if those were zero), and classifies the result. Also attaches a `sector_caveat` string for tickers in `SECTOR_CAVEAT_TICKERS` (royalty/streaming names like FNV/WPM/TPL, where a generic operating-company template is a poor fit) so a misleading-looking score is flagged rather than silently trusted. |

**Module constants:** `MODEL_VERSION`, `QUALITY_STATUS_LEGEND`, `SECTOR_CAVEAT_TICKERS`, `QUALITY_THRESHOLDS` (the editable band-scoring policy), `QUALITY_WEIGHTS` (ROIC 30% / FCF margin 20% / Net Debt-EBITDA 20% / Gross margin 15% / Dilution 15%).

---

## `engines/portfolio_engine.py`

The one engine that looks at the RESULT of your allocation decisions as a
whole, instead of scoring one ticker at a time.

| Function | Signature | What it does |
|---|---|---|
| `check_concentration` | `(universe_rows, limits=None, ignore_tickers=None) -> dict` | Runs directly against `structural_grid.flatten_universe()` output — pure arithmetic, no fetch required. Flags position/layer/section weights exceeding `DEFAULT_LIMITS` (or a custom `limits` dict) and checks the CASH sleeve against `min_cash_buffer`. `ignore_tickers` (defaults to `{"BTC","GOLD","CASH"}`) is excluded from *position* and *layer* breach checks only — a 25% BTC cold-wallet allocation is a deliberate strategic sleeve, not a diversification failure — but these tickers still count fully toward `section_totals` and the cash-buffer check. Returns `{position_breaches, layer_breaches, section_breaches, cash_buffer, section_totals, layer_totals}`. |
| `get_price_returns` | `(tickers: tuple, period="1y") -> (returns_df, failed_tickers)` — `@st.cache_data(ttl=3600)` | One batched `yf.download()` call for the whole ticker list (not N separate per-ticker calls like the scoring engines each do) — returns a wide DataFrame of daily % returns plus a list of tickers that didn't resolve. `tickers` must be a tuple, not a list, so it's hashable for the cache decorator. |
| `compute_correlation_matrix` | `(returns_df) -> pd.DataFrame` | Pairwise Pearson correlation of daily returns. Pure pandas, no fetch. |
| `flag_correlated_pairs` | `(corr_matrix, threshold=0.80) -> list[dict]` | Every ticker pair whose return correlation exceeds `threshold`, sorted descending. Each entry: `{ticker_a, ticker_b, correlation}`. |
| `cluster_correlated_groups` | `(pairs) -> list[set]` | Union-find merge of overlapping flagged pairs into clusters — if A-B and B-C are both flagged, reports `{A, B, C}` as one cluster instead of two separate pairs, since that's the actual "these are all one bet" group. |
| `classify_portfolio_health` | `(concentration, correlation_pairs) -> str` | Single headline verdict combining both checks, from `🟢 Balanced` through `🔴 Significantly Concentrated`. |

**Module constants:** `MODEL_VERSION`, `DEFAULT_LIMITS` (max single position 10%, max layer 15%, max section 25%, min cash buffer 10%, correlation threshold 0.80 — explicit editable policy, same philosophy as `QUALITY_THRESHOLDS`).

---

## `pages/6_Portfolio_Engine.py`

No new functions — two tabs built on `engines/portfolio_engine.py`:

**📐 Concentration** — editable limit inputs, a section-weight bar chart with the limit line drawn on it, and breach tables for position/layer/section, all computed live against `structural_grid.py` (no button needed beyond adjusting the limit inputs).

**🔗 Correlation** — ticker source picker (last `Home.py` scan via `st.session_state["last_grid_scan_tickers"]`, or manual multiselect), lookback/threshold controls, a Plotly correlation heatmap, flagged-pair table, and cluster breakdown. Ends with the combined `classify_portfolio_health` verdict once correlation has run.

---

## `pages/4_Quality_Engine.py`

No new functions — imports everything from `engines/quality_engine.py`
(see table above) and adds the Streamlit sidebar, metric cards (ROIC,
Gross Margin, FCF Margin, Net Debt/EBITDA, Dilution), a horizontal bar
chart of the five 0–100 component scores, and a raw-statement-components
transparency panel.

---

## `pages/5_Ticker_Verifier.py`

Diagnostic tool -- doesn't score or rank anything, just tells you whether a
symbol will actually work in the other four pages before you trust it or
add it to `structural_grid.py`.

| Function | Signature | What it does |
|---|---|---|
| `verify_ticker` | `(ticker: str) -> dict` — `@st.cache_data(ttl=3600)` | Runs the same category of `yfinance` calls the three scoring engines depend on (`.info`, `.history`, `.quarterly_financials`, `.financials`, `.balance_sheet`, `.cashflow`, `.get_shares_full`) and reports what's actually available, without computing any score. Returns a verdict: `✅ Fully compatible`, `🟡 Partial`, `🟠 Price only (likely an ETF/index)`, `🔴 Failed to resolve`, or `⚪ Non-equity sleeve` for BTC/GOLD/CASH. |
| `style_verdict` | `(val) -> str` | CSS background-color string keyed off the verdict text, for the batch/grid dataframe views. |

Three tabs: **Single Ticker** (one lookup with full detail), **Batch
Paste** (any pasted list of tickers, comma/space/newline separated),
**Verify Whole Grid** (runs every ticker currently in `structural_grid.py`
via `flatten_universe()` and summarizes pass/fail counts).

---

## `Home.py` — Combined Conviction Dashboard

Two tabs, sharing one scoring function so the blend logic lives in exactly
one place instead of being duplicated per-tab:

| Function | Signature | What it does |
|---|---|---|
| `scan_ticker` | `(ticker, is_core) -> dict` | Runs all three engines on one ticker (`valuation_engine.get_hardened_valuation_data` + `sovereign_allocation_engine`, `SovereignExpectationsEngine.execute`, `quality_engine.get_quality_data` + `compute_quality_score`), blends them into a Conviction Score (`(valuation_component + (100 − expectations_burden) + quality_score) / 3`), and returns a `Deployment Multiplier` (macro overlay applied, capped further when Expectations burden ≥55/75 or Quality <50/35) — **without** applying any position weight yet, since the two tabs size differently. |
| `format_results` | `(df) -> pd.DataFrame` | Shared display formatting for both tabs' result tables (percent/currency/score string formatting), so formatting logic isn't duplicated either. |

**Tab 1 — 📋 Structural Grid Scan**: pick sections/tickers from `structural_grid.py`, calls `scan_ticker()` per ticker, then applies each ticker's real `effective_weight` from the grid to size **Suggested $ Deployment** = structural weight × portfolio value × deployment multiplier.

**Tab 2 — 🔍 Ad-Hoc Ticker Scan**: run the identical engines/blend on *any* ticker(s) typed or pasted in, including ones with no entry in `structural_grid.py` at all — for vetting a new idea before deciding whether it belongs in the grid. Since there's no real structural weight, $ sizing is opt-in (a checkbox) and uses a hypothetical weight % you set yourself, clearly labeled illustrative rather than tied to an actual portfolio target. Lets you flag which of the entered tickers should be treated as "core" (affects the Valuation Engine's floor logic) via a multiselect built from whatever you typed.

---

## `pages/1_Expectations_Engine.py`

Thin Streamlit wrapper around `SovereignExpectationsEngine`, plus small formatting helpers local to this page (not promoted to the shared engine since they're pure display formatting, not scoring logic):

| Function | Signature | What it does |
|---|---|---|
| `run_engine` | `(ticker, is_core)` — `@st.cache_data(ttl=3600)` | Instantiates `SovereignExpectationsEngine`, hydrates data, executes, returns `(metrics, df_data)`. Cached 1 hour so repeated widget interactions don't re-hit `yfinance`. |
| `fmt_pct` | `(x) -> str` | Formats a float as a percentage string, or `"N/A"` if NaN/non-finite. |
| `fmt_num` | `(x, prefix="", suffix="") -> str` | Formats a float to 2 decimals with optional prefix/suffix, or `"N/A"`. |
| `fmt_money` | `(x) -> str` | Formats a dollar figure with T/B/M suffixes (e.g. `$2.35B`), or `"N/A"`. |

---

## `pages/2_Valuation_Engine.py`

No new functions — imports everything from `engines/valuation_engine.py`
(see table above) and adds the Streamlit sidebar, single-ticker view, batch
core scanner, and the three Plotly charts (P/S history with z/MAD/percentile
bands, rolling Z-score trace, distribution histogram).

---

## `pages/3_Macro_Engine.py`

The FRED-driven macro regime engine. Kept as one script-style page (not
refactored into `engines/`, per the design note in `README.md`) since it's
a portfolio-wide regime call, not a per-ticker one.

### Data fetch & alignment

| Function | Signature | What it does |
|---|---|---|
| `fetch` | `(series: str) -> pd.Series` — `@st.cache_data(ttl=86400)` | Pulls a FRED series via the `/fred/series/observations` REST endpoint, returns a date-indexed float `Series`, or empty on any network/parse failure. |
| `align` | `(s: pd.Series) -> pd.Series` | Reindexes a series onto the shared `common_index` (union of all fetched series' dates) and forward-fills, so every "latest" reading reflects the same as-of date across metrics that publish on different schedules. |

### Liquidity & trend signals

| Function | Signature | What it does |
|---|---|---|
| `liq_momentum_state` | `(trend_val, accel_val) -> str` | Labels liquidity momentum as expanding/contracting, each further split into "accelerating" vs. "losing steam"/"bottoming" using the trend's 1st and 2nd derivative. |
| `trend` | `(series, window=30, smooth=5) -> float` | Standardized `%change(window)` then `rolling(smooth).mean()`, returning the latest value — the common time-basis used for yield/dollar/credit trend so they're comparable to each other. |
| `credit_state` | `(val) -> str` | Buckets the credit-spread trend into `"STRESS SPIKE"` (>0.15), `"WIDENING"` (>0), or `"STABLE"`. |
| `detect_system_phase` | `(liq, dxy, credit) -> str` | The primary regime classifier — combines liquidity direction, dollar direction, and credit state into one of 7 phases (`SYSTEM BREAK`, `FRACTURE`, `CREDIT STRESS`, `LIQUIDITY EXPANSION`, `EXPANSION (credit lagging)`, `FRAGILE EXPANSION`, `NORMAL`), checked in stress-first priority order. |
| `classify_regime` | `(y, d, threshold=0.02) -> str` | Classifies yield/dollar direction into `QT` / `SOFT_PIVOT` / `HARD_PIVOT` / `TRANSITION`, requiring both signals to clear a 2% minimum-magnitude bar before counting as directional (filters out noise-sized moves). |
| `compute_dca_mode` | `(current_trend, trend_history, min_history=10) -> str` | Ranks the current liquidity impulse against its own full history (percentile) rather than a fixed threshold — `"HIGH DCA"` (≥70th pct), `"MEDIUM DCA"` (≥40th), or `"LOW / PAUSE"`. |

### Trigger-signal overlay (heuristic layer)

| Function | Signature | What it does |
|---|---|---|
| `distribution_trap` | `(dxy_trend_val, credit_trend_val_, liq_trend_val) -> bool` | Heuristic: dollar rising + credit not (yet) confirming stress + liquidity falling — reads as "quiet distribution." Deliberately can disagree with `detect_system_phase`'s `NORMAL` reading on the same inputs. |
| `forced_liquidation_signal` | `(credit_trend_val_, liq_acceleration_val, threshold=0.10) -> bool` | Heuristic: credit widening past a lower bar than the official stress spike, combined with liquidity contraction still accelerating — reads as forced (not voluntary) selling. |
| `front_run_pivot` | `(liq_trend_val, liq_acceleration_val, yield_trend_val) -> bool` | Heuristic: liquidity expanding and accelerating while yields aren't rising — reads as liquidity turning before the broader narrative catches up. |
| `distribution_trap_score` | `(dxy_trend_val, credit_trend_val_, liq_trend_val, liq_acceleration_val, is_trap, threshold=0.10) -> int` | Graded 0–100 version of `distribution_trap`, built from the *same three inputs and cutoffs* so a "CONFIRMED" grade can never contradict the boolean trigger. Hard-capped below the CONFIRMED band whenever `is_trap` is `False`. |
| `distribution_trap_grade` | `(score) -> str` | Buckets the score into `CONFIRMED` (≥75) / `ELEVATED` (≥50) / `WATCH` (≥25) / `LOW`. |
| `compute_positioning_score` | `(concentration, breadth, vol_ratio) -> int` | Standalone 0–100 crowding estimate from three manually-entered inputs (index concentration, market breadth, vol-term ratio) — fully inert unless the sidebar's positioning overlay is enabled. |
| `positioning_state` | `(score) -> str` | Buckets the positioning score into `CROWDED` / `ELEVATED` / `NEUTRAL` / `UNDEROWNED`. |
| `execution_playbook` | `(phase) -> dict` | Returns an illustrative `{stance, notes}` capital-stance suggestion keyed to `system_phase` — a starting point, not a validated backtest. |
| `resolve_action` | `() -> (trigger, stance, rationale)` | Priority resolver when multiple triggers fire simultaneously: Forced Liquidation > Distribution Trap > Pivot Signal > fallback to the System Phase playbook. All raw signals stay visible on the dashboard regardless of which one wins here. |

### Sovereign 15-year engine (multi-horizon macro score + governor)

| Function | Signature | What it does |
|---|---|---|
| `liquidity_trend_series` | `(net_liq_series, window_weeks, smooth_weeks) -> pd.Series` | Same trend construction as `trend()`, but returns the full series (not just the latest value) so short/medium/long horizons can each be tracked. |
| `_last_or_zero` | `(s) -> float` | Returns the last non-NaN value of a series, or `0` if empty — a small safety wrapper used when pulling out `liq_multi["short"/"medium"/"long"]`. |
| `trend_series` | `(series, window=30, smooth=5) -> pd.Series` | Same as `trend()` but returns the whole rolling series, used to build percentile-rank history for `compute_confidence`. |
| `percentile_rank` | `(current, hist_series, min_history=10) -> float` | Fraction of a signal's own history below the current reading (0.5 = neutral fallback if insufficient history). Used to normalize liquidity/credit/yield/dollar onto a comparable 0–1 scale before weighting. |
| `compute_macro_score` | `(components: dict, weights: dict) -> float` | Weighted sum of the four signed components (`liquidity`, `credit`, `yield`, `dollar`), scaled to roughly −100..+100. |
| `compute_confidence` | `(components, score) -> str` | `"HIGH"` / `"MEDIUM"` / `"LOW"` based on what fraction of the 4 components agree in sign with the overall score — i.e. whether the score reflects consensus or conflicting signals. |
| `map_score_to_phase` | `(score) -> str` | Buckets `macro_score` into `STRONG EXPANSION` / `EXPANSION` / `NEUTRAL` / `CONTRACTION` / `STRONG CONTRACTION`. |
| `capital_allocation_target` | `(phase, conf) -> float` | Looks up `ALLOCATION_POLICY[(phase, confidence)]` — an explicit, editable policy table, not a discovered "truth." |
| `liquidity_kill_switch` | `(liq_short, liq_accel, threshold=-0.03) -> bool` | Circuit breaker: fires only when short-horizon liquidity is meaningfully negative **and** still accelerating downward (actively worsening, not just currently negative). |
| `discipline_check` | `(target, actual) -> str` | Compares your manually-entered current allocation against the model's target: `"VIOLATION"` (>20% gap), `"DRIFT"` (>10%), or `"ALIGNED"`. |
| `system_governor` | `(target_alloc, kill_switch, discipline, trigger, current_alloc_val, dxy_trend_val, positioning_on, positioning_score_val) -> (governed_target, note)` | Final haircut layer — only ever *reduces* the policy target, never increases it. Stacks every applicable condition multiplicatively (Distribution Trap cap, USD mid-spectrum damping, positioning overlay, kill-switch halving, discipline-violation trim) and reports **all** triggered reasons, not just the first match. |
| `rebalance_suggestion_with_trigger` | `(current, target, trigger, band=0.05) -> str` | Turns the governed target into a plain-English suggestion, deferring to the same trigger priority as `resolve_action()` so this panel can never contradict the headline stance. |
| `tilt_grid` | `(base_grid, score, high_beta, defensive, max_tilt=0.30) -> dict` | Tilts your real structural allocation grid (`BASE_GRID`) toward high-beta sleeves when `macro_score` is positive and toward defensive sleeves when negative, capped at ±30% relative change, then renormalized to sum to 100%. |
| `generate_alerts` | `(sys_phase, trigger, kill_switch, discipline) -> list[str]` | Collects human-readable alert strings for any active kill-switch, stress phase, forced-liquidation trigger, or discipline violation. |
| `log_snapshot` | `(as_of, score, phase, target, actual, portfolio_value=None) -> None` | Appends a row to a local CSV history file (`sovereign_engine_history.csv`). **Not durable on ephemeral hosts** like Streamlit Community Cloud — see the in-file caveat. |
| `load_history` | `() -> pd.DataFrame` | Reads the local CSV history file back in, or returns an empty frame if it doesn't exist / fails to parse. |
| `drawdown_protection` | `(value_series, threshold=0.20) -> (status, current_drawdown)` | Computes drawdown-from-peak on your logged portfolio values; flags `"DRAWDOWN PROTECTION ACTIVE"` past a 20% threshold. |
| `format_liquidity` | `(x_millions) -> str` | Formats a $-millions figure with T/B/M suffixes at the correct scale (FRED series are already in millions). |

### Presentation-only helpers

| Function | Signature | What it does |
|---|---|---|
| `get_style` | `(mapping, key, default_accent, default_bg) -> dict` | Looks up a state's color/icon style dict from one of the `*_STYLE` maps, falling back to a neutral default. |
| `arrow_html` | `(x, up_color, down_color, flat_color) -> str` | Returns a colored ▲/▼/→ HTML span based on the sign of `x`. |
| `metric_card` | `(label, value, delta_pct, note="", icon="") -> None` | Renders one of the custom HTML "sme-card" metric tiles (label, value, colored delta arrow, optional note). |
| `badge_card` | `(label, value, style, note="") -> None` | Renders a colored "sme-badge" status tile using a style dict from `get_style`. |

---

## Quick index — where is the logic that actually decides X?

| Question | Function | File |
|---|---|---|
| "Is this ticker rich or cheap vs. its own history?" | `sovereign_allocation_engine` | `engines/valuation_engine.py` |
| "How much growth is priced in vs. required?" | `SovereignExpectationsEngine.execute` | `engines/expectations_engine.py` |
| "Is this a good business at all?" | `compute_quality_score` | `engines/quality_engine.py` |
| "What's the current macro regime?" | `detect_system_phase`, `classify_regime` | `pages/3_Macro_Engine.py` |
| "Given everything, how much should I actually deploy?" | `system_governor` (macro) / blended score logic | `pages/3_Macro_Engine.py` / `Home.py` |
| "How much of the portfolio should this ticker structurally get?" | `flatten_universe` | `structural_grid.py` |
