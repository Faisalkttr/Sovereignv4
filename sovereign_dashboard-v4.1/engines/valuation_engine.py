"""
Sovereign Valuation & Discipline Engine -- v4.2 sector-aware drop-in replacement.

This file upgrades the valuation engine from a P/S-only engine to a
sector-aware valuation engine while preserving the existing external
interface used by Home.py and pages/2_Valuation_Engine.py.

KEY DESIGN POINTS
-----------------
1. The old function remains:

       get_hardened_valuation_data(ticker, years)

   and still returns:

       df_daily, error, report_freq, fx_note

   so Home.py and pages/2_Valuation_Engine.py do not need to change.

2. The old column remains:

       PS_Ratio

   but it is now a backward-compatibility alias for:

       Valuation_Ratio

3. A new function is added:

       get_hardened_valuation_data_v2(ticker, years)

   which returns:

       df_daily, error, report_freq, fx_note, sector, valuation_model

   for future caller upgrades.

4. The distribution / allocation framework is unchanged:

       calculate_distribution_diagnostics()
       calculate_robust_z_score()
       sovereign_allocation_engine()

   These functions remain generic and operate on whatever valuation
   ratio series is produced.

5. Valuation model selection:

       SOFTWARE                 -> PS
       SEMICONDUCTORS           -> PS
       INFORMATION TECHNOLOGY   -> PS
       COMMUNICATION SERVICES   -> PS

       INDUSTRIAL               -> EV_EBIT
       ENERGY                   -> EV_EBITDA
       BASIC MATERIALS          -> EV_EBITDA
       UTILITIES                -> EV_EBITDA

       FINANCIAL SERVICES       -> PB
       REAL ESTATE              -> P_FFO, with PB fallback if FFO missing

       FNV / WPM / TPL          -> PS override

"""

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf


MODEL_VERSION = "v4.2-Sector-Valuation"

STATUS_LEGEND = {
    "💎 Value Zone": "Valuation is materially below historical range by multiple metrics.",
    "✅ Normal Range": "Valuation is inside broad historical parameters.",
    "🟡 Core Premium Accumulation": "Core asset is expensive but not statistically extreme.",
    "🟡 Tactical Premium Zone": "Tactical asset is expensive; deployment intensity is reduced.",
    "🟠 Core High-Expectation Zone": "Core asset is above the pressure threshold; accumulation is throttled.",
    "🔵 Core Scarcity Premium": "Core asset is statistically extreme but protected by sovereign-core floor rules.",
    "🔴 Tactical Valuation Halt": "Tactical asset valuation pressure is extreme; fresh deployment is paused.",
}

DEFAULT_CORE = ["FNV", "TPL", "ASML", "PANW"]

# Explicit, permanent core overrides -- tickers that should NEVER be
# subject to the full 🔴 Tactical Valuation Halt (allocation_multiplier =
# 0.00), regardless of what core list a caller passes in. Use this for
# names you have multi-decade structural conviction in (e.g. AI/compute
# infrastructure, semiconductors, cybersecurity, scarce real assets) and
# never want fresh-capital deployment fully paused on, even during a
# genuine valuation extreme. At worst these get throttled to a protective
# floor (see DEFAULT_ALLOCATION_FLOORS below), never zeroed. Empty by
# default -- populate to match your own thesis, e.g.:
#
#     STRUCTURAL_CORE_OVERRIDES = {"NVDA", "TSM", "AVGO", "CRWD", "ASML"}
STRUCTURAL_CORE_OVERRIDES = set()

# Suggested default Z-score / robust-Z-score level that counts as a
# "valuation pressure" trigger inside sovereign_allocation_engine(). This
# is only a convenience default for callers -- the function itself still
# takes z_threshold as an explicit argument. Raise this if the halt/throttle
# is firing on names you intend to hold through a structural re-rating
# rather than a mean-reverting cycle.
DEFAULT_Z_THRESHOLD = 2.0

# Suggested default allocation floors retained for CORE names even when
# their valuation trips an extreme trigger, keyed by macro regime. Core
# names never fully halt under this engine; these floors set how much
# fresh capital, if any, keeps flowing in each regime. Also only a
# convenience default -- sovereign_allocation_engine() still takes
# `floors` as an explicit argument.
DEFAULT_ALLOCATION_FLOORS = {
    "expansion": 0.25,
    "transition": 0.15,
    "crunch": 0.05,
}

# Suggested default lookback (in years) for building a ticker's historical
# valuation-ratio distribution. A longer window means a genuine multi-year
# structural re-rating shows up as part of the "normal range" rather than
# looking like a statistical anomaly relative to a short, pre-rerating
# baseline. Only a convenience default -- get_hardened_valuation_data()
# and get_hardened_valuation_data_v2() still take `years` explicitly.
DEFAULT_LOOKBACK_YEARS = 7


def resolve_core_status(ticker, core_tickers=None):
    """
    Determines whether `ticker` should be treated as "core" (throttled,
    never fully halted) vs "tactical" (subject to the full 🔴 Tactical
    Valuation Halt) when calling sovereign_allocation_engine().

    Priority order:
        1. STRUCTURAL_CORE_OVERRIDES -- explicit, permanent core tickers
           that always win, regardless of any list passed in.
        2. `core_tickers` -- an optional caller-supplied core list. Pass
           in your own portfolio's structural conviction set here once
           you've defined it, rather than relying on the narrow
           DEFAULT_CORE starter list below.
        3. DEFAULT_CORE -- fallback starter list if no caller list is given.

    Returns:
        bool
    """
    is_core, _source = resolve_core_status_verbose(ticker, core_tickers)
    return is_core


def resolve_core_status_verbose(ticker, core_tickers=None):
    """
    Same resolution logic as resolve_core_status(), but also reports which
    tier decided the outcome, so a caller/UI can flag the easy-to-miss
    case where STRUCTURAL_CORE_OVERRIDES is still empty and a ticker is
    silently falling through to the narrow DEFAULT_CORE fallback -- i.e.
    the "always-core" protection framework exists but hasn't actually been
    configured for this ticker yet.

    Returns:
        (is_core: bool, source: str) where source is one of
        "structural_override", "caller_list", or "default_fallback".
    """
    ticker = str(ticker).upper()

    if ticker in STRUCTURAL_CORE_OVERRIDES:
        return True, "structural_override"

    if core_tickers is not None:
        return ticker in {str(t).upper() for t in core_tickers}, "caller_list"

    return ticker in DEFAULT_CORE, "default_fallback"


# ----------------------------------------------------------------------
# Sovereign Valuation Engine v4.2
# Sector-aware valuation model selection
# ----------------------------------------------------------------------

VALUATION_MODELS = {
    "SOFTWARE": "PS",
    "SEMICONDUCTORS": "PS",
    "INFORMATION TECHNOLOGY": "PS",
    "COMMUNICATION SERVICES": "PS",

    "INDUSTRIAL": "EV_EBIT",
    "ENERGY": "EV_EBITDA",
    "BASIC MATERIALS": "EV_EBITDA",
    "UTILITIES": "EV_EBITDA",

    "FINANCIAL SERVICES": "PB",
    "REAL ESTATE": "P_FFO",
}

# Royalty / streaming / land companies are structurally weird.
# Until a dedicated royalty model exists, historical P/S is the safest
# comparable anchor for these specific names.
SPECIAL_VALUATION_MODELS = {
    "FNV": "PS",
    "WPM": "PS",
    "TPL": "PS",
}

# Use this for tickers where Yahoo sector/industry data is missing,
# wrong, or too generic. This is especially useful for non-US listings.
#
# Examples:
#
# TICKER_MODEL_OVERRIDES = {
#     "2222.SR": "EV_EBITDA",
#     "ADNOCGAS.AB": "EV_EBITDA",
#     "ADPORTS.AD": "EV_EBIT",
#     "0883.HK": "EV_EBITDA",
#     "0941.HK": "EV_EBITDA",
# }
TICKER_MODEL_OVERRIDES = {}

