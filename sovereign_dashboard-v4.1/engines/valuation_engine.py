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


# ----------------------------------------------------------------------
# Fundamental builder for EV/EBITDA, EV/EBIT, P/B, and P/FFO
# ----------------------------------------------------------------------

def _get_fundamentals(income, balance, cashflow, fx_series):
    """
    Extracts latest fundamental anchors required for non-P/S models.

    Returns:
        dict containing:
            ebit
            ebitda
            ffo
            total_debt
            cash
            equity
    """
    # EBIT
    ebit_raw = _latest_from_candidates(
        income,
        [
            "EBIT",
            "Operating Income",
            "OperatingIncome"
        ]
    )
    ebit = _convert_statement_value(ebit_raw, fx_series)

    # EBITDA
    ebitda_raw = _latest_from_candidates(
        income,
        [
            "EBITDA"
        ]
    )

    if _is_valid_number(ebitda_raw):
        ebitda = _convert_statement_value(ebitda_raw, fx_series)
    else:
        depreciation_raw = _latest_from_candidates(
            cashflow,
            [
                "Depreciation And Amortization",
                "DepreciationAndAmortization",
                "Depreciation"
            ]
        )
        depreciation = _convert_statement_value(depreciation_raw, fx_series)

        if _is_valid_number(ebit) and _is_valid_number(depreciation):
            ebitda = ebit + depreciation
        else:
            ebitda = np.nan

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
        "ebitda": ebitda,
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


def calculate_distribution_diagnostics(series, current_val):
    """
    Calculates distributional asymmetry and exact percentile rank location
    inside asset history.
    """
    clean = series.replace([np.inf, -np.inf], np.nan).dropna()

    if len(clean) < 30:
        return {"skewness": 0.0, "percentile": 50.0, "shape": "Insufficient Data Pool"}

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
        else:
            fallback_shares = info.get("sharesOutstanding")

            if not _is_valid_number(fallback_shares):
                fallback_shares = info.get("impliedSharesOutstanding")

            df_daily["Shares"] = fallback_shares

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
        cashflow = _safe_get_df(stock, "cashflow")

        report_freq = None

        # ------------------------------------------------------------------
        # P/S model
        # ------------------------------------------------------------------
        if requested_model == "PS":
            df_rev, report_freq, revenue_error = _build_revenue_ttm(
                quarterly=quarterly,
                annual=income,
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

            df_rev_sorted = df_rev[["Revenue_TTM"]].copy()
            df_rev_sorted.index = pd.to_datetime(df_rev_sorted.index)

            if df_rev_sorted.index.tz is not None:
                df_rev_sorted.index = df_rev_sorted.index.tz_localize(None)

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
                    "No valid tracking frames remain after performing trailing corporate revenue "
                    "and capitalization data filters.",
                    None,
                    fx_note,
                    sector,
                    valuation_model
                )

            df_daily["Valuation_Ratio"] = df_daily["Market_Cap"] / df_daily["Revenue_TTM"]

        else:
            # --------------------------------------------------------------
            # Non-P/S models require latest fundamental anchors
            # --------------------------------------------------------------
            fundamentals = _get_fundamentals(
                income=income,
                balance=balance,
                cashflow=cashflow,
                fx_series=fx_series
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
                    # FFO is not reliably available on many free Yahoo endpoints.
                    # Use P/B as a pragmatic interim fallback for REITs.
                    requested_model = "PB"
                    valuation_model = "PB_FFO_FALLBACK"

            # --------------------------------------------------------------
            # EV/EBITDA
            # --------------------------------------------------------------
            if not built and requested_model == "EV_EBITDA":
                denominator = fundamentals.get("ebitda")

                if not _finite_positive(denominator):
                    return (
                        None,
                        f"{ticker}: EV/EBITDA model requires positive latest EBITDA, "
                        f"but no usable EBITDA figure was found.",
                        None,
                        fx_note,
                        sector,
                        valuation_model
                    )

                debt = fundamentals.get("total_debt")
                cash = fundamentals.get("cash")

                debt = float(debt) if _is_valid_number(debt) else 0.0
                cash = float(cash) if _is_valid_number(cash) else 0.0

                df_daily["Enterprise_Value"] = df_daily["Market_Cap"] + debt - cash
                df_daily["Valuation_Ratio"] = df_daily["Enterprise_Value"] / denominator

                report_freq = "annual (latest EBITDA anchor)"
                built = True

            # --------------------------------------------------------------
            # EV/EBIT
            # --------------------------------------------------------------
            elif not built and requested_model == "EV_EBIT":
                denominator = fundamentals.get("ebit")

                if not _finite_positive(denominator):
                    return (
                        None,
                        f"{ticker}: EV/EBIT model requires positive latest EBIT, "
                        f"but no usable EBIT figure was found.",
                        None,
                        fx_note,
                        sector,
                        valuation_model
                    )

                debt = fundamentals.get("total_debt")
                cash = fundamentals.get("cash")

                debt = float(debt) if _is_valid_number(debt) else 0.0
                cash = float(cash) if _is_valid_number(cash) else 0.0

                df_daily["Enterprise_Value"] = df_daily["Market_Cap"] + debt - cash
                df_daily["Valuation_Ratio"] = df_daily["Enterprise_Value"] / denominator

                report_freq = "annual (latest EBIT anchor)"
                built = True

            # --------------------------------------------------------------
            # P/B
            # --------------------------------------------------------------
            elif not built and requested_model == "PB":
                book_value = fundamentals.get("equity")

                if not _finite_positive(book_value):
                    return (
                        None,
                        f"{ticker}: P/B model requires positive latest book value, "
                        f"but no usable equity figure was found.",
                        None,
                        fx_note,
                        sector,
                        valuation_model
                    )

                df_daily["Valuation_Ratio"] = df_daily["Market_Cap"] / book_value

                report_freq = "annual (latest book value anchor)"
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
