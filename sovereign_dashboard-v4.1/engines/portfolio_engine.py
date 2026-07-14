"""
Sovereign Portfolio Engine
==========================
Every other engine scores ONE ticker at a time. Nothing in the system
looks at the resulting portfolio as a whole. This engine does two things
none of the others do:

  1. CONCENTRATION -- does the structural grid itself breach sane position/
     layer/section limits? This is a property of structural_grid.py's
     target weights and needs no scan, no price data, no network call at
     all -- it's pure arithmetic on the weights you've already committed to.

  2. CORRELATION -- for a chosen set of tickers (typically your latest
     Home.py scan results, or any manual list), are your "different bets"
     actually the same bet wearing different tickers? A high-conviction
     top 5 that all move together isn't 5 units of diversification, it's
     1 unit of concentrated exposure with 5 tickers on it.

WHAT THIS DELIBERATELY DOES NOT DO
  It does not re-score tickers (that's Valuation/Expectations/Quality's
  job) and it does not decide capital allocation timing (that's the Macro
  Engine + Home.py's Conviction Score). It only asks: given the weights
  and tickers you've already chosen, is the RESULT a sane portfolio?
"""

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

MODEL_VERSION = "v1.0"

# Explicit, editable policy -- same philosophy as QUALITY_THRESHOLDS and
# the Macro Engine's ALLOCATION_POLICY: a stated limit set, not a
# discovered "correct" answer. Edit these to match your actual risk
# tolerance.
DEFAULT_LIMITS = {
    "max_single_position": 0.10,   # no single ticker above 10% of portfolio
    "max_layer": 0.15,             # no single layer above 15% (grid layers can already exceed
                                    # this by design -- e.g. INFRA Layer 1/2 are each 5.6% here,
                                    # fine; this catches layers that creep too large over edits)
    "max_section": 0.25,           # no single section above 25%
    "min_cash_buffer": 0.10,       # at least 10% held in CASH/dry powder
    "correlation_threshold": 0.80,  # price correlation above this = "same bet" flag
}