# How many of the most recent annual reports EV/EBIT and EV/EBITDA are
# willing to scan backward through to find a positive anchor value before
# giving up and falling back to P/S. yfinance typically exposes ~4 years
# of annual statements, so this also acts as a practical ceiling.
EBIT_EBITDA_LOOKBACK_PERIODS = 4

# Heuristic buffer (in days) applied to statement dates before merging
# them onto the daily price series, approximating the real-world delay
# between a fiscal period ending and the filing becoming public. yfinance
# does not expose true 10-K/10-Q filing dates -- only period-end dates --
# so this is a fixed proxy, not an exact fix for look-ahead bias. Applied
# to revenue, debt, cash, and book-value historical series alike.
REPORTING_LAG_DAYS = 45


def resolve_sector(info):
    """
    Resolves Yahoo Finance sector/industry into a Sovereign sector bucket.
    Industry is checked first because it is often more specific than sector.
    """
    sector = str(info.get("sector", "") or "").upper()
    industry = str(info.get("industry", "") or "").upper()

    # Industry-level overrides first
    if "SOFTWARE" in industry:
        return "SOFTWARE"

    if "SEMICONDUCTOR" in industry:
        return "SEMICONDUCTORS"

    if "BANK" in industry:
        return "FINANCIAL SERVICES"

    if "INSURANCE" in industry:
        return "FINANCIAL SERVICES"

    if "REIT" in industry or "REAL ESTATE" in industry:
        return "REAL ESTATE"

    if "ROYALTY" in industry or "STREAMING" in industry:
        return "ROYALTY"

    if "GOLD" in industry or "PRECIOUS METALS" in industry:
        return "BASIC MATERIALS"

    if "OIL" in industry or "GAS" in industry or "ENERGY" in industry:
        return "ENERGY"

    # Sector-level fallback
    if "TECHNOLOGY" in sector or "INFORMATION" in sector:
        return "INFORMATION TECHNOLOGY"

    if "COMMUNICATION" in sector:
        return "COMMUNICATION SERVICES"

    if "INDUSTRIAL" in sector:
        return "INDUSTRIAL"

    if "ENERGY" in sector:
        return "ENERGY"

    if "MATERIAL" in sector:
        return "BASIC MATERIALS"

    if "UTILIT" in sector:
        return "UTILITIES"

    if "FINANCIAL" in sector:
        return "FINANCIAL SERVICES"

    if "REAL ESTATE" in sector:
        return "REAL ESTATE"

    if sector:
        return sector

    return "INFORMATION TECHNOLOGY"


def determine_valuation_model(ticker, info):
    """
    Determines which valuation multiple should be used for this ticker.

    Returns:
        sector, valuation_model
    """
    ticker = str(ticker).upper()

    # Manual override has highest priority
    if ticker in TICKER_MODEL_OVERRIDES:
        return "MANUAL OVERRIDE", TICKER_MODEL_OVERRIDES[ticker]

    # Special royalty/streaming/land override
    if ticker in SPECIAL_VALUATION_MODELS:
        return "ROYALTY OVERRIDE", SPECIAL_VALUATION_MODELS[ticker]

    sector = resolve_sector(info)

    valuation_model = VALUATION_MODELS.get(sector, "PS")

    return sector, valuation_model


# ----------------------------------------------------------------------
# Small numeric / statement helpers
# ----------------------------------------------------------------------

def _is_valid_number(x):
    try:
        return x is not None and not pd.isna(x) and np.isfinite(float(x))
    except Exception:
        return False


def _finite_positive(x):
    try:
        return x is not None and not pd.isna(x) and np.isfinite(float(x)) and float(x) > 0
    except Exception:
        return False


def _safe_get_df(stock, attr_name):
    """
    Safely extracts a DataFrame from volatile yfinance endpoints.
    """
    try:
        attr = getattr(stock, attr_name)
        result = attr() if callable(attr) else attr
        if isinstance(result, pd.DataFrame):
            return result
    except Exception:
        pass

    return pd.DataFrame()


def _first_present(df, candidates):
    """
    Returns the first row label from candidates that exists in df.index.
    """
    if df is None or df.empty:
        return None

    for label in candidates:
        if label in df.index:
            return label

    return None


def _latest_value(df, row_label):
    """
    Returns the most recent non-NaN value for a statement row.
    """
    if df is None or df.empty or row_label is None or row_label not in df.index:
        return np.nan

    row = df.loc[row_label].dropna()

    if row.empty:
        return np.nan

    try:
        return float(row.iloc[0])
    except Exception:
        return np.nan


def _latest_from_candidates(df, candidates):
    """
    Finds the first available row label and returns its latest value.
    """
    label = _first_present(df, candidates)

    if label is None:
        return np.nan

    return _latest_value(df, label)


def _row_from_candidates(df, candidates):
    """
    Returns the full reported row (most-recent-first, NaNs dropped) for the
    first candidate row label found in df.index.
    """
    label = _first_present(df, candidates)

    if label is None:
        return pd.Series(dtype=float)

    row = df.loc[label].dropna()

    if row.empty:
        return pd.Series(dtype=float)

    return row.sort_index(ascending=False)


def _latest_positive_from_candidates(df, candidates, fx_series, max_periods=4):
    """
    Scans the most recent `max_periods` reported values (most recent first)
    of the first matching candidate row, and returns the first one that is
    finite and positive after FX conversion.

    A single unprofitable / break-even reporting period should not, on its
    own, disqualify a company from an EV-multiple valuation if it was
    profitable within the recent lookback window. `max_periods` bounds how
    far back we're willing to reach so a company that hasn't been
    profitable in years doesn't get a multiple built on stale numbers.

    Returns:
        (value, periods_back) where periods_back is 0 for the latest
        reported period, 1 for one period prior, etc. Returns
        (np.nan, None) if nothing usable was found in the window.
    """
    row = _row_from_candidates(df, candidates)

    if row.empty:
        return np.nan, None

    for periods_back, raw_value in enumerate(row.iloc[:max_periods]):
        value = _convert_statement_value(raw_value, fx_series)

        if _finite_positive(value):
            return value, periods_back

    return np.nan, None


