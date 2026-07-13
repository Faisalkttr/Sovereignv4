"""
Sovereign Valuation & Discipline Engine -- core logic only.

This is app3.py with all Streamlit page/sidebar/chart-rendering code
stripped out, leaving just the pure data-fetch and scoring functions so
they can be imported from Home.py (the combined Conviction dashboard) and
from pages/2_Valuation_Engine.py without duplicating logic in two places.

Behavior is unchanged from the original app3.py -- only the surrounding
UI was removed.
"""

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

MODEL_VERSION = "v1.2-Final"

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


def calculate_data_quality(df, report_freq, fx_note):
    """Evaluates raw historical observation thickness and corporate report frequency data health."""
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
    """Maps model deployment intensity into an operational capital-allocation posture."""
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
    """Applies unified color-coding matrices to the batch portfolio dashboard dataframe."""
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
    """Calculates distributional asymmetry and exact percentile rank location inside asset history."""
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
    """Calculates Median Absolute Deviation (MAD) anchored robust Z-score."""
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
    ticker, is_core, z_score, robust_z_score, z_threshold, percentile, skewness, macro_mode, floors
):
    """
    Regime-aware multi-dimensional systemic engine. Cross-validates standard parameters
    against robust metrics, percentile limits, and global liquidity environments.
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
            explanation = (f"Valuation severely discounted via [{value_text}]. Compelling micro metrics "
                            f"confront high macro system stress. Strategic core floor modulated to protect capital.")
        elif macro_transition:
            allocation_multiplier = 1.25 if is_core else 0.75
            explanation = (f"Valuation optimization confirmed via [{value_text}] during transition liquidity "
                            f"tracking. Steady, disciplined pacing active.")
        else:
            allocation_multiplier = 1.50 if is_core else 1.00
            explanation = (f"Deep value terrain established via [{value_text}] alongside healthy expansionary "
                            f"macro liquidity frameworks. Core model pacing increases within configured risk bounds.")
        return status_stance, allocation_multiplier, explanation, distribution_reliability

    if valuation_pressure:
        if is_core:
            if percentile >= 95:
                status_stance = "🔵 Core Scarcity Premium"
                explanation = (f"Asset is extended versus realised valuation history. Trigger source: "
                                f"[{pressure_text}]. Core floor rules preserve exposure-building bounds to "
                                f"lock in multi-year position compounding.")
            else:
                status_stance = "🟠 Core High-Expectation Zone"
                explanation = (f"Significant valuation pressure tracking via [{pressure_text}]. Portfolio "
                                f"defense limits velocity; core allocation scaled down to minimum protective floors.")

            if macro_crunch:
                allocation_multiplier = floors['crunch']
            elif macro_transition:
                allocation_multiplier = floors['transition']
            else:
                allocation_multiplier = floors['expansion']
        else:
            status_stance = "🔴 Tactical Valuation Halt"
            allocation_multiplier = 0.00
            explanation = (f"Asset lacks structural Sovereign Core classification. High multiple friction "
                            f"across checks [{pressure_text}] commands a tactical deployment pause.")
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
            explanation = "Core asset trades within standard premium tolerances. Pacing adjusted down using macro landscape boundaries."
        else:
            status_stance = "🟡 Tactical Premium Zone"
            if macro_crunch:
                allocation_multiplier = 0.00
            elif macro_transition:
                allocation_multiplier = 0.25
            else:
                allocation_multiplier = 0.50
            explanation = "Tactical asset valuation floats above historical equilibrium baselines. Deployment throttled to preserve liquidity optionality."
        return status_stance, allocation_multiplier, explanation, distribution_reliability

    status_stance = "✅ Normal Range"
    if macro_crunch:
        allocation_multiplier = 0.25 if is_core else 0.00
        explanation = "Asset valuation metrics reflect normal baselines, but the macro liquidity landscape is defensive. Non-core tactical operations are paused."
    elif macro_transition:
        allocation_multiplier = 0.50 if is_core else 0.35
        explanation = "Equilibrium asset pricing detected under structural transitional matrix constraints. Model pacing remains measured and controlled."
    else:
        allocation_multiplier = 1.00 if is_core else 0.75
        explanation = "Standard normalized historical pricing interacting with expansionary liquidity states. Baseline model pacing is active."

    return status_stance, allocation_multiplier, explanation, distribution_reliability


@st.cache_data(ttl=86400)
def get_hardened_valuation_data(ticker, years):
    """Fetches price/shares/revenue history and builds a P/S ratio time series. Unchanged from app3.py."""
    try:
        stock = yf.Ticker(ticker)

        try:
            info = stock.info or {}
        except Exception:
            info = {}

        try:
            shares = stock.get_shares_full(start=pd.Timestamp.now() - pd.Timedelta(days=years * 365))
        except Exception:
            shares = pd.Series(dtype=float)

        try:
            history = stock.history(period=f"{years}y", interval="1d")
        except Exception:
            history = pd.DataFrame()

        if history.empty:
            return None, "No historical time series asset data could be parsed from API sources.", None, None

        df_daily = pd.DataFrame(history["Close"]).copy()
        df_daily.index = pd.to_datetime(df_daily.index)
        if df_daily.index.tz is not None:
            df_daily.index = df_daily.index.tz_localize(None)

        def find_revenue_row(fin_df):
            if fin_df is None or fin_df.empty:
                return None
            for candidate in ["Total Revenue", "TotalRevenue", "Revenue"]:
                if candidate in fin_df.index:
                    return candidate
            return None

        def classify_frequency(series):
            if len(series) < 2:
                return None, None
            gaps_days = series.sort_index().index.to_series().diff().dt.days.dropna()
            if gaps_days.empty:
                return None, None
            median_gap = gaps_days.median()
            return ("quarterly", 4) if median_gap <= 130 else (("semi-annual", 2) if median_gap <= 250 else ("annual", 1))

        try:
            quarterly = stock.quarterly_financials
        except Exception:
            quarterly = pd.DataFrame()

        try:
            annual = stock.financials
        except Exception:
            annual = pd.DataFrame()

        fx_note = None
        financial_currency = info.get("financialCurrency")
        price_currency = info.get("currency")
        fx_series = None

        if financial_currency and price_currency and financial_currency != price_currency:
            fx_symbol = f"{price_currency}{financial_currency}=X"
            try:
                fx_hist = yf.Ticker(fx_symbol).history(period=f"{years}y", interval="1d")["Close"]
            except Exception:
                fx_hist = pd.Series(dtype=float)

            if fx_hist is not None and not fx_hist.empty:
                fx_hist.index = pd.to_datetime(fx_hist.index)
                if fx_hist.index.tz is not None:
                    fx_hist.index = fx_hist.index.tz_localize(None)
                fx_series = fx_hist.sort_index().rename("FX_Rate").to_frame()
                fx_note = (
                    f"Converted reporting financial currency from {financial_currency} into transactional pricing units ({price_currency}) "
                    f"using {fx_symbol}; revenue divided by the historical FX rate series."
                )
            else:
                fx_note = f"⚠️ Currency mismatch tracked ({financial_currency} vs {price_currency}). Cross currency conversion array [{fx_symbol}] failed loading."

        def apply_fx_normalization(series):
            if fx_series is None or series.empty:
                return series
            idx = pd.to_datetime(series.index)
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            df_ = series.copy()
            df_.index = idx
            df_ = df_.sort_index().rename("Revenue_Raw").to_frame()
            df_ = pd.merge_asof(df_, fx_series, left_index=True, right_index=True, direction="backward")
            df_["FX_Rate"] = df_["FX_Rate"].bfill()
            return series if df_["FX_Rate"].isna().all() else df_["Revenue_Raw"] / df_["FX_Rate"]

        q_row = find_revenue_row(quarterly)
        rev_q = quarterly.loc[q_row].dropna() if (q_row and not quarterly.empty) else pd.Series(dtype=float)
        rev_q = apply_fx_normalization(rev_q)
        q_freq, q_window = classify_frequency(rev_q)

        df_rev_q = pd.DataFrame()
        if q_freq and len(rev_q) >= q_window:
            df_rev_q = pd.DataFrame(rev_q).sort_index()
            df_rev_q.columns = ["Revenue_Period"]
            df_rev_q["Revenue_TTM"] = df_rev_q["Revenue_Period"].rolling(window=q_window).sum()
            df_rev_q = df_rev_q.dropna()

        a_row = find_revenue_row(annual)
        rev_a = annual.loc[a_row].dropna() if (a_row and not annual.empty) else pd.Series(dtype=float)
        rev_a = apply_fx_normalization(rev_a)

        df_rev_a = pd.DataFrame()
        if len(rev_a) >= 1:
            df_rev_a = pd.DataFrame(rev_a).sort_index()
            df_rev_a.columns = ["Revenue_Period"]
            df_rev_a["Revenue_TTM"] = df_rev_a["Revenue_Period"]
            df_rev_a = df_rev_a.dropna()

        if df_rev_q.empty and df_rev_a.empty:
            return None, "Corporate revenue matrix logs completely empty across known filing timelines.", None, None
        elif not df_rev_q.empty and not df_rev_a.empty:
            q_start = df_rev_q.index.min()
            older_annual = df_rev_a[df_rev_a.index < q_start]
            if not older_annual.empty:
                df_rev = pd.concat([older_annual[["Revenue_TTM"]], df_rev_q[["Revenue_TTM"]]]).sort_index()
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

        if not shares.empty:
            shares_series = shares.sort_index()
            shares_series.index = pd.to_datetime(shares_series.index)
            if shares_series.index.tz is not None:
                shares_series.index = shares_series.index.tz_localize(None)

            df_daily = pd.merge_asof(
                df_daily.sort_index(), shares_series.rename("Shares").to_frame().sort_index(),
                left_index=True, right_index=True, direction="backward"
            )
            df_daily["Shares"] = df_daily["Shares"].fillna(info.get("sharesOutstanding"))
        else:
            df_daily["Shares"] = info.get("sharesOutstanding")

        if df_daily["Shares"].isna().all():
            return None, "Systemic failure checking share outstanding matrix. Cannot build market capitalization maps securely.", None, fx_note

        df_daily["Market_Cap"] = df_daily["Close"] * df_daily["Shares"]

        df_rev_sorted = df_rev[["Revenue_TTM"]].sort_index()
        df_rev_sorted.index = pd.to_datetime(df_rev_sorted.index)
        if df_rev_sorted.index.tz is not None:
            df_rev_sorted.index = df_rev_sorted.index.tz_localize(None)

        df_daily = pd.merge_asof(
            df_daily.sort_index(), df_rev_sorted,
            left_index=True, right_index=True, direction="backward"
        )

        df_daily = df_daily.dropna(subset=["Revenue_TTM", "Market_Cap"])
        df_daily = df_daily[df_daily["Revenue_TTM"] > 0]

        if df_daily.empty:
            return None, "No valid tracking frames remain after performing trailing corporate revenue and capitalization data filters.", None, fx_note

        df_daily["PS_Ratio"] = df_daily["Market_Cap"] / df_daily["Revenue_TTM"]
        df_daily = df_daily.replace([np.inf, -np.inf], np.nan).dropna(subset=["PS_Ratio"])
        df_daily = df_daily.sort_index()

        if df_daily.empty:
            return None, "Price-to-Sales computation process produced completely blank observation horizons.", None, fx_note

        return df_daily, None, report_freq, fx_note
    except Exception as e:
        return None, f"Fatal tracking pipeline internal error: {e}", None, None