def check_concentration(universe_rows: list[dict], limits: dict = None, ignore_tickers: set = None) -> dict:
    """
    Runs position/layer/section concentration checks directly against
    structural_grid.py's flatten_universe() output -- no scan or price
    data required. This is a static property of your target weights.

    `ignore_tickers` (defaults to structural_grid.NON_EQUITY_TICKERS) is
    excluded from POSITION and LAYER breach checks only -- a 25% BTC
    cold-wallet allocation is a deliberate strategic sleeve, not a
    diversification failure, and flagging it as a "position breach"
    alongside an accidentally-oversized stock position would be misleading.
    These tickers still count fully in section_totals and the cash-buffer
    check, since section-level concentration is still a meaningful question
    even for a strategic sleeve.

    Returns {position_breaches, layer_breaches, section_breaches,
             cash_buffer, section_totals, layer_totals}
    Each breach entry: {name, weight, limit, excess}
    """
    limits = limits or DEFAULT_LIMITS
    ignore_tickers = ignore_tickers if ignore_tickers is not None else {"BTC", "GOLD", "CASH"}
    df = pd.DataFrame(universe_rows)
    scoreable_df = df[~df["ticker"].isin(ignore_tickers)]

    position_breaches = []
    for _, row in scoreable_df.iterrows():
        if row["effective_weight"] > limits["max_single_position"]:
            position_breaches.append({
                "name": row["ticker"], "weight": row["effective_weight"],
                "limit": limits["max_single_position"],
                "excess": row["effective_weight"] - limits["max_single_position"],
            })

    layer_totals = df.groupby(["section", "layer"])["effective_weight"].first().reset_index()
    # Using .first() not .sum(): effective_weight is already the layer's ceiling (shared across
    # every ticker in it), summing it per-ticker would double-count the same ceiling N times.
    scoreable_layers = layer_totals[~layer_totals["section"].isin(ignore_tickers)]
    layer_breaches = []
    for _, row in scoreable_layers.iterrows():
        if row["effective_weight"] > limits["max_layer"]:
            layer_breaches.append({
                "name": f"{row['section']} / {row['layer']}", "weight": row["effective_weight"],
                "limit": limits["max_layer"], "excess": row["effective_weight"] - limits["max_layer"],
            })

    section_totals_series = layer_totals.groupby("section")["effective_weight"].sum()
    # Reuses layer_totals (already one row per unique layer ceiling) rather than summing the
    # per-ticker rows directly, which would double/triple-count a layer's shared ceiling once
    # per ticker inside it.
    section_breaches = []
    for section_name, total_weight in section_totals_series.items():
        if total_weight > limits["max_section"]:
            section_breaches.append({
                "name": section_name, "weight": total_weight,
                "limit": limits["max_section"], "excess": total_weight - limits["max_section"],
            })

    cash_row = df[df["ticker"] == "CASH"]
    cash_weight = cash_row["effective_weight"].iloc[0] if not cash_row.empty else 0.0
    cash_buffer = {
        "weight": cash_weight, "limit": limits["min_cash_buffer"],
        "sufficient": cash_weight >= limits["min_cash_buffer"],
        "shortfall": max(0.0, limits["min_cash_buffer"] - cash_weight),
    }

    return {
        "position_breaches": position_breaches,
        "layer_breaches": layer_breaches,
        "section_breaches": section_breaches,
        "cash_buffer": cash_buffer,
        "section_totals": section_totals_series.to_dict(),
        "layer_totals": layer_totals,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def get_price_returns(tickers: tuple, period: str = "1y") -> tuple:
    """
    Batched price fetch for correlation analysis -- ONE yf.download() call
    for the whole ticker list rather than N separate yf.Ticker(...).history()
    calls (which is what the scoring engines each do per-ticker). Returns
    (returns_df, failed_tickers): a wide DataFrame of daily % returns
    (columns = tickers that resolved) and a list of tickers that didn't.

    `tickers` must be a tuple (not list) so it's hashable for @st.cache_data.
    """
    if not tickers:
        return pd.DataFrame(), []

    try:
        raw = yf.download(list(tickers), period=period, auto_adjust=True, progress=False, group_by="ticker")
    except Exception:
        return pd.DataFrame(), list(tickers)

    closes = {}
    failed = []
    for t in tickers:
        try:
            if len(tickers) == 1:
                series = raw["Close"] if "Close" in raw.columns else None
            else:
                series = raw[t]["Close"] if t in raw.columns.get_level_values(0) else None
            if series is not None and not series.dropna().empty:
                closes[t] = series
            else:
                failed.append(t)
        except Exception:
            failed.append(t)

    if not closes:
        return pd.DataFrame(), failed

    price_df = pd.DataFrame(closes).dropna(how="all")
    returns_df = price_df.pct_change().dropna(how="all")
    return returns_df, failed


def compute_correlation_matrix(returns_df: pd.DataFrame) -> pd.DataFrame:
    """Pairwise Pearson correlation of daily returns. Pure pandas, no fetch."""
    if returns_df.empty or returns_df.shape[1] < 2:
        return pd.DataFrame()
    return returns_df.corr()


def flag_correlated_pairs(corr_matrix: pd.DataFrame, threshold: float = 0.80) -> list[dict]:
    """
    Returns every ticker pair whose return correlation exceeds `threshold`,
    sorted by correlation descending. Each entry:
    {ticker_a, ticker_b, correlation}
    """
    if corr_matrix.empty:
        return []

    pairs = []
    tickers = corr_matrix.columns.tolist()
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            corr_val = corr_matrix.iloc[i, j]
            if pd.notna(corr_val) and corr_val >= threshold:
                pairs.append({"ticker_a": tickers[i], "ticker_b": tickers[j], "correlation": corr_val})

    return sorted(pairs, key=lambda p: p["correlation"], reverse=True)


def cluster_correlated_groups(pairs: list[dict]) -> list[set]:
    """
    Merges overlapping correlated pairs into clusters -- e.g. if A-B and
    B-C are both flagged, reports {A, B, C} as one cluster rather than two
    separate pairs, since that's the actual "these are all one bet" group.
    Simple union-find over the flagged pairs only (not all N tickers).
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for p in pairs:
        union(p["ticker_a"], p["ticker_b"])

    clusters = {}
    for ticker in parent:
        root = find(ticker)
        clusters.setdefault(root, set()).add(ticker)

    return [c for c in clusters.values() if len(c) > 1]


def classify_portfolio_health(concentration: dict, correlation_pairs: list[dict]) -> str:
    """Single headline label combining concentration + correlation findings."""
    n_breaches = (len(concentration["position_breaches"]) + len(concentration["layer_breaches"])
                  + len(concentration["section_breaches"]))
    cash_ok = concentration["cash_buffer"]["sufficient"]
    n_corr = len(correlation_pairs)

    if n_breaches == 0 and cash_ok and n_corr == 0:
        return "🟢 Balanced"
    if n_breaches == 0 and n_corr <= 2:
        return "✅ Reasonably Diversified"
    if n_breaches <= 2 or n_corr <= 5:
        return "🟡 Some Concentration Risk"
    return "🔴 Significantly Concentrated"