def _robust_annual_positive(df, candidates, fx_series, max_periods=4, robustness_window=3):
    """
    A stricter variant of _latest_positive_from_candidates(): if the
    latest reported period is itself positive, it's accepted immediately
    (the common, healthy case). But if we have to reach further back
    because the latest period was negative/missing, we additionally
    require that a *majority* of the most recent `robustness_window`
    periods were positive before accepting an older value.

    This guards against anchoring an EV multiple on a single old
    profitable year sandwiched between multiple loss-making years (e.g.
    2026: -100M, 2025: -20M, 2024: +500M) -- which would otherwise make a
    structurally impaired business look artificially cheap on EV/EBIT or
    EV/EBITDA. In that scenario, this returns (nan, None), so the caller
    falls through to a P/S fallback instead.

    Returns:
        (value, periods_back) or (np.nan, None) if the robustness bar
        isn't met.
    """
    row = _row_from_candidates(df, candidates)

    if row.empty:
        return np.nan, None

    window_vals = [_convert_statement_value(v, fx_series) for v in row.iloc[:max_periods]]

    if not window_vals:
        return np.nan, None

    if _finite_positive(window_vals[0]):
        return window_vals[0], 0

    robustness_vals = window_vals[:robustness_window]
    positive_in_window = sum(1 for v in robustness_vals if _finite_positive(v))
    required = (len(robustness_vals) // 2) + 1

    if positive_in_window < required:
        return np.nan, None

    for periods_back, value in enumerate(window_vals):
        if _finite_positive(value):
            return value, periods_back

    return np.nan, None


# ----------------------------------------------------------------------
# FX helpers
# ----------------------------------------------------------------------

def _build_fx_series(price_currency, financial_currency, years):
    """
    Builds FX conversion series when financial statements are reported
    in a currency different from the trading currency.

    Uses the same convention as the original engine:

        fx_symbol = f"{price_currency}{financial_currency}=X"

    Statement values are divided by the FX rate.
    """
    if not financial_currency or not price_currency or financial_currency == price_currency:
        return None, None, None

    fx_symbol = f"{price_currency}{financial_currency}=X"

    try:
        fx_hist = yf.Ticker(fx_symbol).history(period=f"{years}y", interval="1d")["Close"]
    except Exception:
        fx_hist = pd.Series(dtype=float)

    if fx_hist is None or fx_hist.empty:
        fx_note = (
            f"⚠️ Currency mismatch tracked ({financial_currency} vs {price_currency}). "
            f"Cross currency conversion array [{fx_symbol}] failed loading."
        )
        return fx_symbol, None, fx_note

    fx_hist.index = pd.to_datetime(fx_hist.index)

    if fx_hist.index.tz is not None:
        fx_hist.index = fx_hist.index.tz_localize(None)

    fx_series = fx_hist.sort_index().rename("FX_Rate").to_frame()

    fx_note = (
        f"Converted reporting financial currency from {financial_currency} "
        f"into transactional pricing units ({price_currency}) using {fx_symbol}; "
        f"statement values divided by the historical FX rate series."
    )

    return fx_symbol, fx_series, fx_note


def _apply_fx_normalization(series, fx_series):
    """
    Converts a historical statement series into pricing currency.
    Used primarily for revenue in the P/S model.
    """
    if fx_series is None or series.empty:
        return series

    idx = pd.to_datetime(series.index)

    if idx.tz is not None:
        idx = idx.tz_localize(None)

    df_ = series.copy()
    df_.index = idx
    df_ = df_.sort_index().rename("Revenue_Raw").to_frame()

    df_ = pd.merge_asof(
        df_,
        fx_series,
        left_index=True,
        right_index=True,
        direction="backward"
    )

    df_["FX_Rate"] = df_["FX_Rate"].bfill()

    if df_["FX_Rate"].isna().all():
        return series

    return df_["Revenue_Raw"] / df_["FX_Rate"]


def _convert_statement_value(value, fx_series):
    """
    Converts a single latest statement value into pricing currency.
    Used for EBITDA, EBIT, book value, FFO, debt, and cash.
    """
    if not _is_valid_number(value):
        return np.nan

    if fx_series is None:
        return float(value)

    rate = fx_series["FX_Rate"].dropna()

    if rate.empty:
        return np.nan

    return float(value) / float(rate.iloc[-1])


# ----------------------------------------------------------------------
# Historical (point-in-time) statement series builders
#
# EV-based and P/B models originally divided a fully time-varying
# Market_Cap series by a single scalar "latest" debt/cash/book-value
# figure -- meaning a 2019 EV or P/B ratio was silently built using
# 2026-era balance sheet data. The helpers below build genuinely
# historical, FX-date-aligned series for these balance-sheet items
# instead, the same way _build_revenue_ttm() already does for revenue.
# ----------------------------------------------------------------------

def _row_history(df, candidates, fx_series):
    """
    Returns an FX-converted, date-indexed (ascending) Series for the first
    matching candidate row in a statement dataframe (columns are report
    dates). Returns an empty Series if nothing is found.
    """
    label = _first_present(df, candidates)

    if label is None:
        return pd.Series(dtype=float)

    row = df.loc[label].dropna()

    if row.empty:
        return pd.Series(dtype=float)

    row.index = pd.to_datetime(row.index)
    row = row.sort_index()

    return _apply_fx_normalization(row, fx_series)


def _build_point_in_time_history(quarterly_df, annual_df, candidates, fx_series):
    """
    Builds a historical, FX-converted point-in-time series for a
    balance-sheet-style (stock, not flow) statement line -- e.g. debt,
    cash, or shareholder equity -- by combining quarterly and annual
    statements. Where both report the same date, the quarterly figure
    wins (more granular). Returns an empty Series if nothing is found.
    """
    a_hist = _row_history(annual_df, candidates, fx_series)
    q_hist = _row_history(quarterly_df, candidates, fx_series)

    if q_hist.empty and a_hist.empty:
        return pd.Series(dtype=float)

    combined = pd.concat([a_hist, q_hist])
    combined = combined[~combined.index.duplicated(keep="last")]

    return combined.sort_index()


def _build_debt_history(quarterly_balance, annual_balance, fx_series):
    """
    Builds a historical Total Debt series, falling back to
    (Long Term Debt + Current Debt) per reported period when a combined
    "Total Debt" row isn't available for a given statement source.
    """
    total = _build_point_in_time_history(
        quarterly_balance, annual_balance, ["Total Debt", "TotalDebt"], fx_series
    )

    if not total.empty:
        return total

    long_term = _build_point_in_time_history(
        quarterly_balance, annual_balance, ["Long Term Debt", "LongTermDebt"], fx_series
    )
    current = _build_point_in_time_history(
        quarterly_balance, annual_balance,
        ["Current Debt", "CurrentDebt", "Short Long Term Debt"], fx_series
    )

    if long_term.empty and current.empty:
        return pd.Series(dtype=float)

    combined_index = long_term.index.union(current.index)
    long_term = long_term.reindex(combined_index).fillna(0.0)
    current = current.reindex(combined_index).fillna(0.0)

    return (long_term + current).sort_index()


def _merge_point_in_time_onto_daily(df_daily, history_series, column_name, lag_days):
    """
    Merges a point-in-time historical statement series onto the daily
    price/market-cap frame via merge_asof(direction="backward"), after
    shifting the statement dates forward by `lag_days`.

    The shift approximates the real-world delay between a fiscal period
    ending and the filing actually becoming public (10-K/10-Q lag).
    yfinance only exposes period-end dates, not true filing dates, so this
    is a heuristic buffer rather than an exact fix for look-ahead bias --
    it stops a Dec-31 balance sheet from being treated as known information
    on Jan 1, but it is not a substitute for real filing-date data.

    Dates earlier than the first available (lagged) statement date will
    have NaN in `column_name` and should be filled by the caller (e.g.
    with the earliest known snapshot, or the latest, per the caller's
    judgment on how to handle pre-history dates).
    """
    if history_series is None or history_series.empty:
        df_daily[column_name] = np.nan
        return df_daily

    hist_df = history_series.rename(column_name).to_frame()
    hist_df.index = pd.to_datetime(hist_df.index)

    if hist_df.index.tz is not None:
        hist_df.index = hist_df.index.tz_localize(None)

    hist_df.index = hist_df.index + pd.Timedelta(days=lag_days)
    hist_df = hist_df.sort_index()

    df_daily = pd.merge_asof(
        df_daily.sort_index(),
        hist_df,
        left_index=True,
        right_index=True,
        direction="backward"
    )

    # Dates before the very first available (lagged) statement date have no
    # "backward" match and come back NaN. Fill those leading dates with the
    # EARLIEST known historical value (bfill), not the latest company-wide
    # figure -- filling with "latest" would reintroduce the exact static-
    # snapshot contamination this function exists to fix, just confined to
    # the pre-history tail instead of the whole series.
    df_daily[column_name] = df_daily[column_name].bfill()

    return df_daily


# ----------------------------------------------------------------------
# Revenue builder for P/S model
# ----------------------------------------------------------------------

def _find_revenue_row(fin_df):
    if fin_df is None or fin_df.empty:
        return None

    for candidate in ["Total Revenue", "TotalRevenue", "Revenue"]:
        if candidate in fin_df.index:
            return candidate

    return None


def _classify_frequency(series):
    if len(series) < 2:
        return None, None

    gaps_days = series.sort_index().index.to_series().diff().dt.days.dropna()

    if gaps_days.empty:
        return None, None

    median_gap = gaps_days.median()

    if median_gap <= 130:
        return "quarterly", 4
    elif median_gap <= 250:
        return "semi-annual", 2
    else:
        return "annual", 1


def _build_revenue_ttm(quarterly, annual, fx_series):
    """
    Builds Revenue_TTM series for the P/S valuation model.

    Returns:
        df_rev, report_freq, error
    """
    q_row = _find_revenue_row(quarterly)
    rev_q = quarterly.loc[q_row].dropna() if (q_row is not None and not quarterly.empty) else pd.Series(dtype=float)
    rev_q = _apply_fx_normalization(rev_q, fx_series)

    q_freq, q_window = _classify_frequency(rev_q)

    df_rev_q = pd.DataFrame()

    if q_freq and len(rev_q) >= q_window:
        df_rev_q = pd.DataFrame(rev_q).sort_index()
        df_rev_q.columns = ["Revenue_Period"]
        df_rev_q["Revenue_TTM"] = df_rev_q["Revenue_Period"].rolling(window=q_window).sum()
        df_rev_q = df_rev_q.dropna()

    a_row = _find_revenue_row(annual)
    rev_a = annual.loc[a_row].dropna() if (a_row is not None and not annual.empty) else pd.Series(dtype=float)
    rev_a = _apply_fx_normalization(rev_a, fx_series)

    df_rev_a = pd.DataFrame()

    if len(rev_a) >= 1:
        df_rev_a = pd.DataFrame(rev_a).sort_index()
        df_rev_a.columns = ["Revenue_Period"]
        df_rev_a["Revenue_TTM"] = df_rev_a["Revenue_Period"]
        df_rev_a = df_rev_a.dropna()

    if df_rev_q.empty and df_rev_a.empty:
        return None, None, "Corporate revenue matrix logs completely empty across known filing timelines."

    elif not df_rev_q.empty and not df_rev_a.empty:
        q_start = df_rev_q.index.min()
        older_annual = df_rev_a[df_rev_a.index < q_start]

        if not older_annual.empty:
            df_rev = pd.concat([
                older_annual[["Revenue_TTM"]],
                df_rev_q[["Revenue_TTM"]]
            ]).sort_index()

            report_freq = f"{q_freq} (extended using historical annual data components)"
        else:
            df_rev = df_rev_q[["Revenue_TTM"]]
            report_freq = q_freq

    elif not df_rev_q.empty:
        df_rev = df_rev_q[["Revenue_TTM"]]
        report_freq = q_freq

    else:
        df_rev = df_rev_a[["Revenue_TTM"]]
        report_freq = "annual"

    return df_rev, report_freq, None


def _build_flow_ttm(quarterly, annual, candidates, fx_series):
    """
    Generic version of _build_revenue_ttm() for any income-statement flow
    item (EBIT, EBITDA, etc.): builds a rolling trailing-twelve-month sum
    from quarterly data when available, falling back to the latest annual
    figure otherwise.

    Used to prefer a genuine TTM EBIT/EBITDA anchor over a stale annual
    "latest reported year" figure, since TTM reflects the most recent four
    reported quarters rather than a full fiscal year that may already be
    9-12 months stale.

    Returns:
        latest TTM (or annual) value, or np.nan if nothing usable was found.
    """
    q_row = _first_present(quarterly, candidates)
    flow_q = quarterly.loc[q_row].dropna() if (q_row is not None and not quarterly.empty) else pd.Series(dtype=float)
    flow_q = _apply_fx_normalization(flow_q, fx_series)

    q_freq, q_window = _classify_frequency(flow_q)

    if q_freq and len(flow_q) >= q_window:
        df_q = pd.DataFrame(flow_q).sort_index()
        df_q.columns = ["Period_Value"]
        df_q["TTM_Value"] = df_q["Period_Value"].rolling(window=q_window).sum()
        df_q = df_q.dropna()

        if not df_q.empty:
            return float(df_q["TTM_Value"].iloc[-1])

    a_row = _first_present(annual, candidates)
    flow_a = annual.loc[a_row].dropna() if (a_row is not None and not annual.empty) else pd.Series(dtype=float)
    flow_a = _apply_fx_normalization(flow_a, fx_series)

    if not flow_a.empty:
        return float(flow_a.sort_index().iloc[-1])

    return np.nan


def _build_ps_valuation(df_daily, quarterly, income, fx_series):
    """
    Builds a Market_Cap / Revenue_TTM Valuation_Ratio column onto df_daily.

    Factored out of the main pipeline so it can be reused both as the
    primary model for P/S sectors and as a fallback for EV/EBIT and
    EV/EBITDA sectors when no usable positive EBIT/EBITDA anchor exists.

    Returns:
        df_daily, report_freq, error
    """
    df_rev, report_freq, revenue_error = _build_revenue_ttm(
        quarterly=quarterly,
        annual=income,
        fx_series=fx_series
    )

    if revenue_error:
        return None, None, revenue_error

    df_rev_sorted = df_rev[["Revenue_TTM"]].copy()
    df_rev_sorted.index = pd.to_datetime(df_rev_sorted.index)

    if df_rev_sorted.index.tz is not None:
        df_rev_sorted.index = df_rev_sorted.index.tz_localize(None)

    # Shift the reporting date forward to approximate filing-date lag --
    # otherwise a Dec-31 TTM figure is treated as known to the market on
    # Jan 1, which is look-ahead bias relative to real-world filing delays.
    df_rev_sorted.index = df_rev_sorted.index + pd.Timedelta(days=REPORTING_LAG_DAYS)

    df_daily = pd.merge_asof(
        df_daily.sort_index(),
        df_rev_sorted.sort_index(),
        left_index=True,
        right_index=True,
        direction="backward"
    )

    df_daily = df_daily.dropna(subset=["Revenue_TTM", "Market_Cap"])
    df_daily = df_daily[df_daily["Revenue_TTM"] > 0]

    if df_daily.empty:
        return (
            None,
            None,
            "No valid tracking frames remain after performing trailing corporate revenue "
            "and capitalization data filters."
        )

    df_daily["Valuation_Ratio"] = df_daily["Market_Cap"] / df_daily["Revenue_TTM"]

    return df_daily, report_freq, None


# ----------------------------------------------------------------------
# Fundamental builder for EV/EBITDA, EV/EBIT, P/B, and P/FFO
# ----------------------------------------------------------------------

def _get_fundamentals(income, balance, cashflow, fx_series, quarterly=None, lookback_periods=4):
    """
    Extracts fundamental anchors required for non-P/S models.

    For EBIT and EBITDA, the priority order is:
        1. TTM (trailing twelve months from quarterly data), if positive --
           the freshest possible anchor.
        2. The latest annual period, if positive.
        3. An earlier annual period within `lookback_periods`, but only if
           a majority of the most recent periods examined were themselves
           positive (see _robust_annual_positive() docstring) -- this
           guards against anchoring on a single old profitable year
           sandwiched between loss-making years.

    Returns:
        dict containing:
            ebit, ebit_periods_back, ebit_source
            ebitda, ebitda_periods_back, ebitda_source
            ffo
            total_debt
            cash
            equity

    `*_periods_back` is 0 if the latest/TTM period was usable as-is, a
    positive integer if an earlier annual period had to be used instead,
    and None if no usable value was found anywhere in the lookback window.
    `*_source` is "ttm", "annual", or None.
    """
    quarterly = quarterly if quarterly is not None else pd.DataFrame()

    ebit_candidates = ["EBIT", "Operating Income", "OperatingIncome"]
    ebitda_candidates = ["EBITDA"]

    # EBIT -- prefer TTM, then latest/robust-lagged annual
    ttm_ebit = _build_flow_ttm(quarterly, income, ebit_candidates, fx_series)

    if _finite_positive(ttm_ebit):
        ebit, ebit_periods_back, ebit_source = ttm_ebit, 0, "ttm"
    else:
        ebit, ebit_periods_back = _robust_annual_positive(
            income, ebit_candidates, fx_series, max_periods=lookback_periods
        )
        ebit_source = "annual" if _finite_positive(ebit) else None

    # EBITDA -- prefer TTM from a directly reported EBITDA line, then
    # latest/robust-lagged annual EBITDA, then derive from EBIT + D&A.
    ttm_ebitda = _build_flow_ttm(quarterly, income, ebitda_candidates, fx_series)

    if _finite_positive(ttm_ebitda):
        ebitda, ebitda_periods_back, ebitda_source = ttm_ebitda, 0, "ttm"
    else:
        ebitda, ebitda_periods_back = _robust_annual_positive(
            income, ebitda_candidates, fx_series, max_periods=lookback_periods
        )
        ebitda_source = "annual" if _finite_positive(ebitda) else None

    if not _finite_positive(ebitda):
        # No directly reported EBITDA row was usable within the window.
        # Fall back to (latest EBIT + latest D&A). This only uses the
        # latest period of each component, since reliably aligning older
        # EBIT and D&A periods across two separate statements isn't
        # guaranteed by yfinance's schemas.
        latest_ebit_raw = _latest_from_candidates(income, ebit_candidates)
        latest_ebit = _convert_statement_value(latest_ebit_raw, fx_series)

        depreciation_raw = _latest_from_candidates(
            cashflow,
            [
                "Depreciation And Amortization",
                "DepreciationAndAmortization",
                "Depreciation"
            ]
        )
        depreciation = _convert_statement_value(depreciation_raw, fx_series)

        if _is_valid_number(latest_ebit) and _is_valid_number(depreciation):
            derived_ebitda = latest_ebit + depreciation

            if _finite_positive(derived_ebitda):
                ebitda = derived_ebitda
                ebitda_periods_back = 0
                ebitda_source = "annual"

    # FFO -- not always available in yfinance, but try anyway
    ffo_raw = _latest_from_candidates(
        income,
        [
            "Funds From Operations",
            "FFO"
        ]
    )
    ffo = _convert_statement_value(ffo_raw, fx_series)

    # Total debt
    total_debt_raw = _latest_from_candidates(
        balance,
        [
            "Total Debt",
            "TotalDebt"
        ]
    )

    total_debt = _convert_statement_value(total_debt_raw, fx_series)

    if not _is_valid_number(total_debt):
        long_term_debt = _convert_statement_value(
            _latest_from_candidates(
                balance,
                [
                    "Long Term Debt",
                    "LongTermDebt"
                ]
            ),
            fx_series
        )

        current_debt = _convert_statement_value(
            _latest_from_candidates(
                balance,
                [
                    "Current Debt",
                    "CurrentDebt",
                    "Short Long Term Debt"
                ]
            ),
            fx_series
        )

        if _is_valid_number(long_term_debt) or _is_valid_number(current_debt):
            total_debt = float(np.nansum([
                long_term_debt if _is_valid_number(long_term_debt) else 0.0,
                current_debt if _is_valid_number(current_debt) else 0.0
            ]))
        else:
            total_debt = np.nan

    # Cash
    cash_raw = _latest_from_candidates(
        balance,
        [
            "Cash And Cash Equivalents",
            "CashAndCashEquivalents",
            "Cash Cash Equivalents And Short Term Investments"
        ]
    )
    cash = _convert_statement_value(cash_raw, fx_series)

    # Book value
    equity_raw = _latest_from_candidates(
        balance,
        [
            "Stockholders Equity",
            "Total Stockholder Equity",
            "Common Stock Equity"
        ]
    )
    equity = _convert_statement_value(equity_raw, fx_series)

    return {
        "ebit": ebit,
        "ebit_periods_back": ebit_periods_back,
        "ebit_source": ebit_source,
        "ebitda": ebitda,
        "ebitda_periods_back": ebitda_periods_back,
        "ebitda_source": ebitda_source,
        "ffo": ffo,
        "total_debt": total_debt,
        "cash": cash,
        "equity": equity,
    }


# ----------------------------------------------------------------------
# Existing valuation engine scoring functions
# These remain unchanged conceptually.
# ----------------------------------------------------------------------

def calculate_data_quality(df, report_freq, fx_note):
    """
    Evaluates raw historical observation thickness and corporate report
    frequency data health.
    """
    obs = len(df)

    if obs >= 1000:
        obs_score = "Strong Sample Thickness"
    elif obs >= 500:
        obs_score = "Moderate Sample Thickness"
    else:
        obs_score = "Thin Data Matrix"

    fx_flag = "FX Spliced & Denominated" if fx_note else "Native Currency Base"

    if "annual" in str(report_freq).lower():
        statement_quality = "Low-Frequency (Trailing Annual)"
    elif "quarterly" in str(report_freq).lower():
        statement_quality = "High-Frequency (Trailing Quarterly TTM)"
    else:
        statement_quality = "Undefined Reporting Interval"

    return f"{obs_score} ({obs} periods) | {statement_quality} | {fx_flag}"


def classify_action(multiplier):
    """
    Maps model deployment intensity into an operational capital-allocation posture.
    """
    if multiplier is None or pd.isna(multiplier):
        return "⚪ Unavailable"

    if multiplier == 0:
        return "🛑 Pause Fresh Deployment"
    elif multiplier < 0.25:
        return "🔬 Micro-Accumulation Mode"
    elif multiplier < 0.75:
        return "📉 Throttled Accumulation Mode"
    elif multiplier < 1.25:
        return "⚖️ Standard Allocation Mode"
    else:
        return "⚡ Accelerated Opportunity Mode"


def style_batch_status(val):
    """
    Applies unified color-coding matrices to the batch portfolio dashboard dataframe.
    """
    val = str(val)

    if "Value" in val:
        return "background-color: #065f46; color: white;"

    if "Scarcity" in val:
        return "background-color: #1d4ed8; color: white;"

    if "High-Expectation" in val or "Premium" in val:
        return "background-color: #ca8a04; color: black;"

    if "Halt" in val:
        return "background-color: #991b1b; color: white;"

    if "Normal" in val:
        return "background-color: #1e293b; color: #cbd5e1;"

    return ""


def _winsorize(series, lower_pct=0.01, upper_pct=0.99):
    """
    Clips a series to its [lower_pct, upper_pct] quantile range.

    A single bad or misreported data point (e.g. Yahoo briefly reporting
    Revenue=1 for a quarter, sending P/S to 40,000x) can otherwise distort
    percentile rank, skewness, and Z-score calculations for the entire
    historical distribution, not just the affected date.
    """
    if series.empty:
        return series

    lower = series.quantile(lower_pct)
    upper = series.quantile(upper_pct)

    return series.clip(lower=lower, upper=upper)


def calculate_distribution_diagnostics(series, current_val):
    """
    Calculates distributional asymmetry and exact percentile rank location
    inside asset history.
    """
    clean = series.replace([np.inf, -np.inf], np.nan).dropna()

    if len(clean) < 30:
        return {"skewness": 0.0, "percentile": 50.0, "shape": "Insufficient Data Pool"}

    clean = _winsorize(clean)

    skewness = clean.skew()
    percentile = (clean <= current_val).mean() * 100

    if abs(skewness) >= 1.0:
        shape = "Highly Skewed / Fat-Tailed"
    elif abs(skewness) >= 0.5:
        shape = "Moderately Skewed Profile"
    else:
        shape = "Symmetric Distribution"

    return {"skewness": skewness, "percentile": percentile, "shape": shape}


def calculate_robust_z_score(series, current_val):
    """
    Calculates Median Absolute Deviation (MAD) anchored robust Z-score.
    """
    clean = series.replace([np.inf, -np.inf], np.nan).dropna()

    if len(clean) < 30:
        return 0.0, np.nan, np.nan

    clean = _winsorize(clean)

    median_val = clean.median()
    mad = np.median(np.abs(clean - median_val))

    if mad == 0 or np.isnan(mad):
        return 0.0, median_val, mad

    robust_z = 0.6745 * (current_val - median_val) / mad

    return robust_z, median_val, mad


def sovereign_allocation_engine(
    ticker,
    is_core,
    z_score,
    robust_z_score,
    z_threshold,
    percentile,
    skewness,
    macro_mode,
    floors
):
    """
    Regime-aware multi-dimensional systemic engine. Cross-validates standard
    parameters against robust metrics, percentile limits, and global liquidity
    environments.
    """
    macro_crunch = "Crunch" in macro_mode
    macro_transition = "Transition" in macro_mode

    if abs(skewness) >= 1.0:
        distribution_reliability = "Low (Fat Tails Active)"
    elif abs(skewness) >= 0.5:
        distribution_reliability = "Medium (Standard Skew)"
    else:
        distribution_reliability = "High (Normalized Curve)"

    pressure_sources = []

    if z_score >= z_threshold:
        pressure_sources.append(f"Standard Z-Score ({z_score:.2f})")

    if robust_z_score >= z_threshold:
        pressure_sources.append(f"Robust Z-Score ({robust_z_score:.2f})")

    if percentile >= 95:
        pressure_sources.append(f"Extreme Percentile Breach ({percentile:.1f}%)")

    valuation_pressure = len(pressure_sources) > 0
    pressure_text = ", ".join(pressure_sources) if valuation_pressure else "No extreme expansion alerts"

    value_sources = []

    if z_score <= -z_threshold:
        value_sources.append(f"Standard Z-Score ({z_score:.2f})")

    if robust_z_score <= -z_threshold:
        value_sources.append(f"Robust Z-Score ({robust_z_score:.2f})")

    if percentile <= 10:
        value_sources.append(f"10th Percentile Floor ({percentile:.1f}%)")

    deep_value_pressure = len(value_sources) > 0
    value_text = ", ".join(value_sources) if deep_value_pressure else "No core discount metrics"

    premium_pressure = (
        (1.0 <= z_score < z_threshold) or
        (1.0 <= robust_z_score < z_threshold) or
        (80 <= percentile < 95)
    )

    if deep_value_pressure:
        status_stance = "💎 Value Zone"

        if macro_crunch:
            allocation_multiplier = max(floors['crunch'], 0.50) if is_core else 0.25
            explanation = (
                f"Valuation severely discounted via [{value_text}]. Compelling micro metrics "
                f"confront high macro system stress. Strategic core floor modulated to protect capital."
            )
        elif macro_transition:
            allocation_multiplier = 1.25 if is_core else 0.75
            explanation = (
                f"Valuation optimization confirmed via [{value_text}] during transition liquidity "
                f"tracking. Steady, disciplined pacing active."
            )
        else:
            allocation_multiplier = 1.50 if is_core else 1.00
            explanation = (
                f"Deep value terrain established via [{value_text}] alongside healthy expansionary "
                f"macro liquidity frameworks. Core model pacing increases within configured risk bounds."
            )

        return status_stance, allocation_multiplier, explanation, distribution_reliability

    if valuation_pressure:
        if is_core:
            if percentile >= 95:
                status_stance = "🔵 Core Scarcity Premium"
                explanation = (
                    f"Asset is extended versus realised valuation history. Trigger source: "
                    f"[{pressure_text}]. Core floor rules preserve exposure-building bounds to "
                    f"lock in multi-year position compounding."
                )
            else:
                status_stance = "🟠 Core High-Expectation Zone"
                explanation = (
                    f"Significant valuation pressure tracking via [{pressure_text}]. Portfolio "
                    f"defense limits velocity; core allocation scaled down to minimum protective floors."
                )

            if macro_crunch:
                allocation_multiplier = floors['crunch']
            elif macro_transition:
                allocation_multiplier = floors['transition']
            else:
                allocation_multiplier = floors['expansion']
        else:
            status_stance = "🔴 Tactical Valuation Halt"
            allocation_multiplier = 0.00
            explanation = (
                f"Asset lacks structural Sovereign Core classification. High multiple friction "
                f"across checks [{pressure_text}] commands a tactical deployment pause."
            )

        return status_stance, allocation_multiplier, explanation, distribution_reliability

    if premium_pressure:
        if is_core:
            status_stance = "🟡 Core Premium Accumulation"

            if macro_crunch:
                allocation_multiplier = 0.15
            elif macro_transition:
                allocation_multiplier = 0.40
            else:
                allocation_multiplier = 0.60

            explanation = (
                "Core asset trades within standard premium tolerances. "
                "Pacing adjusted down using macro landscape boundaries."
            )
        else:
            status_stance = "🟡 Tactical Premium Zone"

            if macro_crunch:
                allocation_multiplier = 0.00
            elif macro_transition:
                allocation_multiplier = 0.25
            else:
                allocation_multiplier = 0.50

            explanation = (
                "Tactical asset valuation floats above historical equilibrium baselines. "
                "Deployment throttled to preserve liquidity optionality."
            )

        return status_stance, allocation_multiplier, explanation, distribution_reliability

    status_stance = "✅ Normal Range"

    if macro_crunch:
        allocation_multiplier = 0.25 if is_core else 0.00
        explanation = (
            "Asset valuation metrics reflect normal baselines, but the macro liquidity landscape "
            "is defensive. Non-core tactical operations are paused."
        )
    elif macro_transition:
        allocation_multiplier = 0.50 if is_core else 0.35
        explanation = (
            "Equilibrium asset pricing detected under structural transitional matrix constraints. "
            "Model pacing remains measured and controlled."
        )
    else:
        allocation_multiplier = 1.00 if is_core else 0.75
        explanation = (
            "Standard normalized historical pricing interacting with expansionary liquidity states. "
            "Baseline model pacing is active."
        )

    return status_stance, allocation_multiplier, explanation, distribution_reliability


# ----------------------------------------------------------------------
# Core v4.2 data pipeline
# ----------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def get_hardened_valuation_data_v2(ticker, years):
    """
    Sovereign Valuation Engine v4.2 data pipeline.

    Builds a sector-appropriate Valuation_Ratio series.

    Returns:
        df_daily,
        error,
        report_freq,
        fx_note,
        sector,
        valuation_model
    """
    sector = "UNKNOWN"
    valuation_model = "UNKNOWN"
    data_quality_notes = []

    try:
        stock = yf.Ticker(ticker)

        try:
            info = stock.info or {}
        except Exception:
            info = {}

        sector, requested_model = determine_valuation_model(ticker, info)
        valuation_model = requested_model

        # ------------------------------------------------------------------
        # Price history
        # ------------------------------------------------------------------
        try:
            history = stock.history(period=f"{years}y", interval="1d")
        except Exception:
            history = pd.DataFrame()

        if history.empty or "Close" not in history.columns:
            return (
                None,
                "No historical time series asset data could be parsed from API sources.",
                None,
                None,
                sector,
                valuation_model
            )

        df_daily = pd.DataFrame(history["Close"]).copy()
        df_daily.index = pd.to_datetime(df_daily.index)

        if df_daily.index.tz is not None:
            df_daily.index = df_daily.index.tz_localize(None)

        # ------------------------------------------------------------------
        # Shares outstanding
        # ------------------------------------------------------------------
        try:
            shares = stock.get_shares_full(
                start=pd.Timestamp.now() - pd.Timedelta(days=years * 365)
            )
        except Exception:
            shares = pd.Series(dtype=float)

        if not shares.empty:
            shares_series = shares.sort_index()
            shares_series.index = pd.to_datetime(shares_series.index)

            if shares_series.index.tz is not None:
                shares_series.index = shares_series.index.tz_localize(None)

            df_daily = pd.merge_asof(
                df_daily.sort_index(),
                shares_series.rename("Shares").to_frame().sort_index(),
                left_index=True,
                right_index=True,
                direction="backward"
            )

            fallback_shares = info.get("sharesOutstanding")

            if not _is_valid_number(fallback_shares):
                fallback_shares = info.get("impliedSharesOutstanding")

            df_daily["Shares"] = df_daily["Shares"].fillna(fallback_shares)

            # If the returned share history doesn't actually span most of
            # the requested window, dates before it effectively get today's
            # constant share count via the fillna above -- misleading for
            # companies with heavy buybacks/issuance/splits (AMD, TSLA,
            # PLTR, NVDA, banks mid-buyback, etc.).
            history_span_days = (shares_series.index.max() - shares_series.index.min()).days
            requested_span_days = years * 365

            if history_span_days < 0.5 * requested_span_days:
                data_quality_notes.append(
                    "Share-count history only covers "
                    f"{history_span_days} of the requested {requested_span_days} days; earlier "
                    "dates use a constant fallback share count and may understate/overstate "
                    "historical market cap for names with material buybacks, issuance, or splits."
                )
        else:
            fallback_shares = info.get("sharesOutstanding")

            if not _is_valid_number(fallback_shares):
                fallback_shares = info.get("impliedSharesOutstanding")

            df_daily["Shares"] = fallback_shares

            data_quality_notes.append(
                "No historical share-count series was available; a single current share count was "
                "applied across the entire price history, which can distort historical market cap "
                "for names with material buybacks, issuance, or splits."
            )

        # Extra fallback for non-US tickers where .info is sparse but
        # fast_info still contains share data.
        if df_daily["Shares"].isna().all():
            try:
                fast_info = stock.fast_info
                fast_info = dict(fast_info) if not isinstance(fast_info, dict) else fast_info
                fi_shares = fast_info.get("shares")

                if _is_valid_number(fi_shares):
                    df_daily["Shares"] = float(fi_shares)
            except Exception:
                pass

        if df_daily["Shares"].isna().all():
            return (
                None,
                "Systemic failure checking share outstanding matrix. "
                "Cannot build market capitalization maps securely.",
                None,
                None,
                sector,
                valuation_model
            )

        df_daily["Market_Cap"] = df_daily["Close"] * df_daily["Shares"]

        # ------------------------------------------------------------------
        # FX normalization setup
        # ------------------------------------------------------------------
        financial_currency = info.get("financialCurrency")
        price_currency = info.get("currency")

        fx_symbol, fx_series, fx_note = _build_fx_series(
            price_currency=price_currency,
            financial_currency=financial_currency,
            years=years
        )

        fx_required = bool(
            financial_currency
            and price_currency
            and financial_currency != price_currency
        )

        if fx_required and fx_series is None:
            return (
                None,
                f"{ticker}: Reports in {financial_currency} but trades in {price_currency}, and the "
                f"{fx_symbol} FX conversion series could not be loaded. Refusing to compute a valuation "
                f"ratio that would silently divide a {price_currency} market value by unconverted "
                f"{financial_currency} fundamentals.",
                None,
                fx_note,
                sector,
                valuation_model
            )

        # ------------------------------------------------------------------
        # Financial statements
        # ------------------------------------------------------------------
        income = _safe_get_df(stock, "financials")
        quarterly = _safe_get_df(stock, "quarterly_financials")
        balance = _safe_get_df(stock, "balance_sheet")
        quarterly_balance = _safe_get_df(stock, "quarterly_balance_sheet")
        cashflow = _safe_get_df(stock, "cashflow")

        report_freq = None

        # ------------------------------------------------------------------
        # P/S model
        # ------------------------------------------------------------------
        if requested_model == "PS":
            df_daily, report_freq, revenue_error = _build_ps_valuation(
                df_daily=df_daily,
                quarterly=quarterly,
                income=income,
                fx_series=fx_series
            )

            if revenue_error:
                return (
                    None,
                    revenue_error,
                    None,
                    fx_note,
                    sector,
                    valuation_model
                )

        else:
            # --------------------------------------------------------------
            # Non-P/S models require latest fundamental anchors
            # --------------------------------------------------------------
            fundamentals = _get_fundamentals(
                income=income,
                balance=balance,
                cashflow=cashflow,
                fx_series=fx_series,
                quarterly=quarterly,
                lookback_periods=EBIT_EBITDA_LOOKBACK_PERIODS
            )

            built = False

            # --------------------------------------------------------------
            # P/FFO model
            # --------------------------------------------------------------
            if requested_model == "P_FFO":
                if _finite_positive(fundamentals.get("ffo")):
                    df_daily["Valuation_Ratio"] = df_daily["Market_Cap"] / fundamentals["ffo"]
                    valuation_model = "P_FFO"
                    report_freq = "annual (latest FFO anchor)"
                    built = True
                else:
                    # FFO is not reliably available on many free Yahoo
                    # endpoints. P/S is a safer fallback than P/B for REITs
                    # specifically: heavily depreciated property portfolios
                    # with large embedded gains can look "expensive" on P/B
                    # while actually being cheap, whereas revenue is a more
                    # stable reference point for real-asset-heavy REITs.
                    df_daily_ps, report_freq_ps, ps_error = _build_ps_valuation(
                        df_daily=df_daily,
                        quarterly=quarterly,
                        income=income,
                        fx_series=fx_series
                    )

                    if ps_error:
                        return (
                            None,
                            f"{ticker}: P/FFO model requires a positive latest FFO figure, but none "
                            f"was found, and the P/S fallback also failed ({ps_error}).",
                            None,
                            fx_note,
                            sector,
                            valuation_model
                        )

                    df_daily = df_daily_ps
                    report_freq = f"{report_freq_ps} (fallback -- no usable FFO figure)"
                    valuation_model = "PS_FFO_FALLBACK"
                    built = True

            # --------------------------------------------------------------
            # EV/EBITDA
            # --------------------------------------------------------------
            if not built and requested_model == "EV_EBITDA":
                denominator = fundamentals.get("ebitda")
                periods_back = fundamentals.get("ebitda_periods_back")
                anchor_source = fundamentals.get("ebitda_source")

                if not _finite_positive(denominator):
                    # No positive EBITDA anywhere in the lookback window --
                    # fall back to P/S rather than hard-failing outright.
                    df_daily_ps, report_freq_ps, ps_error = _build_ps_valuation(
                        df_daily=df_daily,
                        quarterly=quarterly,
                        income=income,
                        fx_series=fx_series
                    )

                    if ps_error:
                        return (
                            None,
                            f"{ticker}: EV/EBITDA model requires positive EBITDA within the last "
                            f"{EBIT_EBITDA_LOOKBACK_PERIODS} annual reports (or a positive TTM figure), "
                            f"but none was found, and the P/S fallback also failed ({ps_error}).",
                            None,
                            fx_note,
                            sector,
                            valuation_model
                        )

                    df_daily = df_daily_ps
                    report_freq = f"{report_freq_ps} (fallback -- no positive EBITDA in lookback window)"
                    valuation_model = "PS_EBITDA_FALLBACK"
                    built = True
                else:
                    debt_hist = _build_debt_history(quarterly_balance, balance, fx_series)
                    cash_hist = _build_point_in_time_history(
                        quarterly_balance, balance,
                        ["Cash And Cash Equivalents", "CashAndCashEquivalents",
                         "Cash Cash Equivalents And Short Term Investments"],
                        fx_series
                    )

                    history_available = not debt_hist.empty or not cash_hist.empty

                    df_daily = _merge_point_in_time_onto_daily(
                        df_daily, debt_hist, "Debt_Historical", REPORTING_LAG_DAYS
                    )
                    df_daily = _merge_point_in_time_onto_daily(
                        df_daily, cash_hist, "Cash_Historical", REPORTING_LAG_DAYS
                    )

                    latest_debt = float(fundamentals.get("total_debt")) if _is_valid_number(fundamentals.get("total_debt")) else 0.0
                    latest_cash = float(fundamentals.get("cash")) if _is_valid_number(fundamentals.get("cash")) else 0.0

                    # Fallback only for the case where NO historical debt/cash
                    # data was found at all (bfill inside the merge helper
                    # already handles the pre-history tail when at least
                    # some history exists).
                    df_daily["Debt_Historical"] = df_daily["Debt_Historical"].fillna(latest_debt)
                    df_daily["Cash_Historical"] = df_daily["Cash_Historical"].fillna(latest_cash)

                    if not history_available:
                        data_quality_notes.append(
                            "No historical debt/cash time series was available; EV was built using "
                            "a single latest balance-sheet snapshot applied across the full price history."
                        )

                    negative_ev_periods = int(
                        (df_daily["Market_Cap"] + df_daily["Debt_Historical"] - df_daily["Cash_Historical"] <= 0).sum()
                    )

                    if negative_ev_periods > 0:
                        data_quality_notes.append(
                            f"{negative_ev_periods} period(s) had non-positive Enterprise Value (net-cash "
                            f"position exceeding market cap) and were excluded from the EV/EBITDA series."
                        )

                    df_daily["Enterprise_Value"] = df_daily["Market_Cap"] + df_daily["Debt_Historical"] - df_daily["Cash_Historical"]
                    df_daily["Valuation_Ratio"] = df_daily["Enterprise_Value"] / denominator

                    anchor_desc = "TTM" if anchor_source == "ttm" else "annual"

                    if periods_back:
                        report_freq = (
                            f"{anchor_desc} (EBITDA anchor lagged {periods_back} period(s) back; "
                            f"latest period was not usable)"
                        )
                        valuation_model = "EV_EBITDA_LAGGED_ANCHOR"
                    else:
                        report_freq = f"{anchor_desc} (latest EBITDA anchor, historical debt/cash)"

                    built = True

            # --------------------------------------------------------------
            # EV/EBIT
            # --------------------------------------------------------------
            elif not built and requested_model == "EV_EBIT":
                denominator = fundamentals.get("ebit")
                periods_back = fundamentals.get("ebit_periods_back")
                anchor_source = fundamentals.get("ebit_source")

                if not _finite_positive(denominator):
                    # No positive EBIT anywhere in the lookback window --
                    # fall back to P/S rather than hard-failing outright.
                    df_daily_ps, report_freq_ps, ps_error = _build_ps_valuation(
                        df_daily=df_daily,
                        quarterly=quarterly,
                        income=income,
                        fx_series=fx_series
                    )

                    if ps_error:
                        return (
                            None,
                            f"{ticker}: EV/EBIT model requires positive EBIT within the last "
                            f"{EBIT_EBITDA_LOOKBACK_PERIODS} annual reports (or a positive TTM figure), "
                            f"but none was found, and the P/S fallback also failed ({ps_error}).",
                            None,
                            fx_note,
                            sector,
                            valuation_model
                        )

                    df_daily = df_daily_ps
                    report_freq = f"{report_freq_ps} (fallback -- no positive EBIT in lookback window)"
                    valuation_model = "PS_EBIT_FALLBACK"
                    built = True
                else:
                    debt_hist = _build_debt_history(quarterly_balance, balance, fx_series)
                    cash_hist = _build_point_in_time_history(
                        quarterly_balance, balance,
                        ["Cash And Cash Equivalents", "CashAndCashEquivalents",
                         "Cash Cash Equivalents And Short Term Investments"],
                        fx_series
                    )

                    history_available = not debt_hist.empty or not cash_hist.empty

                    df_daily = _merge_point_in_time_onto_daily(
                        df_daily, debt_hist, "Debt_Historical", REPORTING_LAG_DAYS
                    )
                    df_daily = _merge_point_in_time_onto_daily(
                        df_daily, cash_hist, "Cash_Historical", REPORTING_LAG_DAYS
                    )

                    latest_debt = float(fundamentals.get("total_debt")) if _is_valid_number(fundamentals.get("total_debt")) else 0.0
                    latest_cash = float(fundamentals.get("cash")) if _is_valid_number(fundamentals.get("cash")) else 0.0

                    df_daily["Debt_Historical"] = df_daily["Debt_Historical"].fillna(latest_debt)
                    df_daily["Cash_Historical"] = df_daily["Cash_Historical"].fillna(latest_cash)

                    if not history_available:
                        data_quality_notes.append(
                            "No historical debt/cash time series was available; EV was built using "
                            "a single latest balance-sheet snapshot applied across the full price history."
                        )

                    negative_ev_periods = int(
                        (df_daily["Market_Cap"] + df_daily["Debt_Historical"] - df_daily["Cash_Historical"] <= 0).sum()
                    )

                    if negative_ev_periods > 0:
                        data_quality_notes.append(
                            f"{negative_ev_periods} period(s) had non-positive Enterprise Value (net-cash "
                            f"position exceeding market cap) and were excluded from the EV/EBIT series."
                        )

                    df_daily["Enterprise_Value"] = df_daily["Market_Cap"] + df_daily["Debt_Historical"] - df_daily["Cash_Historical"]
                    df_daily["Valuation_Ratio"] = df_daily["Enterprise_Value"] / denominator

                    anchor_desc = "TTM" if anchor_source == "ttm" else "annual"

                    if periods_back:
                        report_freq = (
                            f"{anchor_desc} (EBIT anchor lagged {periods_back} period(s) back; "
                            f"latest period was not usable)"
                        )
                        valuation_model = "EV_EBIT_LAGGED_ANCHOR"
                    else:
                        report_freq = f"{anchor_desc} (latest EBIT anchor, historical debt/cash)"

                    built = True

            # --------------------------------------------------------------
            # P/B
            # --------------------------------------------------------------
            elif not built and requested_model == "PB":
                book_value_hist = _build_point_in_time_history(
                    quarterly_balance, balance,
                    ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"],
                    fx_series
                )

                latest_book_value = fundamentals.get("equity")

                if book_value_hist.empty and not _finite_positive(latest_book_value):
                    return (
                        None,
                        f"{ticker}: P/B model requires positive book value, "
                        f"but no usable equity figure was found.",
                        None,
                        fx_note,
                        sector,
                        valuation_model
                    )

                df_daily = _merge_point_in_time_onto_daily(
                    df_daily, book_value_hist, "Book_Value_Historical", REPORTING_LAG_DAYS
                )

                if not book_value_hist.empty:
                    df_daily["Book_Value_Historical"] = df_daily["Book_Value_Historical"].fillna(latest_book_value)
                    report_freq = "annual (historical book-value series)"
                else:
                    df_daily["Book_Value_Historical"] = latest_book_value
                    data_quality_notes.append(
                        "No historical book-value time series was available; P/B was built using a "
                        "single latest equity snapshot applied across the full price history."
                    )
                    report_freq = "annual (latest book value anchor)"

                # Drop periods with non-positive book value (e.g. a company
                # that briefly had negative equity) rather than silently
                # producing a meaningless negative P/B for those dates.
                df_daily = df_daily[df_daily["Book_Value_Historical"] > 0]

                if df_daily.empty:
                    return (
                        None,
                        f"{ticker}: No periods with positive book value remain after aligning historical "
                        f"equity data.",
                        None,
                        fx_note,
                        sector,
                        valuation_model
                    )

                df_daily["Valuation_Ratio"] = df_daily["Market_Cap"] / df_daily["Book_Value_Historical"]

                built = True

            if not built:
                return (
                    None,
                    f"Unsupported or unresolvable valuation model: {requested_model}",
                    None,
                    fx_note,
                    sector,
                    valuation_model
                )

        # ------------------------------------------------------------------
        # Clean unified ratio output
        # ------------------------------------------------------------------
        df_daily = df_daily.replace([np.inf, -np.inf], np.nan)
        df_daily = df_daily.dropna(subset=["Valuation_Ratio"])
        df_daily = df_daily[df_daily["Valuation_Ratio"] > 0]
        df_daily = df_daily.sort_index()

        if df_daily.empty:
            return (
                None,
                "Sector-aware valuation ratio computation produced completely blank observation horizons.",
                None,
                fx_note,
                sector,
                valuation_model
            )

        # Temporary backward-compatibility alias.
        # Long-term, all callers should migrate to Valuation_Ratio.
        df_daily["PS_Ratio"] = df_daily["Valuation_Ratio"]

        df_daily.attrs["sector"] = sector
        df_daily.attrs["valuation_model"] = valuation_model
        df_daily.attrs["data_quality_notes"] = data_quality_notes

        return (
            df_daily,
            None,
            report_freq,
            fx_note,
            sector,
            valuation_model
        )

    except Exception as e:
        return (
            None,
            f"Fatal tracking pipeline internal error: {e}",
            None,
            None,
            sector,
            valuation_model
        )


# ----------------------------------------------------------------------
# Backward-compatible public interface
# ----------------------------------------------------------------------

def get_hardened_valuation_data(ticker, years):
    """
    Drop-in replacement for the original valuation_engine function.

    Returns the original four-tuple:

        df_daily, error, report_freq, fx_note

    This preserves compatibility with existing Home.py and
    pages/2_Valuation_Engine.py code.

    Sector and valuation_model metadata are still available via:

        df_daily.attrs["sector"]
        df_daily.attrs["valuation_model"]
        df_daily.attrs["data_quality_notes"]  -- list of str, may be empty
    """
    (
        df_daily,
        error,
        report_freq,
        fx_note,
        sector,
        valuation_model
    ) = get_hardened_valuation_data_v2(ticker, years)

    if df_daily is not None:
        df_daily.attrs["sector"] = sector
        df_daily.attrs["valuation_model"] = valuation_model

    return df_daily, error, report_freq, fx_note
