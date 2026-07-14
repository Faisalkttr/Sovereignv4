"""
Sovereign Quality Engine
========================
Answers a question the other three engines don't: is this a GOOD
business, independent of what it costs (Valuation Engine) or how much
growth is priced in (Expectations Engine) or whether now is a good time
to deploy capital at all (Macro Engine)?

A cheap, unpriced-for-perfection stock in a genuine macro window is still
a bad buy if the underlying business is a leveraged, dilutive, thin-margin
operator. This engine scores the business itself.

METRICS (five, TTM/latest-annual where TTM isn't available)
  1. ROIC              -- NOPAT / Invested Capital. Core capital-efficiency metric.
  2. Gross Margin       -- Gross Profit / Revenue. Pricing power / cost structure.
  3. FCF Margin          -- Free Cash Flow / Revenue. Cash conversion, not just accounting profit.
  4. Net Debt / EBITDA  -- Leverage. Lower (or net-cash / negative) is better.
  5. Share Dilution      -- YoY change in diluted shares outstanding. Lower is better;
                            negative (buybacks) is best.

Each metric is scored 0-100 against an explicit, editable threshold table
(QUALITY_THRESHOLDS below -- these are a stated policy, not a discovered
truth, same philosophy as the Macro Engine's ALLOCATION_POLICY). The five
scores are then weighted into one Quality Score (0-100) and classified.

DESIGN NOTE: this deliberately does NOT try to be sector-aware (e.g. a
royalty company like FNV or a bank don't fit a generic ROIC/margin
template well). That's flagged explicitly in the output rather than
silently producing a misleading number -- see `sector_caveat` in
`compute_quality_score`'s return dict.
"""

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

MODEL_VERSION = "v1.0"

QUALITY_STATUS_LEGEND = {
    "🟢 Fortress Quality": "High capital efficiency, strong margins, low leverage, minimal dilution.",
    "✅ Strong Quality": "Solidly above-average business quality across most metrics.",
    "🟡 Adequate Quality": "Middling quality -- no major red flags, no standout strengths either.",
    "🟠 Weak Quality": "Multiple metrics below healthy thresholds -- treat conviction cautiously.",
    "🔴 Fragile Quality": "Weak capital efficiency and/or high leverage and/or heavy dilution.",
    "⚪ Insufficient Data": "Not enough clean financial statement data to score reliably.",
}

# Sectors/business models where a generic ROIC + margin template is a poor
# fit and the Quality Score should be read with extra skepticism (royalty
# streamers, banks/financials, REITs -- their balance sheets and margin
# structures don't compare to an industrial or tech operating company).
SECTOR_CAVEAT_TICKERS = {
    "FNV": "Royalty/streaming model -- ROIC and margin templates built for operating "
           "companies don't map cleanly onto a royalty book. Read this score as informational only.",
    "WPM": "Royalty/streaming model -- same caveat as FNV.",
    "TPL": "Land/royalty model -- unusually high margins are structural, not a quality signal "
           "in the normal operating-company sense.",
}

# ---------------------------------------------------------------------
# EXPLICIT, EDITABLE THRESHOLD POLICY
# Each entry: list of (lower_bound_inclusive, score) pairs, evaluated
# top-down; first match wins. `higher_is_better` controls sort direction.
# ---------------------------------------------------------------------
QUALITY_THRESHOLDS = {
    "roic": {
        "higher_is_better": True,
        "bands": [(0.20, 100), (0.15, 80), (0.10, 60), (0.05, 40), (0.00, 20), (-np.inf, 0)],
    },
    "gross_margin": {
        "higher_is_better": True,
        "bands": [(0.60, 100), (0.40, 80), (0.25, 60), (0.10, 40), (0.00, 20), (-np.inf, 0)],
    },
    "fcf_margin": {
        "higher_is_better": True,
        "bands": [(0.20, 100), (0.10, 80), (0.05, 60), (0.00, 40), (-0.10, 20), (-np.inf, 0)],
    },
    "net_debt_to_ebitda": {
        "higher_is_better": False,
        "bands": [(-np.inf, 100), (1.0, 80), (2.0, 60), (3.5, 40), (5.0, 20), (np.inf, 0)],
    },
    "dilution_rate": {
        "higher_is_better": False,
        "bands": [(-np.inf, 100), (0.01, 80), (0.03, 60), (0.06, 40), (0.10, 20), (np.inf, 0)],
    },
}

QUALITY_WEIGHTS = {
    "roic": 0.30,
    "gross_margin": 0.15,
    "fcf_margin": 0.20,
    "net_debt_to_ebitda": 0.20,
    "dilution_rate": 0.15,
}


