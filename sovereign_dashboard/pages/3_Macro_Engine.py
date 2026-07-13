import streamlit as st
import pandas as pd
import requests
from datetime import datetime

# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------
st.set_page_config(page_title="Sovereign Macro Engine", layout="wide", page_icon="🛡️")

# --------------------------------------------------
# THEME / CSS
# --------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap');

html, body, [class*="css"]  { font-family: 'Inter', sans-serif; }

.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1200px; }

/* Streamlit default title/caption restyle */
h1 { font-weight: 800 !important; letter-spacing: -0.02em; }

.sme-section-label {
    font-size: 12px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
    color: #8892a6; margin: 28px 0 10px 0; display: flex; align-items: center; gap: 8px;
}
.sme-section-label::after {
    content: ""; flex: 1; height: 1px; background: #232838; margin-left: 8px;
}

.sme-asof {
    display:inline-block; font-size:12px; color:#8892a6; background:#12161f;
    border:1px solid #232838; border-radius:999px; padding:4px 12px; margin-bottom:6px;
}

.sme-card {
    background: #12161f; border: 1px solid #232838; border-left: 4px solid var(--accent, #7fa8c9);
    border-radius: 12px; padding: 16px 18px; height: 100%;
}
.sme-card .lbl {
    font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #8892a6;
}
.sme-card .val {
    font-family: 'JetBrains Mono', monospace; font-size: 26px; font-weight: 700; color: #eef1f7; margin: 6px 0 2px 0;
}
.sme-card .delta { font-size: 13px; font-weight: 600; color: var(--accent, #7fa8c9); }
.sme-card .note { font-size: 11px; color: #6b7385; margin-top: 4px; }

.sme-badge {
    background: var(--bg, #12161f); border: 1px solid var(--accent, #7fa8c9); border-radius: 12px;
    padding: 16px 18px; text-align: center; height: 100%;
}
.sme-badge .lbl {
    font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #8892a6;
}
.sme-badge .val {
    font-size: 19px; font-weight: 800; color: var(--accent, #7fa8c9); margin-top: 8px;
}
.sme-badge .note { font-size: 11px; color: #6b7385; margin-top: 6px; }

.sme-hero {
    border-radius: 16px; padding: 24px 28px; margin: 4px 0 26px 0;
    background: var(--bg, #12161f); border: 1px solid var(--accent, #7fa8c9);
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px;
}
.sme-hero .tag {
    font-size: 12px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: #8892a6;
}
.sme-hero .phase {
    font-size: 30px; font-weight: 800; color: var(--accent, #7fa8c9); margin-top: 4px;
}
.sme-hero .side { text-align: right; font-size: 13px; color: #8892a6; line-height: 1.7; }
.sme-hero .side b { color: #eef1f7; }
</style>
""", unsafe_allow_html=True)

st.title("🛡️ Sovereign Macro Execution Engine")
st.caption("Execution > Prediction  |  Survival First")

# --------------------------------------------------
# API CONFIG
# --------------------------------------------------
api_key = st.secrets.get("FRED_API_KEY")
if not api_key:
    api_key = st.sidebar.text_input("Enter FRED API Key", type="password")

if not api_key:
    st.warning("Enter FRED API Key")
    st.stop()

start_date = "2015-01-01"
end_date = datetime.now().strftime("%Y-%m-%d")

# --------------------------------------------------
# SOVEREIGN 15-YEAR ENGINE — USER INPUTS
# --------------------------------------------------
# These CANNOT be derived from FRED data -- they describe YOUR actual
# portfolio, which this engine has no independent visibility into. Manual
# entry here is intentional, not a placeholder: any "current allocation"
# or "drawdown" number this engine shows is only ever as accurate as what
# you enter.
st.sidebar.markdown("---")
st.sidebar.subheader("🏛️ Sovereign Engine Inputs")
current_alloc_pct = st.sidebar.slider(
    "Your current deployed % (risk sleeve vs. total investable cash)",
    min_value=0, max_value=100, value=50, step=1,
    help="What fraction of your investable money is currently deployed into the risk sleeve "
         "(everything except your dry-powder cash), as best you can estimate today."
)
current_alloc = current_alloc_pct / 100

portfolio_value_input = st.sidebar.number_input(
    "Today's total portfolio value (optional, for drawdown tracking)",
    min_value=0.0, value=0.0, step=100.0,
    help="Leave at 0 to skip drawdown tracking. If entered, this gets appended to a local "
         "history log each time you open the app so drawdown-from-peak can be computed over time."
)

log_snapshot_clicked = st.sidebar.button("📝 Log today's snapshot to history")

# --------------------------------------------------
# POSITIONING OVERLAY — USER INPUTS (manual, optional, off by default)
# --------------------------------------------------
# WHY MANUAL: unlike everything above the SERIES MAP below, none of these
# three proxies (index concentration, breadth, a VIX-term ratio) have a
# free FRED series -- FRED does not publish equity breadth or a
# short/long VIX ratio. This is not a placeholder to "fill in later with
# real data" inside this file; it is fundamentally the same kind of input
# as current_alloc above -- something only YOU can supply, from wherever
# you track it (your broker, a market-breadth site, CBOE VIX9D/VIX).
#
# OFF BY DEFAULT, ON PURPOSE: unlike current_alloc (which the rest of the
# engine already depended on), this is a brand-new overlay being added on
# top of an otherwise-working governor. Defaulting it to enabled would mean
# governed_target silently changes the moment this code ships, driven by
# three numbers nobody has entered or reviewed for today. Leaving it off
# until you deliberately turn it on and enter today's estimates keeps that
# a conscious choice rather than a silent behavior change.
st.sidebar.markdown("---")
st.sidebar.subheader("👥 Positioning Overlay (optional, manual)")
positioning_enabled = st.sidebar.checkbox(
    "Enable positioning overlay",
    value=False,
    help="Off by default -- turning this on lets crowding/breadth/vol-complacency estimates "
         "you enter below add an additional haircut in the System Governor. These are your "
         "own estimates, not fetched data; treat the resulting score with the same "
         "skepticism as the other hand-tuned heuristics in this engine."
)

if positioning_enabled:
    concentration_pct = st.sidebar.slider(
        "Top-10 index weight concentration (%)", min_value=0, max_value=60, value=25, step=1,
        help="Roughly, what % of your reference index's weight sits in its top 10 names. "
             "Higher = more crowded into a narrow set of leaders."
    )
    breadth_pct = st.sidebar.slider(
        "Market breadth -- advancing vs. total (%)", min_value=0, max_value=100, value=50, step=1,
        help="Roughly, what % of stocks/assets in your reference universe are trending up "
             "alongside the index. Lower = narrower, more crowded leadership."
    )
    vol_ratio_input = st.sidebar.number_input(
        "Short-term / long-term vol ratio (e.g. VIX9D / VIX)", min_value=0.0, value=1.0, step=0.05,
        help="Below 1.0 = short-term vol priced below long-term vol -- a common complacency "
             "signal. Leave at 1.0 (neutral) if you don't track this."
    )
else:
    concentration_pct, breadth_pct, vol_ratio_input = 25, 50, 1.0  # neutral values, unused unless enabled

# --------------------------------------------------
# SERIES MAP
# --------------------------------------------------
# NOTE ON "DXY": DTWEXAFEGS is the Fed's free Nominal Advanced Foreign
# Economies Dollar Index -- a broad ~26-currency, trade-weighted basket,
# base year 2006=100. It is NOT the ICE US Dollar Index (DXY), which is a
# fixed 6-currency basket (EUR-dominated), base year 1973=100, and is
# proprietary/paid data. The two are highly correlated on % moves but their
# RAW LEVELS are not comparable -- do not read this index's level as if it
# were a DXY quote. We label it "USD Index (Fed Broad-AFE)" throughout and
# only ever use its % change (trend), never its level, in engine logic.
SERIES = {
    "USD_BROAD": "DTWEXAFEGS",   # proxy for USD strength, NOT ICE DXY
    "10Y": "DGS10",
    "FED": "WALCL",              # $ millions
    "RRP": "RRPONTSYD",          # $ billions  <-- different unit than FED/TGA
    "TGA": "WTREGEN",            # $ millions
    "CREDIT_SPREAD": "BAMLH0A0HYM2"
}

# --------------------------------------------------
# FETCH DATA
# --------------------------------------------------
@st.cache_data(ttl=86400)
def fetch(series):
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        if "observations" not in data:
            st.warning(f"No observations returned for series '{series}'.")
            return pd.Series(dtype="float64")

        df = pd.DataFrame(data["observations"])
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

        return df.dropna().set_index("date")["value"]

    except requests.exceptions.RequestException as e:
        st.warning(f"Network/API error fetching '{series}': {e}")
        return pd.Series(dtype="float64")
    except Exception as e:
        st.warning(f"Unexpected error fetching '{series}': {e}")
        return pd.Series(dtype="float64")

# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------
usd_broad = fetch(SERIES["USD_BROAD"])
y10 = fetch(SERIES["10Y"])
fed = fetch(SERIES["FED"])
rrp = fetch(SERIES["RRP"])
tga = fetch(SERIES["TGA"])
credit_spread = fetch(SERIES["CREDIT_SPREAD"])

# --------------------------------------------------
# ALIGN LIQUIDITY DATA (UNIT FIX: RRP is in $B, FED/TGA are in $M)
# --------------------------------------------------
if fed.empty or rrp.empty or tga.empty:
    st.error("One or more liquidity series (FED/RRP/TGA) failed to load. "
             "Liquidity metrics will be unavailable.")

rrp_millions = rrp * 1000  # convert $B -> $M so all three series share units

# FREQUENCY FIX: WALCL (Fed balance sheet) only publishes once a week
# (Wednesdays). RRP and TGA publish daily. Previously all three were
# forward-filled onto a shared daily index -- which repeats the same
# single weekly WALCL print across 6 daily rows, creating the illusion of
# daily-resolution granularity in net_liquidity that the underlying data
# doesn't actually support (pct_change(30) would look smoother than the
# real weekly data justifies). Liquidity is a balance-sheet signal, not a
# tick-by-tick one, so we resample all three components down to weekly
# (Wednesday-anchored, matching WALCL's native cadence) before combining.
if not fed.empty:
    fed_w = fed.resample("W-WED").last()
else:
    fed_w = fed
rrp_w = rrp_millions.resample("W-WED").last() if not rrp_millions.empty else rrp_millions
tga_w = tga.resample("W-WED").last() if not tga.empty else tga

df_liq = pd.concat([fed_w, rrp_w, tga_w], axis=1)
df_liq.columns = ["fed", "rrp", "tga"]
df_liq = df_liq.ffill().dropna()

# --------------------------------------------------
# ALIGN ALL DAILY SIGNALS TO A COMMON CALENDAR
# --------------------------------------------------
# Previously usd_broad / y10 / credit_spread were each read independently
# with .iloc[-1], so "latest" could silently mean different calendar dates
# across metrics (they publish on different schedules / with different
# reporting lags). Reindex everything onto one shared daily index and
# forward-fill, so every "latest" value reflects the same as-of date.
common_index = df_liq.index
for s in (usd_broad, y10, credit_spread):
    if not s.empty:
        common_index = common_index.union(s.index)
common_index = common_index.sort_values()

def align(s):
    if s.empty:
        return s
    return s.reindex(common_index).ffill()

usd_broad_a = align(usd_broad)
y10_a = align(y10)
credit_spread_a = align(credit_spread)

as_of_date = common_index.max() if len(common_index) else None

# --------------------------------------------------
# LIQUIDITY ENGINE (SMOOTHED)
# --------------------------------------------------
net_liquidity = df_liq["fed"] - df_liq["rrp"] - df_liq["tga"]  # all in $M now, weekly cadence

# WINDOW FIX: net_liquidity is now weekly (see resample above), so a
# 30-period pct_change would mean 30 WEEKS (~7 months), not 30 days as
# before. To keep the "~1 month lookback" intent from the daily version,
# use 4 weekly periods (~1 month) with a 2-week smoothing window instead
# of the daily 30/5 pairing.
LIQ_WINDOW_WEEKS = 4
LIQ_SMOOTH_WEEKS = 2

liq_impulse_raw = net_liquidity.pct_change(LIQ_WINDOW_WEEKS)
liq_impulse = liq_impulse_raw.rolling(LIQ_SMOOTH_WEEKS).mean().dropna()

liq_trend = liq_impulse.iloc[-1] if not liq_impulse.empty else 0

# ACCELERATION (2nd derivative): is the liquidity trend itself speeding up
# or rolling over? A negative liq_trend that's decelerating (accel > 0)
# suggests contraction may be bottoming; a positive liq_trend that's
# decelerating (accel < 0) suggests expansion may be running out of steam.
# This is a genuinely useful addition on top of first-derivative trend.
liq_acceleration = liq_impulse.diff().iloc[-1] if len(liq_impulse) > 1 else 0

def liq_momentum_state(trend_val, accel_val):
    if trend_val > 0 and accel_val > 0:
        return "EXPANDING (accelerating)"
    elif trend_val > 0 and accel_val <= 0:
        return "EXPANDING (losing steam)"
    elif trend_val <= 0 and accel_val > 0:
        return "CONTRACTING (bottoming)"
    else:
        return "CONTRACTING (accelerating)"

liq_momentum = liq_momentum_state(liq_trend, liq_acceleration)

# --------------------------------------------------
# CORE SIGNALS
# --------------------------------------------------
# NOTE: window/smoothing choices below are intentionally standardized
# (30-day % change, 5-day rolling smooth) across every trend signal so
# that liq_trend, yield_trend, dxy_trend, and credit_trend_val are all
# measured on the same time basis before being compared/combined in the
# regime and system-phase classifiers below. (Previously yield_trend used
# an unsmoothed 60-day window while liquidity/credit used smoothed 30-day
# windows -- an apples-to-oranges comparison.)
TREND_WINDOW = 30
SMOOTH_WINDOW = 5

def trend(series, window=TREND_WINDOW, smooth=SMOOTH_WINDOW):
    if series.empty:
        return 0
    raw = series.pct_change(window)
    smoothed = raw.rolling(smooth).mean().dropna()
    if smoothed.empty:
        return 0
    return smoothed.iloc[-1]

yield_trend = trend(y10_a)
dxy_trend = trend(usd_broad_a)          # "dxy_trend" kept as variable name
credit_trend_val = trend(credit_spread_a)

# --------------------------------------------------
# ACTUAL LEVEL VALUES
# --------------------------------------------------
latest_yield = y10_a.iloc[-1] if not y10_a.empty else 0
latest_usd_broad = usd_broad_a.iloc[-1] if not usd_broad_a.empty else 0
latest_credit = credit_spread_a.iloc[-1] if not credit_spread_a.empty else 0
latest_liquidity = net_liquidity.iloc[-1] if not net_liquidity.empty else 0

# --------------------------------------------------
# CREDIT STATE
# --------------------------------------------------
def credit_state(val):
    if val > 0.15:
        return "STRESS SPIKE"
    elif val > 0:
        return "WIDENING"
    else:
        return "STABLE"

credit_status = credit_state(credit_trend_val)

# --------------------------------------------------
# SYSTEM PHASE
# --------------------------------------------------
# GAP FIX: previously this only modeled downside/stress states (FRACTURE,
# SYSTEM BREAK) and collapsed every other combination -- including genuine
# liquidity expansion, dollar-weakening easing cycles, and unstable
# "liquidity up but dollar also up" setups -- into a single flat "NORMAL".
# That throws away information you're already computing (liq_trend,
# dxy_trend) elsewhere. Add explicit upside/transitional states so the
# phase output actually reflects the full state space, not just the
# crisis corner of it.
def detect_system_phase(liq, dxy, credit):

    # --- downside / stress states (checked first, highest priority) ---
    if liq < 0 and dxy > 0 and credit == "STRESS SPIKE":
        return "SYSTEM BREAK"

    if liq < 0 and dxy > 0 and credit == "WIDENING":
        return "FRACTURE"

    if credit == "STRESS SPIKE":
        # Credit stress firing even without the liq/dxy alignment above is
        # still worth flagging on its own -- credit markets often lead.
        return "CREDIT STRESS"

    # --- upside / expansion states ---
    if liq > 0 and dxy < 0 and credit == "STABLE":
        # Textbook easing: liquidity rising, dollar weakening, credit calm.
        return "LIQUIDITY EXPANSION"

    if liq > 0 and dxy < 0 and credit == "WIDENING":
        # Liquidity/dollar say expansion, credit hasn't confirmed yet.
        return "EXPANSION (credit lagging)"

    if liq > 0 and dxy > 0:
        # Liquidity rising AND dollar rising is not the clean easing setup
        # -- often reflects safe-haven flows offsetting stimulus, or a
        # short-covering rally rather than durable expansion. Flag as
        # fragile rather than lumping it in with NORMAL or true expansion.
        return "FRAGILE EXPANSION"

    return "NORMAL"

system_phase = detect_system_phase(liq_trend, dxy_trend, credit_status)

# Defined here (not just in the dashboard section below) so it's available
# to any logic computed before the UI renders -- e.g. generate_alerts()
# in the Sovereign Engine block needs this before the dashboard section runs.
STRESS_PHASES = {"SYSTEM BREAK", "FRACTURE", "CREDIT STRESS"}

# --------------------------------------------------
# REGIME
# --------------------------------------------------
# MAGNITUDE FIX: previously any nonzero sign (even a +0.0001% noise move)
# was enough to trigger a full regime label like "QT" or "HARD_PIVOT".
# That treats a rounding-error-sized move the same as a real repricing.
# Add a minimum-magnitude threshold both signals must clear before a
# directional regime is assigned; sub-threshold moves fall through to
# TRANSITION (i.e. "no clear signal yet") instead of a false-confidence
# label.
REGIME_MAGNITUDE_THRESHOLD = 0.02  # 2% minimum move to count as directional

def classify_regime(y, d, threshold=REGIME_MAGNITUDE_THRESHOLD):
    y_sig = y if abs(y) >= threshold else 0
    d_sig = d if abs(d) >= threshold else 0

    if y_sig > 0 and d_sig > 0:
        return "QT"
    elif y_sig < 0 and d_sig < 0:
        return "SOFT_PIVOT"
    elif y_sig < 0 and d_sig > 0:
        return "HARD_PIVOT"
    else:
        return "TRANSITION"

regime = classify_regime(yield_trend, dxy_trend)

# --------------------------------------------------
# SAFER EARLY PIVOT (FILTERED)
# --------------------------------------------------
# BUG FIX: original condition required regime == "QT" (which by
# classify_regime's own definition requires yield_trend > 0) AND
# yield_trend < 0 in the same branch -- a contradiction that could never
# be true, so EARLY_PIVOT was dead code. An "early pivot" is better
# understood as liquidity expanding while yields/dollar direction are
# still ambiguous (i.e. regime == "TRANSITION"), so we gate on that
# instead.
if liq_trend > 0.01 and yield_trend < 0 and regime == "TRANSITION":
    regime = "EARLY_PIVOT"

# --------------------------------------------------
# DCA LOGIC
# --------------------------------------------------
# GAP FIX: previously these were hardcoded absolute thresholds
# (liq_trend > 0.05 / > 0) with no relationship to what's actually normal
# for this series historically. A 5% liquidity swing might be enormous in
# a calm regime or unremarkable in a volatile one -- the threshold doesn't
# adapt. Instead, rank the current liq_trend against its own full history
# (percentile) so "HIGH DCA" means "liquidity impulse is genuinely strong
# relative to its own past," not an arbitrary fixed number.
def compute_dca_mode(current_trend, trend_history, min_history=10):
    if trend_history is None or len(trend_history.dropna()) < min_history:
        # Not enough history to rank against -- default to caution rather
        # than a possibly-misleading confident label.
        return "LOW / PAUSE (insufficient history)"

    hist = trend_history.dropna()
    percentile = (hist < current_trend).mean()  # fraction of history below current value

    if percentile >= 0.70:
        return "HIGH DCA"
    elif percentile >= 0.40:
        return "MEDIUM DCA"
    else:
        return "LOW / PAUSE"

dca_mode = compute_dca_mode(liq_trend, liq_impulse)

# --------------------------------------------------
# TRIGGER-SIGNAL OVERLAY (heuristic, NOT backtested or validated)
# --------------------------------------------------
# Everything below is a second, more opinionated lens layered on top of
# the validated System Phase / Regime / DCA Mode logic above. These are
# unvalidated heuristics with hand-picked thresholds -- useful as
# additional context, not as proof of anything. They are shown alongside
# (not instead of) the primary signals so disagreements between the two
# lenses are visible rather than silently resolved.

FORCED_LIQUIDATION_CREDIT_THRESHOLD = 0.10  # below the 0.15 STRESS SPIKE bar --
                                              # catches credit deteriorating fast
                                              # even before it crosses into official stress

def distribution_trap(dxy_trend_val, credit_trend_val_, liq_trend_val):
    """
    Heuristic: dollar rising + credit NOT confirming stress + liquidity
    falling. One reading of this combination is 'quiet distribution' --
    risk being transferred while headline conditions look calm.
    NOTE: this is the same input combination that detect_system_phase()
    calls NORMAL by design (it requires credit to confirm before
    escalating). The two signals can and will disagree -- that's
    intentional, not a bug. They represent different philosophies:
    'wait for confirmation' vs 'calm itself is the warning sign'.
    """
    return dxy_trend_val > 0 and credit_trend_val_ <= 0 and liq_trend_val < 0

def forced_liquidation_signal(credit_trend_val_, liq_acceleration_val,
                                threshold=FORCED_LIQUIDATION_CREDIT_THRESHOLD):
    """
    Heuristic: credit widening meaningfully AND liquidity contraction still
    accelerating (not bottoming). Reads as stress moving from voluntary
    to forced -- sellers who have to sell, not choose to.
    """
    return credit_trend_val_ > threshold and liq_acceleration_val < 0

def front_run_pivot(liq_trend_val, liq_acceleration_val, yield_trend_val):
    """
    Heuristic: liquidity expanding AND accelerating, while yields aren't
    rising (no fear-driven Treasury selloff offsetting it). Reads as
    liquidity turning before the broader narrative catches up.
    """
    return liq_trend_val > 0 and liq_acceleration_val > 0 and yield_trend_val <= 0

is_distribution_trap = distribution_trap(dxy_trend, credit_trend_val, liq_trend)
is_forced_liquidation = forced_liquidation_signal(credit_trend_val, liq_acceleration)
is_pivot_signal = front_run_pivot(liq_trend, liq_acceleration, yield_trend)

# --------------------------------------------------
# TRIGGER LABEL CONSTANTS
# --------------------------------------------------
# Single source of truth for the trigger-name strings. resolve_action() below
# and rebalance_suggestion_with_trigger() further down both branch on these --
# defining them once here means renaming a trigger can't silently desync the
# two switch statements the way two independently-typed string literals could.
TRIGGER_FORCED_LIQ = "FORCED LIQUIDATION"
TRIGGER_DIST_TRAP = "DISTRIBUTION TRAP"
TRIGGER_PIVOT = "PIVOT SIGNAL"
TRIGGER_SYSTEM_PHASE = "SYSTEM PHASE"

# --------------------------------------------------
# DISTRIBUTION TRAP SCORE (graded view of the same boolean above)
# --------------------------------------------------
# DESIGN CONSTRAINT: this must never show "confirmed" while the
# is_distribution_trap badge says "not triggered" -- that would be the same
# self-contradicting-dashboard bug as the old rebalance suggestion. So the
# score is built from the *same three inputs and same cutoffs* as
# distribution_trap() above (dxy>0 / credit<=0 / liq<0 -- 25 pts each,
# +10 bonus for accelerating contraction), which makes 75 the mathematical
# floor whenever all three are true. As a second, explicit safety net (in
# case anyone changes the point values later without re-deriving this), any
# case where is_distribution_trap is False is hard-capped below the
# "CONFIRMED" band regardless of how the arithmetic works out.
def distribution_trap_score(dxy_trend_val, credit_trend_val_, liq_trend_val,
                             liq_acceleration_val, is_trap,
                             threshold=FORCED_LIQUIDATION_CREDIT_THRESHOLD):
    score = 0
    if dxy_trend_val > 0:
        score += 25
    if credit_trend_val_ <= 0:
        score += 25
    elif credit_trend_val_ < threshold:
        score += 10          # widening a little, but not yet past the stress bar
    if liq_trend_val < 0:
        score += 25
    if liq_acceleration_val < 0:
        score += 10          # contraction still accelerating, not bottoming

    if not is_trap:
        score = min(score, 70)   # hard invariant, see design note above

    return score

def distribution_trap_grade(score):
    if score >= 75:
        return "CONFIRMED"
    elif score >= 50:
        return "ELEVATED"
    elif score >= 25:
        return "WATCH"
    return "LOW"

dist_score = distribution_trap_score(dxy_trend, credit_trend_val, liq_trend,
                                      liq_acceleration, is_distribution_trap)
dist_grade = distribution_trap_grade(dist_score)

# --------------------------------------------------
# POSITIONING SCORE (optional overlay -- see sidebar inputs)
# --------------------------------------------------
# UNLIKE distribution_trap_score above, this has no boolean counterpart to
# stay consistent with -- it's a new, standalone heuristic, built entirely
# from the manual sidebar inputs. Treat it accordingly: it's an estimate of
# an estimate, not a validated signal, and it's fully inert (positioning_enabled
# == False) unless you deliberately turn it on and enter today's numbers.
def compute_positioning_score(concentration, breadth, vol_ratio):
    score = 0
    if concentration > 0.30:
        score += 30
    elif concentration > 0.25:
        score += 15

    if breadth < 0.4:
        score += 30
    elif breadth < 0.5:
        score += 15

    if vol_ratio < 0.8:
        score += 20
    elif vol_ratio < 1.0:
        score += 10

    return min(score, 100)

def positioning_state(score):
    if score >= 70:
        return "CROWDED"
    elif score >= 40:
        return "ELEVATED"
    elif score >= 20:
        return "NEUTRAL"
    return "UNDEROWNED"

positioning_score = (
    compute_positioning_score(concentration_pct / 100, breadth_pct / 100, vol_ratio_input)
    if positioning_enabled else 0
)
positioning_grade = positioning_state(positioning_score) if positioning_enabled else "OFF"

def execution_playbook(phase):
    """
    Illustrative capital-stance suggestions keyed to System Phase.
    These are starting points to adapt to your own risk tolerance and
    position sizing -- not validated by backtesting within this engine,
    and not a substitute for your own judgment.
    """
    playbooks = {
        "SYSTEM BREAK": {
            "stance": "MAX AGGRESSION (highest conviction tier)",
            "notes": [
                "Largest planned deployment tranche of your cash reserve",
                "Prioritize core continuous-lane names (physical monopolies, royalties) first",
                "Consider increasing BTC allocation within your existing risk budget",
            ],
        },
        "FRACTURE": {
            "stance": "STAGGERED DEPLOYMENT",
            "notes": [
                "Partial deployment tranche, held back for further confirmation",
                "Favor infra + royalties over high-beta names",
                "Wait for credit to either stabilize or worsen before sizing up further",
            ],
        },
        "CREDIT STRESS": {
            "stance": "CAUTIOUS -- CREDIT-LED WARNING",
            "notes": [
                "Credit is flagging stress liquidity/dollar haven't confirmed yet",
                "Reduce new risk-taking until liq/dollar either confirm or the credit signal fades",
            ],
        },
        "LIQUIDITY EXPANSION": {
            "stance": "RISK ON",
            "notes": [
                "Full continuous-lane deployment",
                "Conditional/cyclical buckets can deploy on their own dip triggers",
                "Let existing winners run rather than trimming early",
            ],
        },
        "EXPANSION (credit lagging)": {
            "stance": "RISK ON, WATCH CREDIT",
            "notes": [
                "Liquidity/dollar support risk-taking, credit hasn't confirmed",
                "Proceed but keep an eye on credit_status for confirmation or reversal",
            ],
        },
        "FRAGILE EXPANSION": {
            "stance": "PARTIAL RISK",
            "notes": [
                "Hold core positions, avoid adding aggressively",
                "Elevated cash buffer -- this combination has historically been unstable",
            ],
        },
        "NORMAL": {
            "stance": "DEFENSIVE BUILD",
            "notes": [
                "Continuous lane only (hard assets, royalties, physical monopolies, BTC/gold at target)",
                "Conditional/cyclical lane stays parked for its own dip triggers",
                "No aggressive positioning either direction",
            ],
        },
    }
    return playbooks.get(phase, playbooks["NORMAL"])

# --------------------------------------------------
# PRIORITY RESOLUTION
# --------------------------------------------------
# When more than one trigger fires, this defines which one drives the
# headline "Recommended Stance". All raw signals remain visible on the
# dashboard regardless -- this only decides which one gets top billing.
def resolve_action():
    if is_forced_liquidation:
        return (TRIGGER_FORCED_LIQ, "AGGRESSIVE BUY SEQUENCE",
                 "Credit widening past threshold while liquidity contraction is still accelerating -- "
                 "reads as forced (not voluntary) selling pressure.")
    if is_distribution_trap:
        return (TRIGGER_DIST_TRAP, "HOLD -- DO NOT ADD RISK",
                 "Dollar rising, liquidity falling, but credit hasn't confirmed stress -- "
                 "on this lens, calm credit here is itself the caution flag, not reassurance. "
                 "Contradicts System Phase's NORMAL reading by design; see note above.")
    if is_pivot_signal:
        return (TRIGGER_PIVOT, "ACCUMULATE RISK EARLY",
                 "Liquidity expanding and accelerating while yields aren't rising -- "
                 "reads as liquidity turning before the broader narrative confirms it.")
    playbook = execution_playbook(system_phase)
    return (TRIGGER_SYSTEM_PHASE, playbook["stance"],
             f"No override trigger fired -- falling back to System Phase ({system_phase}).")

resolved_trigger, resolved_stance, resolved_rationale = resolve_action()

# --------------------------------------------------
# SOVEREIGN 15-YEAR ENGINE (built fresh -- nothing here existed before)
# --------------------------------------------------
# DESIGN NOTE: the source document this was requested from described
# "V3/V4" components (multi_horizon_liquidity, compute_macro_score,
# drawdown_protection, etc.) as if they were already-built, validated
# layers this was extending. They were not -- none of that code existed
# in this file. Everything below is built from scratch, using only the
# FRED series and signals already validated earlier in this file, with
# explicit formulas rather than asserted black-box behavior.
#
# SCOPE CAVEAT: this is a decision-support policy framework, not an
# autonomous trading system. It places no trades, connects to no
# brokerage, and should not be treated as financial advice -- it turns
# your own chosen policy (the thresholds and weights below, which you can
# and should edit) into a consistent, repeatable readout. You are the
# governor of this system, not the other way around.

# --- 1) MULTI-HORIZON LIQUIDITY ---
# Same net_liquidity series, three different lookback lenses. "15-year"
# describes your intended holding horizon, not the data window itself --
# FRED's WALCL/RRP/TGA history only goes back to start_date (2015), so the
# "long" horizon below is capped by ~11 years of actual data, not 15.
def liquidity_trend_series(net_liq_series, window_weeks, smooth_weeks):
    if net_liq_series.empty:
        return pd.Series(dtype=float)
    raw = net_liq_series.pct_change(window_weeks)
    return raw.rolling(smooth_weeks).mean()

liq_short_series = liquidity_trend_series(net_liquidity, 4, 2)     # ~1 month
liq_medium_series = liquidity_trend_series(net_liquidity, 13, 4)   # ~1 quarter
liq_long_series = liquidity_trend_series(net_liquidity, 52, 8)     # ~1 year

def _last_or_zero(s):
    d = s.dropna()
    return d.iloc[-1] if not d.empty else 0

liq_multi = {
    "short": _last_or_zero(liq_short_series),
    "medium": _last_or_zero(liq_medium_series),
    "long": _last_or_zero(liq_long_series),
}

# --- 2) MACRO COMPOSITE SCORE ---
# Ranks each signal's current trend against ITS OWN history (percentile,
# same technique as compute_dca_mode above), then combines with fixed
# weights into a single -100..+100 score. Weights favor liquidity and
# credit (40%/30%) over yield and dollar (15%/15%) -- consistent with the
# earlier discussion in this conversation that liquidity direction and
# credit stress are the more reliable leading signals, while yield/dollar
# pivots are noisier to trust for timing. Edit MACRO_SCORE_WEIGHTS below
# if you disagree with that prioritization -- it's a stated assumption,
# not a proven one.
MACRO_SCORE_WEIGHTS = {"liquidity": 0.40, "credit": 0.30, "yield": 0.15, "dollar": 0.15}

def trend_series(series, window=TREND_WINDOW, smooth=SMOOTH_WINDOW):
    if series.empty:
        return pd.Series(dtype=float)
    raw = series.pct_change(window)
    return raw.rolling(smooth).mean()

yield_trend_series = trend_series(y10_a)
dxy_trend_series = trend_series(usd_broad_a)
credit_trend_series = trend_series(credit_spread_a)

def percentile_rank(current, hist_series, min_history=10):
    hist = hist_series.dropna()
    if len(hist) < min_history:
        return 0.5  # neutral if not enough history to rank against
    return (hist < current).mean()

liq_pct = percentile_rank(liq_multi["medium"], liq_medium_series)
credit_pct = percentile_rank(credit_trend_val, credit_trend_series)
yield_pct = percentile_rank(yield_trend, yield_trend_series)
dxy_pct = percentile_rank(dxy_trend, dxy_trend_series)

# Convert each percentile (0..1) to a signed -1..+1 contribution.
# Liquidity: high percentile (strong expansion) = positive for risk.
# Credit/Yield/Dollar: high percentile (spreads/yields/dollar rising
# strongly) = tightening = negative for risk, in this framework.
score_components = {
    "liquidity": (liq_pct - 0.5) * 2,
    "credit":   -(credit_pct - 0.5) * 2,
    "yield":    -(yield_pct - 0.5) * 2,
    "dollar":   -(dxy_pct - 0.5) * 2,
}

def compute_macro_score(components, weights):
    return sum(components[k] * weights[k] for k in weights) * 100

macro_score = compute_macro_score(score_components, MACRO_SCORE_WEIGHTS)

def compute_confidence(components, score):
    """Confidence = what fraction of the 4 components agree in sign with
    the overall score. High agreement = the signals are telling the same
    story. Low agreement = the score is a product of conflicting inputs
    and deserves more skepticism."""
    if score == 0:
        return "LOW"
    agree = sum(1 for c in components.values() if (c > 0) == (score > 0))
    frac = agree / len(components)
    if frac >= 0.75:
        return "HIGH"
    elif frac >= 0.5:
        return "MEDIUM"
    return "LOW"

confidence = compute_confidence(score_components, macro_score)

def map_score_to_phase(score):
    if score >= 40:
        return "STRONG EXPANSION"
    elif score >= 15:
        return "EXPANSION"
    elif score > -15:
        return "NEUTRAL"
    elif score > -40:
        return "CONTRACTION"
    return "STRONG CONTRACTION"

macro_phase_v2 = map_score_to_phase(macro_score)

# --- 3) TARGET ALLOCATION POLICY (illustrative default -- EDIT THIS) ---
# This table is a stated, editable POLICY, not a discovered truth. It
# expresses "if I trust the macro read, how much of my risk sleeve would
# I want deployed" at each phase/confidence combination. Change these
# numbers to match your own risk tolerance before treating the output as
# meaningful to you.
ALLOCATION_POLICY = {
    ("STRONG EXPANSION", "HIGH"): 0.90, ("STRONG EXPANSION", "MEDIUM"): 0.80, ("STRONG EXPANSION", "LOW"): 0.70,
    ("EXPANSION", "HIGH"): 0.80,        ("EXPANSION", "MEDIUM"): 0.70,        ("EXPANSION", "LOW"): 0.60,
    ("NEUTRAL", "HIGH"): 0.60,          ("NEUTRAL", "MEDIUM"): 0.55,          ("NEUTRAL", "LOW"): 0.50,
    ("CONTRACTION", "HIGH"): 0.40,      ("CONTRACTION", "MEDIUM"): 0.45,      ("CONTRACTION", "LOW"): 0.50,
    ("STRONG CONTRACTION", "HIGH"): 0.20, ("STRONG CONTRACTION", "MEDIUM"): 0.30, ("STRONG CONTRACTION", "LOW"): 0.40,
}

def capital_allocation_target(phase, conf):
    return ALLOCATION_POLICY.get((phase, conf), 0.55)

allocation_target = capital_allocation_target(macro_phase_v2, confidence)

# --- 4) LIQUIDITY KILL SWITCH ---
# A circuit breaker, not an order. Fires only when SHORT-horizon liquidity
# is meaningfully negative (worse than -3%) AND still accelerating
# downward -- i.e. actively getting worse, not just currently negative.
def liquidity_kill_switch(liq_short, liq_accel, threshold=-0.03):
    return liq_short < threshold and liq_accel < 0

kill_switch_active = liquidity_kill_switch(liq_multi["short"], liq_acceleration)

# --- 5) DISCIPLINE TRACKER ---
# Compares YOUR reported current_alloc (sidebar input) against the
# model's target_alloc. This can only ever be as honest as the number you
# entered -- there is no way for this engine to independently verify your
# real brokerage position.
def discipline_check(target, actual):
    deviation = abs(target - actual)
    if deviation > 0.20:
        return "VIOLATION"
    elif deviation > 0.10:
        return "DRIFT"
    return "ALIGNED"

discipline_status = discipline_check(allocation_target, current_alloc)

# --- 6) SYSTEM GOVERNOR ---
# Final haircut layer. Only ever REDUCES the suggested target relative to
# what the raw policy table said -- it never increases it. This is a
# deliberate asymmetry: the governor's job is to add caution, not
# aggression.
#
# GAP FIX (target itself, not just the rebalance sentence): previously this
# only looked at kill_switch/discipline, so governed_target could still read
# e.g. "55%" (above current_alloc) during an active Distribution Trap, even
# though rebalance_note said "NO ADD". Capping the target at current_alloc
# during a confirmed trap fixes the number itself, not just the sentence
# next to it.
#
# GAP FIX (USD mid-spectrum): the dollar previously only mattered in two
# extremes -- a mild 15% weight buried inside macro_score, or a hard binary
# trigger inside distribution_trap(). Nothing damped exposure in between --
# e.g. USD rising meaningfully on its own, with liquidity/credit not (yet)
# bad enough to complete the trap. Added a mild trim once |dxy_trend|
# clears the same 2% magnitude bar used elsewhere in this file
# (REGIME_MAGNITUDE_THRESHOLD), skipped whenever Distribution Trap is
# already the driving trigger so the same dollar signal isn't penalized
# twice by two different mechanisms.
#
# ADDITION (positioning overlay): a new, independent haircut for crowded
# positioning -- see the sidebar inputs and compute_positioning_score()
# above. Fully inert unless positioning_enabled is turned on. JUDGMENT
# CALL: skipped during FORCED LIQUIDATION specifically -- crowded longs
# unwinding is generally *the mechanism that produces* forced liquidation
# in the first place, so an extra "reduce for crowding" haircut stacked on
# top of that trigger's own "aggressive buy the capitulation" stance would
# be fighting itself rather than adding independent information. It still
# stacks normally with Distribution Trap, USD damping, kill-switch, and
# discipline, since crowding is genuinely orthogonal to those.
#
# STRUCTURE CHANGE: this used to be a mutually-exclusive if/elif chain that
# only ever reported the FIRST matching reason, silently hiding any other
# that was also true (e.g. a discipline violation happening at the same
# time as a kill-switch would only ever surface the kill-switch note). With
# five independent conditions now possible instead of two, that gets more
# likely to matter, so this now accumulates every applicable haircut
# multiplicatively and reports all of them -- still purely a reduction,
# just no longer able to hide a true reason behind whichever one happens to
# be checked first.
USD_DAMPING_THRESHOLD = REGIME_MAGNITUDE_THRESHOLD  # reuse the existing 2% bar, not a new number
USD_DAMPING_FACTOR = 0.90

def system_governor(target_alloc, kill_switch, discipline, trigger, current_alloc_val, dxy_trend_val,
                     positioning_on, positioning_score_val):
    target = target_alloc
    reasons = []

    if trigger == TRIGGER_DIST_TRAP:
        target = min(target, current_alloc_val)
        reasons.append("Distribution trap active: target capped at your current allocation.")
    elif dxy_trend_val > USD_DAMPING_THRESHOLD:
        target *= USD_DAMPING_FACTOR
        reasons.append(f"Dollar rising >{USD_DAMPING_THRESHOLD*100:.0f}% (not yet a confirmed trap): "
                        f"target trimmed {(1 - USD_DAMPING_FACTOR)*100:.0f}% as early caution.")

    if positioning_on and trigger != TRIGGER_FORCED_LIQ:
        if positioning_score_val >= 70:
            target *= 0.80
            reasons.append("Positioning overlay: crowded (>=70/100) -- target trimmed 20%.")
        elif positioning_score_val >= 40:
            target *= 0.90
            reasons.append("Positioning overlay: elevated (>=40/100) -- target trimmed 10%.")

    if kill_switch:
        target *= 0.5
        reasons.append("Liquidity kill-switch active: target halved.")

    if discipline == "VIOLATION":
        target *= 0.8
        reasons.append("Large deviation from your own reported allocation: target trimmed.")

    if not reasons:
        return target_alloc, "No override applied -- policy target stands as-is."
    return target, " | ".join(reasons)

governed_target, governor_note = system_governor(allocation_target, kill_switch_active, discipline_status,
                                                   resolved_trigger, current_alloc, dxy_trend,
                                                   positioning_enabled, positioning_score)

# --- 7) REBALANCING SUGGESTION ---
# GAP FIX: this used to be computed purely from governed_target vs.
# current_alloc, with no awareness of resolved_trigger. That let the
# dashboard say "HOLD -- DO NOT ADD RISK" (Distribution Trap) in one panel
# and "Consider INCREASING exposure by ~5%" in another -- a direct
# contradiction a user could act on without noticing the override above it.
# This version defers to the same trigger priority as resolve_action(), and
# where it overrides the raw allocation math it says so in the same language
# as Resolved Stance rather than inventing a second, differently-worded verb
# for the same trigger (e.g. it does NOT say "staged" for forced liquidation
# while Resolved Stance separately says "aggressive" -- it explicitly defers
# to that card instead of re-describing the action).
def rebalance_suggestion_with_trigger(current, target, trigger, band=0.05):
    diff = target - current

    if trigger == TRIGGER_DIST_TRAP:
        return ("NO ADD -- distribution trap active; keep the current/target gap as dry "
                "powder until liquidity repairs or credit confirms stress (see Resolved Stance).")

    if trigger == TRIGGER_FORCED_LIQ:
        return ("DEPLOY, BUT IN TRANCHES -- Resolved Stance calls for an aggressive buy "
                "sequence; size it in stages rather than all at once so a further leg down "
                "doesn't exhaust dry powder in one entry.")

    if trigger == TRIGGER_PIVOT and diff > band:
        return f"ACCUMULATE -- consider increasing exposure by ~{diff*100:.1f}% (early pivot signal)."

    # No overriding trigger (or PIVOT SIGNAL with current already at/above
    # target) -- fall back to the plain allocation-gap math.
    if abs(diff) < band:
        return "NO ACTION -- within tolerance band"
    direction = "INCREASING" if diff > 0 else "REDUCING"
    return f"Consider {direction} exposure by ~{abs(diff)*100:.1f}%"

rebalance_note = rebalance_suggestion_with_trigger(current_alloc, governed_target, resolved_trigger)

# --- 8) DYNAMIC PORTFOLIO SPLIT (tilts YOUR actual allocation grid) ---
# Uses the real allocation grid from your uploaded sheet as the base, and
# applies a bounded tilt (max +/-30% relative change, capped so the tilt
# can never dominate the base policy) toward higher-beta sleeves
# (AI/Semis, BTC, EM) when macro_score is positive, and toward defensive
# sleeves (Gold, Cash) when negative.
BASE_GRID = {
    "INFRA": 0.15, "ENERGY_COMMODITY": 0.23, "AI_SEMIS": 0.10,
    "EM": 0.07, "BTC": 0.25, "GOLD": 0.10, "CASH": 0.10,
}
HIGH_BETA_SLEEVES = {"AI_SEMIS", "BTC", "EM"}
DEFENSIVE_SLEEVES = {"GOLD", "CASH"}
MAX_TILT = 0.30  # hard cap: no sleeve can be tilted more than +/-30% relative to its base weight

def tilt_grid(base_grid, score, high_beta, defensive, max_tilt=MAX_TILT):
    tilt_factor = (max(-100, min(100, score)) / 100) * max_tilt  # clamp score defensively
    tilted = {}
    for name, weight in base_grid.items():
        if name in high_beta:
            tilted[name] = weight * (1 + tilt_factor)
        elif name in defensive:
            tilted[name] = weight * (1 - tilt_factor)
        else:
            tilted[name] = weight
    total = sum(tilted.values())
    return {k: v / total for k, v in tilted.items()}  # renormalize to sum to 100%

tilted_grid = tilt_grid(BASE_GRID, macro_score, HIGH_BETA_SLEEVES, DEFENSIVE_SLEEVES)

# --- 9) ALERTS PANEL ---
def generate_alerts(sys_phase, trigger, kill_switch, discipline):
    alerts = []
    if kill_switch:
        alerts.append("🚨 Liquidity kill-switch active — short-horizon liquidity deeply negative and still worsening. Consider pausing new risk deployment.")
    if sys_phase in STRESS_PHASES:
        alerts.append(f"⚠️ System Phase is {sys_phase} — Risk Status reads RISK OFF.")
    if trigger == "FORCED LIQUIDATION":
        alerts.append("⚠️ Forced Liquidation heuristic fired — credit widening fast alongside accelerating liquidity contraction.")
    if discipline == "VIOLATION":
        alerts.append("🧭 Your reported current allocation deviates >20% from the model's target — consider a gradual rebalance, not an abrupt jump.")
    if not alerts:
        alerts.append("✅ No active alerts.")
    return alerts

alerts = generate_alerts(system_phase, resolved_trigger, kill_switch_active, discipline_status)

# --- 10) STATE MEMORY / HISTORY LOG ---
# IMPORTANT HOSTING CAVEAT: this writes to a local CSV file. On many free
# hosting tiers (including Streamlit Community Cloud), the filesystem is
# EPHEMERAL and can be wiped on redeploys or app restarts -- this is NOT
# guaranteed 15-year persistent storage as-is. For genuine long-horizon
# tracking you'd want this pointed at a real durable store (a Google
# Sheet via gspread, Airtable, a hosted Postgres/SQLite file on a
# persistent volume, etc.). Shipping with local CSV here so the mechanism
# is complete and testable; swapping the storage backend is a follow-up,
# not a redesign, when you're ready for it.
import os
HISTORY_FILE = "sovereign_engine_history.csv"

def log_snapshot(as_of, score, phase, target, actual, portfolio_value=None):
    row = pd.DataFrame([{
        "date": as_of, "macro_score": score, "phase": phase,
        "target_alloc": target, "current_alloc": actual,
        "portfolio_value": portfolio_value if portfolio_value else None,
    }])
    write_header = not os.path.exists(HISTORY_FILE)
    row.to_csv(HISTORY_FILE, mode="a", header=write_header, index=False)

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            return pd.read_csv(HISTORY_FILE, parse_dates=["date"])
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

if log_snapshot_clicked:
    log_snapshot(as_of_date, macro_score, macro_phase_v2, governed_target, current_alloc,
                 portfolio_value_input if portfolio_value_input > 0 else None)
    st.sidebar.success("Snapshot logged.")

history_df = load_history()

# --- 11) DRAWDOWN PROTECTION (from your own logged portfolio values) ---
def drawdown_protection(value_series, threshold=0.20):
    vals = value_series.dropna()
    if vals.empty:
        return "NO DATA", 0.0
    peak = vals.cummax()
    dd = (vals - peak) / peak
    current_dd = dd.iloc[-1]
    status = "DRAWDOWN PROTECTION ACTIVE" if current_dd <= -threshold else "NORMAL"
    return status, current_dd

if not history_df.empty and "portfolio_value" in history_df.columns and history_df["portfolio_value"].notna().any():
    drawdown_status, current_drawdown = drawdown_protection(history_df["portfolio_value"])
else:
    drawdown_status, current_drawdown = "NO DATA", 0.0


def format_liquidity(x_millions):
    # BUG FIX: FRED liquidity series are denominated in $ millions already.
    # The old version compared that millions-scale number directly against
    # 1e9 / 1e12 thresholds meant for raw dollars, so it could never reach
    # the "B" or "T" branches and always printed misleadingly small "M"
    # values. Convert to raw dollars first, then bucket.
    x = x_millions * 1e6
    if abs(x) >= 1e12:
        return f"${x/1e12:.2f}T"
    elif abs(x) >= 1e9:
        return f"${x/1e9:.0f}B"
    return f"${x/1e6:.0f}M"

# --------------------------------------------------
# STYLE MAPS (map computed states -> color/icon, purely presentational)
# --------------------------------------------------
PHASE_STYLE = {
    "SYSTEM BREAK":              {"accent": "#ff4d4d", "bg": "rgba(255,77,77,0.08)",  "icon": "🚨"},
    "FRACTURE":                  {"accent": "#ff8c42", "bg": "rgba(255,140,66,0.08)", "icon": "⚠️"},
    "CREDIT STRESS":             {"accent": "#ffb84d", "bg": "rgba(255,184,77,0.08)", "icon": "⚠️"},
    "FRAGILE EXPANSION":         {"accent": "#e8d44d", "bg": "rgba(232,212,77,0.08)", "icon": "🌀"},
    "EXPANSION (credit lagging)":{"accent": "#8de07a", "bg": "rgba(141,224,122,0.08)","icon": "📈"},
    "LIQUIDITY EXPANSION":       {"accent": "#4dd68c", "bg": "rgba(77,214,140,0.08)", "icon": "✅"},
    "NORMAL":                    {"accent": "#7fa8c9", "bg": "rgba(127,168,201,0.08)","icon": "➖"},
}
REGIME_STYLE = {
    "QT":           {"accent": "#ff8c42", "bg": "rgba(255,140,66,0.06)", "icon": "🔻"},
    "SOFT_PIVOT":   {"accent": "#8de07a", "bg": "rgba(141,224,122,0.06)","icon": "🌤️"},
    "HARD_PIVOT":   {"accent": "#ffb84d", "bg": "rgba(255,184,77,0.06)", "icon": "⚡"},
    "EARLY_PIVOT":  {"accent": "#4dd6c9", "bg": "rgba(77,214,201,0.06)", "icon": "🔔"},
    "TRANSITION":   {"accent": "#9aa5b1", "bg": "rgba(154,165,177,0.06)","icon": "↔️"},
}
CREDIT_STYLE = {
    "STRESS SPIKE": {"accent": "#ff4d4d", "bg": "rgba(255,77,77,0.06)", "icon": "🔴"},
    "WIDENING":     {"accent": "#ffb84d", "bg": "rgba(255,184,77,0.06)","icon": "🟠"},
    "STABLE":       {"accent": "#4dd68c", "bg": "rgba(77,214,140,0.06)","icon": "🟢"},
}
DCA_STYLE = {
    "HIGH DCA":                          {"accent": "#4dd68c", "bg": "rgba(77,214,140,0.06)"},
    "MEDIUM DCA":                        {"accent": "#ffb84d", "bg": "rgba(255,184,77,0.06)"},
    "LOW / PAUSE":                       {"accent": "#9aa5b1", "bg": "rgba(154,165,177,0.06)"},
    "LOW / PAUSE (insufficient history)":{"accent": "#6b7385", "bg": "rgba(107,115,133,0.06)"},
}
RISK_STYLE = {
    "RISK OFF": {"accent": "#ff4d4d", "bg": "rgba(255,77,77,0.08)"},
    "ACTIVE":   {"accent": "#4dd68c", "bg": "rgba(77,214,140,0.08)"},
}

def get_style(mapping, key, default_accent="#7fa8c9", default_bg="rgba(127,168,201,0.06)"):
    return mapping.get(key, {"accent": default_accent, "bg": default_bg, "icon": ""})

def arrow_html(x, up_color="#4dd68c", down_color="#ff6b6b", flat_color="#9aa5b1"):
    if x > 0:
        return f'<span style="color:{up_color};">▲</span>'
    elif x < 0:
        return f'<span style="color:{down_color};">▼</span>'
    return f'<span style="color:{flat_color};">→</span>'

def metric_card(label, value, delta_pct, note="", icon=""):
    accent = "#4dd68c" if delta_pct > 0 else ("#ff6b6b" if delta_pct < 0 else "#9aa5b1")
    arrow = arrow_html(delta_pct)
    html = f"""
    <div class="sme-card" style="--accent:{accent};">
        <div class="lbl">{icon} {label}</div>
        <div class="val">{value}</div>
        <div class="delta">{delta_pct*100:+.2f}% {arrow}</div>
        {f'<div class="note">{note}</div>' if note else ''}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

def badge_card(label, value, style, note=""):
    html = f"""
    <div class="sme-badge" style="--accent:{style['accent']}; --bg:{style['bg']}; background:{style['bg']};">
        <div class="lbl">{label}</div>
        <div class="val">{style.get('icon','')} {value}</div>
        {f'<div class="note">{note}</div>' if note else ''}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------
if as_of_date is not None:
    st.markdown(f'<div class="sme-asof">📅 Data as of {as_of_date.strftime("%Y-%m-%d")} '
                f'(forward-filled to common calendar)</div>', unsafe_allow_html=True)

# --- HERO: the one thing you should see first ---
phase_style = get_style(PHASE_STYLE, system_phase)
st.markdown(f"""
<div class="sme-hero" style="--accent:{phase_style['accent']}; background:{phase_style['bg']};">
    <div>
        <div class="tag">Current System Phase</div>
        <div class="phase">{phase_style['icon']} {system_phase}</div>
    </div>
    <div class="side">
        Regime &nbsp;<b>{REGIME_STYLE.get(regime,{}).get('icon','')} {regime}</b><br/>
        DCA Mode &nbsp;<b>{dca_mode}</b><br/>
        Liquidity Momentum &nbsp;<b>{liq_momentum}</b>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="sme-section-label">📊 Macro Chokepoints</div>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1:
    metric_card("Liquidity", format_liquidity(latest_liquidity), liq_trend, icon="💧")
with c2:
    metric_card("10Y Yield", f"{latest_yield:.2f}%", yield_trend, icon="📉")
with c3:
    metric_card("USD Index (Fed Broad-AFE)", f"{latest_usd_broad:.2f}", dxy_trend, icon="💵",
                note="Fed's Nominal Advanced Foreign Economies index — NOT the ICE DXY quote. Levels aren't comparable; trend direction is.")
with c4:
    metric_card("Credit Spread", f"{latest_credit:.2f}%", credit_trend_val, icon="🏦")

st.markdown('<div class="sme-section-label">🧭 System State</div>', unsafe_allow_html=True)

c5, c6, c7, c8 = st.columns(4)
with c5:
    badge_card("Regime", regime, get_style(REGIME_STYLE, regime))
with c6:
    badge_card("Credit Condition", credit_status, get_style(CREDIT_STYLE, credit_status))
with c7:
    badge_card("System Phase", system_phase, phase_style)
with c8:
    badge_card("Liquidity Momentum", liq_momentum,
                {"accent": "#4dd68c" if liq_acceleration > 0 else "#ff6b6b", "bg": "rgba(127,168,201,0.06)"},
                note=f"acceleration: {liq_acceleration*100:+.2f}%")

st.markdown('<div class="sme-section-label">⚙️ Execution</div>', unsafe_allow_html=True)

risk_status = "RISK OFF" if system_phase in STRESS_PHASES else "ACTIVE"

col1, col2 = st.columns(2)
with col1:
    badge_card("DCA Mode", dca_mode, get_style(DCA_STYLE, dca_mode))
with col2:
    badge_card("Risk Status", risk_status, get_style(RISK_STYLE, risk_status))

# --------------------------------------------------
# TRIGGER-SIGNAL OVERLAY (heuristic second lens)
# --------------------------------------------------
st.markdown('<div class="sme-section-label">🎯 Trigger Signals (heuristic overlay -- unvalidated, not backtested)</div>',
            unsafe_allow_html=True)
st.caption("These are hand-tuned heuristics layered on top of the validated System Phase logic above. "
           "They can disagree with System Phase by design (see Distribution Trap note) -- "
           "treat as additional context for your own judgment, not as proof.")

TRIGGER_STYLE_ON = {"accent": "#ff8c42", "bg": "rgba(255,140,66,0.08)", "icon": "🔥"}
TRIGGER_STYLE_OFF = {"accent": "#4dd68c", "bg": "rgba(77,214,140,0.06)", "icon": "—"}

t1, t2, t3 = st.columns(3)
with t1:
    badge_card("Distribution Trap", "ACTIVE" if is_distribution_trap else "not triggered",
               TRIGGER_STYLE_ON if is_distribution_trap else TRIGGER_STYLE_OFF,
               note="dollar↑ + credit calm + liquidity↓")
with t2:
    badge_card("Forced Liquidation", "ACTIVE" if is_forced_liquidation else "not triggered",
               TRIGGER_STYLE_ON if is_forced_liquidation else TRIGGER_STYLE_OFF,
               note=f"credit widening > {FORCED_LIQUIDATION_CREDIT_THRESHOLD*100:.0f}% + liq accel↓")
with t3:
    badge_card("Front-Run Pivot", "ACTIVE" if is_pivot_signal else "not triggered",
               TRIGGER_STYLE_ON if is_pivot_signal else TRIGGER_STYLE_OFF,
               note="liq↑ + accelerating + yields not rising")

dist_score_color = (
    "#ff4d4d" if dist_grade == "CONFIRMED" else
    "#ff8c42" if dist_grade == "ELEVATED" else
    "#ffb84d" if dist_grade == "WATCH" else
    "#4dd68c"
)
badge_card(
    "Distribution Trap Score", f"{dist_score}/100 -- {dist_grade}",
    {"accent": dist_score_color, "bg": "rgba(127,168,201,0.06)"},
    note=("Graded view of the badge above, same three inputs (dollar / credit / liquidity) "
          "plus a liquidity-acceleration bonus. CONFIRMED (>=75) is only reachable when "
          "Distribution Trap above also reads ACTIVE -- this can go no higher than ELEVATED "
          "otherwise, by construction, so the two can't contradict each other.")
)

if positioning_enabled:
    pos_color = (
        "#ff4d4d" if positioning_grade == "CROWDED" else
        "#ff8c42" if positioning_grade == "ELEVATED" else
        "#ffb84d" if positioning_grade == "NEUTRAL" else
        "#4dd68c"
    )
    badge_card(
        "Positioning Overlay", f"{positioning_score}/100 -- {positioning_grade}",
        {"accent": pos_color, "bg": "rgba(127,168,201,0.06)"},
        note=("Built entirely from the manual sidebar estimates (concentration / breadth / "
              "vol ratio) -- not fetched data. Suppressed in the governor during Forced "
              "Liquidation (see code comment: crowding unwinding is usually the cause of "
              "that trigger, not a separate reason to compound it).")
    )
else:
    badge_card(
        "Positioning Overlay", "OFF",
        {"accent": "#6b7385", "bg": "rgba(107,115,133,0.06)"},
        note="Optional manual overlay -- enable in the sidebar and enter today's estimates to use it."
    )

st.markdown(f"""
<div class="sme-hero" style="--accent:#e8d44d; background:rgba(232,212,77,0.06);">
    <div>
        <div class="tag">Resolved Stance (priority: forced liquidation → distribution trap → pivot → system phase)</div>
        <div class="phase" style="font-size:24px;">{resolved_stance}</div>
        <div style="font-size:13px;color:#8892a6;margin-top:6px;max-width:600px;">{resolved_rationale}</div>
    </div>
    <div class="side">
        Driving trigger &nbsp;<b>{resolved_trigger}</b>
    </div>
</div>
""", unsafe_allow_html=True)

with st.expander("Playbook notes for current System Phase"):
    pb = execution_playbook(system_phase)
    st.markdown(f"**Stance:** {pb['stance']}")
    for n in pb["notes"]:
        st.markdown(f"- {n}")
    st.caption("Illustrative starting points, not validated recommendations. Adjust to your own risk tolerance.")

# --------------------------------------------------
# SOVEREIGN 15-YEAR ENGINE (dashboard section)
# --------------------------------------------------
st.markdown('<div class="sme-section-label">🏛️ Sovereign 15-Year Engine</div>', unsafe_allow_html=True)
st.caption("A policy framework built from the signals above, not a new data source and not an autonomous "
           "trading system. No trades are placed. Every threshold and weight here is an editable assumption "
           "you set in the code -- treat the output as a consistent readout of YOUR policy, not a discovered truth. "
           "Not financial advice.")

s1, s2, s3, s4 = st.columns(4)
score_color = "#4dd68c" if macro_score > 0 else ("#ff6b6b" if macro_score < 0 else "#9aa5b1")
with s1:
    badge_card("Macro Score", f"{macro_score:+.1f}", {"accent": score_color, "bg": "rgba(127,168,201,0.06)"},
               note="-100 (max contraction) to +100 (max expansion)")
with s2:
    badge_card("Macro Phase", macro_phase_v2, {"accent": score_color, "bg": "rgba(127,168,201,0.06)"})
with s3:
    conf_color = {"HIGH": "#4dd68c", "MEDIUM": "#ffb84d", "LOW": "#ff8c42"}.get(confidence, "#9aa5b1")
    badge_card("Confidence", confidence, {"accent": conf_color, "bg": "rgba(127,168,201,0.06)"},
               note="% of the 4 signals agreeing with the overall score direction")
with s4:
    ks_style = {"accent": "#ff4d4d", "bg": "rgba(255,77,77,0.08)"} if kill_switch_active else {"accent": "#4dd68c", "bg": "rgba(77,214,140,0.06)"}
    badge_card("Liquidity Kill-Switch", "ACTIVE" if kill_switch_active else "not active", ks_style)

st.markdown('<div class="sme-section-label">⚖️ Allocation Policy Readout</div>', unsafe_allow_html=True)

a1, a2, a3, a4 = st.columns(4)
with a1:
    metric_card("Policy Target", f"{allocation_target*100:.0f}%", 0, icon="🎯",
               note="from ALLOCATION_POLICY table, before governor")
with a2:
    metric_card("Governed Target", f"{governed_target*100:.0f}%", 0, icon="🏛️", note=governor_note)
with a3:
    metric_card("Your Reported Current", f"{current_alloc*100:.0f}%", 0, icon="📍",
               note="from sidebar input")
with a4:
    disc_color = {"ALIGNED": "#4dd68c", "DRIFT": "#ffb84d", "VIOLATION": "#ff4d4d"}.get(discipline_status, "#9aa5b1")
    badge_card("Discipline Status", discipline_status, {"accent": disc_color, "bg": "rgba(127,168,201,0.06)"})

st.info(f"**Rebalance suggestion:** {rebalance_note}")

st.markdown('<div class="sme-section-label">🧭 Multi-Horizon Liquidity</div>', unsafe_allow_html=True)
h1, h2, h3 = st.columns(3)
for col, (label, key) in zip((h1, h2, h3), [("Short (~1mo)", "short"), ("Medium (~1qtr)", "medium"), ("Long (~1yr)", "long")]):
    with col:
        metric_card(label, f"{liq_multi[key]*100:+.2f}%", liq_multi[key], icon="💧")

st.markdown('<div class="sme-section-label">📢 Alerts</div>', unsafe_allow_html=True)
for a in alerts:
    st.markdown(f"- {a}")

st.markdown('<div class="sme-section-label">🧩 Tilted Portfolio Grid (from your uploaded allocation sheet)</div>', unsafe_allow_html=True)
st.caption(f"Base weights tilted +/-{MAX_TILT*100:.0f}% max toward AI/Semis, BTC, EM (high-beta) or "
           f"Gold, Cash (defensive) based on the current macro score. Renormalized to sum to 100%.")
grid_df = pd.DataFrame([
    {"Sleeve": k, "Base Weight": f"{BASE_GRID[k]*100:.1f}%", "Tilted Weight": f"{v*100:.1f}%"}
    for k, v in tilted_grid.items()
])
st.dataframe(grid_df, hide_index=True, use_container_width=True)

st.markdown('<div class="sme-section-label">📉 Drawdown Tracking (from your logged history)</div>', unsafe_allow_html=True)
if drawdown_status == "NO DATA":
    st.caption("No portfolio value history logged yet. Enter a value in the sidebar and click "
               "'Log today's snapshot' to start tracking drawdown from peak over time.")
else:
    dd_style = {"accent": "#ff4d4d", "bg": "rgba(255,77,77,0.08)"} if drawdown_status == "DRAWDOWN PROTECTION ACTIVE" else {"accent": "#4dd68c", "bg": "rgba(77,214,140,0.06)"}
    badge_card("Drawdown Status", f"{drawdown_status} ({current_drawdown*100:.1f}% from peak)", dd_style)

with st.expander("📜 Logged history (session memory -- see hosting caveat in code comments)"):
    if history_df.empty:
        st.caption("No snapshots logged yet.")
    else:
        st.dataframe(history_df, hide_index=True, use_container_width=True)
    st.caption("⚠️ This log writes to a local CSV file. On ephemeral hosting (e.g. Streamlit Community "
               "Cloud free tier), this can be wiped on redeploy/restart -- it is NOT guaranteed durable "
               "15-year storage as shipped. For genuine long-horizon persistence, point this at a real "
               "backing store (Google Sheet, Airtable, hosted database) as a follow-up.")