def score_metric(value, metric_name):
    """
    Maps a raw metric value to a 0-100 score using QUALITY_THRESHOLDS.
    Returns np.nan if value is None/NaN (metric unavailable -- excluded
    from the blend and re-weighted, not silently treated as zero).
    """
    if value is None or (isinstance(value, float) and (np.isnan(value) or not np.isfinite(value))):
        return np.nan

    spec = QUALITY_THRESHOLDS[metric_name]
    bands = spec["bands"]

    if spec["higher_is_better"]:
        for lower_bound, score in bands:
            if value >= lower_bound:
                return score
    else:
        for upper_bound, score in bands:
            if value <= upper_bound:
                return score

    return 0


def classify_quality(score):
    """Maps a blended 0-100 Quality Score to a status label."""
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return "⚪ Insufficient Data"
    if score >= 80:
        return "🟢 Fortress Quality"
    elif score >= 65:
        return "✅ Strong Quality"
    elif score >= 50:
        return "🟡 Adequate Quality"
    elif score >= 35:
        return "🟠 Weak Quality"
    else:
        return "🔴 Fragile Quality"


def _first_present(df, candidates):
    """Returns the first row label from `candidates` that exists in df.index, else None."""
    if df is None or df.empty:
        return None
    for label in candidates:
        if label in df.index:
            return label
    return None


def _latest_value(df, row_label):
    """Returns the most recent (first) column's value for a row label, or NaN."""
    if df is None or df.empty or row_label is None or row_label not in df.index:
        return np.nan
    row = df.loc[row_label].dropna()
    return row.iloc[0] if not row.empty else np.nan


def _prior_year_value(df, row_label):
    """Returns the second-most-recent column's value for a row label (YoY comparison), or NaN."""
    if df is None or df.empty or row_label is None or row_label not in df.index:
        return np.nan
    row = df.loc[row_label].dropna()
    return row.iloc[1] if len(row) > 1 else np.nan


@st.cache_data(ttl=86400)
def get_quality_data(ticker: str):
    """
    Fetches annual income statement, balance sheet, and cash flow data and
    derives the five raw quality metrics. Uses annual statements (not TTM)
    since ROIC/leverage are balance-sheet-anchored, point-in-time measures
    where TTM splicing (useful for revenue in the other engines) doesn't
    apply the same way.

    Returns (metrics: dict | None, error: str | None)
    metrics keys: roic, gross_margin, fcf_margin, net_debt_to_ebitda,
                  dilution_rate, plus raw components for transparency.
    """
    try:
        stock = yf.Ticker(ticker)

        try:
            income = stock.financials
        except Exception:
            income = pd.DataFrame()
        try:
            balance = stock.balance_sheet
        except Exception:
            balance = pd.DataFrame()
        try:
            cashflow = stock.cashflow
        except Exception:
            cashflow = pd.DataFrame()

        if income.empty and balance.empty and cashflow.empty:
            return None, "No annual financial statement data returned for this ticker."

        # --- Revenue & margins ---
        revenue_row = _first_present(income, ["Total Revenue", "TotalRevenue"])
        revenue = _latest_value(income, revenue_row)

        gross_profit_row = _first_present(income, ["Gross Profit", "GrossProfit"])
        gross_profit = _latest_value(income, gross_profit_row)
        if np.isnan(gross_profit) and revenue_row:
            cogs_row = _first_present(income, ["Cost Of Revenue", "CostOfRevenue"])
            cogs = _latest_value(income, cogs_row)
            gross_profit = revenue - cogs if not np.isnan(cogs) else np.nan

        gross_margin = gross_profit / revenue if revenue and not np.isnan(gross_profit) and revenue != 0 else np.nan

        # --- ROIC ---
        ebit_row = _first_present(income, ["EBIT", "Operating Income", "OperatingIncome"])
        ebit = _latest_value(income, ebit_row)

        tax_row = _first_present(income, ["Tax Provision", "TaxProvision"])
        pretax_row = _first_present(income, ["Pretax Income", "PretaxIncome"])
        tax_provision = _latest_value(income, tax_row)
        pretax_income = _latest_value(income, pretax_row)

        if not np.isnan(tax_provision) and not np.isnan(pretax_income) and pretax_income != 0:
            effective_tax_rate = np.clip(tax_provision / pretax_income, 0.0, 0.40)
        else:
            effective_tax_rate = 0.21  # US statutory corporate rate fallback

        nopat = ebit * (1 - effective_tax_rate) if not np.isnan(ebit) else np.nan

        debt_row = _first_present(balance, ["Total Debt", "TotalDebt"])
        total_debt = _latest_value(balance, debt_row)
        if np.isnan(total_debt):
            ltd_row = _first_present(balance, ["Long Term Debt", "LongTermDebt"])
            std_row = _first_present(balance, ["Current Debt", "CurrentDebt", "Short Long Term Debt"])
            ltd = _latest_value(balance, ltd_row)
            std = _latest_value(balance, std_row)
            total_debt = np.nansum([ltd, std]) if not (np.isnan(ltd) and np.isnan(std)) else np.nan

        equity_row = _first_present(balance, ["Stockholders Equity", "Total Stockholder Equity",
                                               "Common Stock Equity"])
        total_equity = _latest_value(balance, equity_row)

        cash_row = _first_present(balance, ["Cash And Cash Equivalents", "CashAndCashEquivalents",
                                             "Cash Cash Equivalents And Short Term Investments"])
        cash = _latest_value(balance, cash_row)

        invested_capital = np.nansum([total_debt, total_equity]) - (cash if not np.isnan(cash) else 0) \
            if not (np.isnan(total_debt) and np.isnan(total_equity)) else np.nan

        roic = nopat / invested_capital if (
            not np.isnan(nopat) and not np.isnan(invested_capital) and invested_capital > 0
        ) else np.nan

        # --- FCF margin ---
        ocf_row = _first_present(cashflow, ["Operating Cash Flow", "OperatingCashFlow",
                                             "Total Cash From Operating Activities"])
        capex_row = _first_present(cashflow, ["Capital Expenditure", "CapitalExpenditure"])
        ocf = _latest_value(cashflow, ocf_row)
        capex = _latest_value(cashflow, capex_row)
        fcf = ocf - abs(capex) if not np.isnan(ocf) and not np.isnan(capex) else np.nan
        fcf_margin = fcf / revenue if not np.isnan(fcf) and revenue else np.nan

        # --- Net Debt / EBITDA ---
        da_row = _first_present(cashflow, ["Depreciation And Amortization", "DepreciationAndAmortization",
                                            "Depreciation"])
        d_and_a = _latest_value(cashflow, da_row)
        ebitda = ebit + d_and_a if not np.isnan(ebit) and not np.isnan(d_and_a) else ebit

        net_debt = total_debt - cash if not np.isnan(total_debt) and not np.isnan(cash) else np.nan
        net_debt_to_ebitda = (
            net_debt / ebitda if not np.isnan(net_debt) and not np.isnan(ebitda) and ebitda > 0 else np.nan
        )

        # --- Dilution ---
        shares_row = _first_present(income, ["Diluted Average Shares", "DilutedAverageShares",
                                              "Basic Average Shares"])
        shares_now = _latest_value(income, shares_row)
        shares_prior = _prior_year_value(income, shares_row)
        dilution_rate = (
            (shares_now - shares_prior) / shares_prior
            if not np.isnan(shares_now) and not np.isnan(shares_prior) and shares_prior != 0
            else np.nan
        )

        metrics = {
            "roic": roic,
            "gross_margin": gross_margin,
            "fcf_margin": fcf_margin,
            "net_debt_to_ebitda": net_debt_to_ebitda,
            "dilution_rate": dilution_rate,
            # raw components, kept for the standalone page's transparency panel
            "_revenue": revenue, "_gross_profit": gross_profit, "_ebit": ebit,
            "_nopat": nopat, "_invested_capital": invested_capital, "_fcf": fcf,
            "_net_debt": net_debt, "_ebitda": ebitda,
            "_shares_now": shares_now, "_shares_prior": shares_prior,
            "_effective_tax_rate": effective_tax_rate,
        }

        if all(np.isnan(v) for k, v in metrics.items() if not k.startswith("_")):
            return None, "All five quality metrics were unresolvable from available statement rows."

        return metrics, None

    except Exception as e:
        return None, f"Fatal quality data pipeline error: {e}"


def compute_quality_score(ticker: str, metrics: dict):
    """
    Scores each available metric 0-100, blends with QUALITY_WEIGHTS
    (re-normalized over whichever metrics are actually available), and
    classifies the result.

    Returns dict: {quality_score, classification, component_scores,
                   available_weight, sector_caveat}
    """
    component_scores = {}
    for metric_name in QUALITY_WEIGHTS:
        component_scores[metric_name] = score_metric(metrics.get(metric_name), metric_name)

    available = {k: v for k, v in component_scores.items() if not np.isnan(v)}

    if not available:
        return {
            "quality_score": np.nan,
            "classification": classify_quality(np.nan),
            "component_scores": component_scores,
            "available_weight": 0.0,
            "sector_caveat": SECTOR_CAVEAT_TICKERS.get(ticker.upper()),
        }

    total_weight = sum(QUALITY_WEIGHTS[k] for k in available)
    quality_score = sum(available[k] * QUALITY_WEIGHTS[k] for k in available) / total_weight

    return {
        "quality_score": quality_score,
        "classification": classify_quality(quality_score),
        "component_scores": component_scores,
        "available_weight": total_weight,  # <1.0 means some metrics were missing -- score is less complete
        "sector_caveat": SECTOR_CAVEAT_TICKERS.get(ticker.upper()),
    }
