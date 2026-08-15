"""
Structural Allocation Grid — WATCHLIST-MAXIMAL BUILD (v4.1-compatible)
Pure data encoding (sections -> layers -> target weights -> tickers ->
protocol/thesis). No Streamlit, no network calls; safe to import anywhere.

Additive by design: every ticker from every prior grid/yaml/expansion list
is retained (either/or pairs keep BOTH members; previously cut names and
delisted ADRs remain as watchlist satellites).

Core/satellite convention: tickers in a layer's "satellites" key are
half-size watchlist positions; everyone else is core. effective_weight
remains the layer's shared ceiling (section_target_pct * layer_weight),
NOT a per-ticker entitlement.

Core portfolio (sums to 100%):
INFRA 14% + ENERGY & COMMODITY 18% + AI/SEMIS 10% + EM 7%
+ Business & Futuristic Overlay 6% + BTC 25% + GOLD 10% + CASH 10% = 100%
"""

SECTIONS = {
    "INFRA": {
        "target_pct": 0.14,
        "layers": {
            "Layer 1: Hard Assets & Global Freight": {
                "weight": 0.35,
                "tickers": ["TPL", "ADPORTS.AD", "ICTSY", "CNI", "CP", "UNP", "MATX", "DSV.CO"],
                # ADPORTS.AD = AD Ports Group (grid said "ADPORTS"); ICTSY = ICTSI ADR (grid said "ICTEY")
                "protocol": "Landowners, royalty engines, maritime ports, and Class I transcontinental "
                            "freight rail networks; Jones Act maritime shipping (MATX) and global "
                            "freight forwarding / contract logistics integration (DSV).",
            },
            "Layer 2: Electrification, Grid & Utilities": {
                "weight": 0.40,
                "tickers": ["LIN", "ABBN.SW", "SU.PA", "GEV", "ETN", "NVT", "CEG", "PWR",
                            "PRY.MI", "5803.T", "VRT", "AGX", "PH", "BE"],
                "satellites": ["PH", "BE"],
                # 5803.T = Fujikura, Tokyo listing (grid showed "FUWAY" OTC ADR; FUWAF also seen)
                "protocol": "Industrial gases, power electrification, grid equipment, clean nuclear for "
                            "data centers, HV/subsea cabling (PRY.MI), AI-DC optical/power cabling "
                            "(Fujikura), DC power & liquid cooling (VRT), power EPC (PWR, AGX), "
                            "motion control (PH), fuel cells (BE).",
            },
            "Layer 3: Water & Environmental": {
                "weight": 0.10,
                "tickers": ["XYL", "ECL", "WM", "RSG", "CWCO", "BMI"],
                "satellites": ["CWCO", "BMI"],
                "protocol": "Water tech and environmental waste: treatment, smart metering, process "
                            "chemistry, waste duopoly, niche desalination.",
            },
            "Layer 4: Cyber, Networking & Tech-Adjacent": {
                "weight": 0.15,
                "tickers": ["ANET", "FTNT", "CHKP", "CRWD", "ZS", "PANW", "OKTA", "ADTN", "CALX", "HLIT"],
                "satellites": ["ADTN", "CALX", "HLIT"],
                "core_eligible": ["PANW"],
                "protocol": "Data center networking switches, zero-trust/perimeter cloud cybersecurity, "
                            "identity (OKTA); broadband-access satellites. FTNT/CHKP and CRWD/ZS were "
                            "either/or pairs -- BOTH members kept; layer weight is a shared ceiling.",
            },
        },
    },
    "ENERGY & COMMODITY": {
        "target_pct": 0.18,
        "layers": {
            "Layer 1: Monetary Royalties": {
                "weight": 0.30,
                "tickers": ["FNV", "WPM", "BSM", "DMLP"],
                "satellites": ["BSM", "DMLP"],
                "protocol": "Precious metals streaming and asset-light gold/silver royalty engines; "
                            "BSM/DMLP add an energy/mineral royalty tail.",
            },
            "Layer 2: Baseload & Nuclear Energy": {
                "weight": 0.40,
                "tickers": ["CCJ", "UUUU", "CNQ", "XOM", "SU", "EQT", "CVX"],
                "satellites": ["CVX"],
                "light_only": ["XOM"],
                "protocol": "Uranium pure-plays for nuclear baseload (CCJ, UUUU), oil sands, natural gas, "
                            "and integrated supermajors. XOM = Light weighting only, per grid. CVX kept "
                            "on the watchlist as alternate supermajor expression.",
            },
            "Layer 3: Industrial & Critical Materials": {
                "weight": 0.30,
                "tickers": ["FCX", "SCCO", "BHP", "NEM", "STLD", "CAT", "3750.HK",
                            "COP", "NUE", "HBM", "AA", "ALB", "ALM", "LYL.AX"],
                "satellites": ["COP", "NUE", "HBM", "AA", "ALB", "ALM", "LYL.AX"],
                # 3750.HK = CATL (HK listing); LYL.AX = Lycopodium (grid showed "LYSCF" OTC)
                "protocol": "Copper/iron mining for global electrification, efficient steel, heavy "
                            "machinery, batteries/storage (CATL), aluminum, lithium, tungsten, and mining "
                            "engineering services. COP/NUE retained on the watchlist.",
            },
        },
    },
    "AI/SEMIS": {
        "target_pct": 0.10,
        "layers": {
            "Layer 1: Physical Monopolies, Foundry & Materials": {
                "weight": 0.45,
                "tickers": ["TSM", "ASML", "SHECY", "ENTG", "GFS", "6920.T", "AXTI", "ALMU"],
                "satellites": ["6920.T", "AXTI", "ALMU"],
                "protocol": "Structural monopolies in advanced foundries, EUV lithography systems, silicon "
                            "wafers, and EUV mask inspection; materials/filtration (ENTG) and differentiated "
                            "foundry (GFS); photonics/substrate satellites (AXTI, ALMU -- verify).",
            },
            "Layer 2: Architecture, Robotics, Edge & Memory": {
                "weight": 0.30,
                "tickers": ["AVGO", "CDNS", "QCOM", "FANUY", "8035.T", "SNPS", "MRAM", "AMBA", "PENG"],
                "satellites": ["MRAM", "AMBA", "PENG"],
                "protocol": "Custom AI ASICs, EDA software, edge AI silicon, industrial factory robotics; "
                            "memory IP/security (MRAM), edge vision (AMBA), AI memory modules (PENG).",
            },
            "Layer 3: Velocity Applications": {
                "weight": 0.15,
                "tickers": ["NOW", "STX"],
                "protocol": "Enterprise generative AI workflow automation and high-capacity mass cloud "
                            "storage. (PANW moved to INFRA Layer 4 when cyber was consolidated; still in "
                            "universe and still core-eligible.)",
            },
            "Layer 4: Vertical Software & Data Monopolies": {
                "weight": 0.10,
                "tickers": ["VRSN", "MANH", "WTC.AX", "DSGX", "FDS", "KXS.TO", "TRMB", "IKTSY"],
                "satellites": ["KXS.TO", "TRMB", "IKTSY"],
                "protocol": "Toll-booth data monopolies: domain registry, supply-chain and logistics "
                            "software, financial data, geospatial, and quality-certification infrastructure.",
            },
        },
    },
    "EM": {
        "target_pct": 0.07,
        "layers": {
            "Layer 1: INDIA": {
                "weight": 0.50,
                "tickers": ["ABB.NS", "SIEMENS.NS", "POWERINDIA.NS", "CGPOWER.NS", "DIXON.NS", "KAYNES.NS",
                            "HFCL.NS", "CONCOR.NS", "SUNPHARMA.NS", "HCLTECH.NS", "PIIND.NS", "STLTECH.NS",
                            "PRECWIRE.NS", "MTARTECH.NS", "HINDCOPPER.NS", "DIACABS.NS"],
                "satellites": ["PIIND.NS", "STLTECH.NS", "PRECWIRE.NS", "MTARTECH.NS", "HINDCOPPER.NS", "DIACABS.NS"],
                # ABB.NS (not bare "ABB" = Swiss ABB Ltd). POWERINDIA.NS = Hitachi Energy India, verified
                # against Yahoo Finance ("HITACHIENR.NS"/"HITACHI-ENERGY" are not the symbol).
                "protocol": "Indian grid modernization, power transmission, EMS/electronics manufacturing, "
                            "rail logistics, agrochemicals, pharmaceuticals, and enterprise IT services. "
                            "DIACABS.NS -- verify exact listing.",
            },
            "Layer 2: GCC": {
                "weight": 0.20,
                "tickers": ["2222.SR", "ADNOCGAS.AB", "2082.SR", "7010.SR"],
                # Aramco/ACWA/STC on Tadawul (.SR); ADNOC Gas is on the Abu Dhabi exchange (.AB),
                # NOT Tadawul and NOT .AD. Grid showed "ADCONGAS".
                "protocol": "Highly cash-generative regional energy, natural gas processing, water "
                            "desalination, and telecom/digital infrastructure.",
            },
            "Layer 3: Other Jurisdictions": {
                "weight": 0.30,
                "tickers": ["TLK", "VALE", "0883.HK", "CSUAY", "0941.HK", "BABAF", "YPF",
                            "0883.HK", "0941.HK", "INDO", "ISDE.L", "HIJP", "KAP.IL"],
                "satellites": ["CEO", "CHL", "INDO", "ISDE.L", "HIJP", "KAP.IL"],
                # CEO/CHL = delisted NYSE ADRs (EO 13959, 2021); live listings are 0883.HK / 0941.HK.
                # Retained for watchlist continuity only.
                "protocol": "Resource-rich emerging markets (Brazil/Indonesia), dominant international "
                            "infrastructure/telecom operators, China value (BABAF), LatAm energy (YPF). "
                            "INDO/ISDE.L/HIJP/KAP.IL -- verify exact vehicles.",
            },
        },
    },
    "Business & Futuristic Overlay": {
        "target_pct": 0.06,
        "layers": {
            "NVO": {
                "weight": 0.30,
                "tickers": ["NVO"],
                "protocol": "Global metabolic healthcare leader dominating GLP-1/obesity/diabetes "
                            "secular growth engines.",
                "core_eligible": ["NVO"],
            },
            "AZN": {
                "weight": 0.20,
                "tickers": ["AZN"],
                "protocol": "Advanced oncology, complex rare disease therapeutics, and deep "
                            "biopharmaceutical pipeline depth.",
            },
            "ISRG": {
                "weight": 0.20,
                "tickers": ["ISRG"],
                "protocol": "Structural monopoly in da Vinci robotic-assisted minimally invasive "
                            "surgery ecosystems.",
            },
            "TMO": {
                "weight": 0.15,
                "tickers": ["TMO"],
                "protocol": "The universal foundational provider of life sciences tools, reagents, "
                            "and laboratory equipment.",
            },
            "RHHBY": {
                "weight": 0.15,
                "tickers": ["RHHBY"],
                "protocol": "Roche ADR -- oncology and diversified pharma depth.",
            },
        },
    },
    "BTC": {
        "target_pct": 0.25,
        "layers": {
            "Core: Cold Wallet": {
                "weight": 0.90,
                "tickers": ["BTC"],
                "protocol": "Cold wallet. Self-custodied monetary position, no counterparty.",
            },
            "Equity Satellites (capped)": {
                "weight": 0.10,
                "tickers": ["MSTR", "RIOT"],
                "satellites": ["MSTR", "RIOT"],
                "protocol": "High-volatility BTC expressions (treasury vehicle, miner). Capped satellite "
                            "sleeve; trim into NAV-premium strength.",
            },
        },
    },
    "GOLD": {"target_pct": 0.10, "tickers": ["GOLD"], "protocol": "Physical."},
    "CASH": {"target_pct": 0.10, "tickers": ["CASH"], "protocol": "Tactical parking / dry powder."},
}

# No separate satellite tier -- everything lives inside SECTIONS above.
# Kept as an empty dict so any code iterating SATELLITE doesn't break.
SATELLITE = {}


def flatten_universe() -> list[dict]:
    """
    Flattens SECTIONS (+ SATELLITE, empty) into one row-per-ticker list:
    [{"ticker", "section", "layer", "layer_weight", "section_target_pct",
    "effective_weight", "protocol", "group", "role"}]

    effective_weight = section_target_pct * layer_weight -- the layer's slice
    of the whole portfolio, i.e. an upper bound when ranking within a layer,
    NOT a per-ticker entitlement.

    "role" = "satellite" if the ticker is in the layer's "satellites" key,
    else "core".

    Exceptions:
      * Overlay layers each hold exactly one ticker with an explicit weight
        (30/20/20/15/15) -- there effective_weight IS the per-ticker target.
      * BTC "Equity Satellites" weight (0.10 of the 0.25 sleeve) is a hard
        cap for MSTR+RIOT combined, not an entitlement each.
    """
    rows = []
    for section_name, section in SECTIONS.items():
        target_pct = section.get("target_pct")
        if "layers" in section:
            for layer_name, layer in section["layers"].items():
                satellites = set(layer.get("satellites", []))
                for ticker in layer["tickers"]:
                    rows.append({
                        "ticker": ticker,
                        "section": section_name,
                        "layer": layer_name,
                        "layer_weight": layer["weight"],
                        "section_target_pct": target_pct,
                        "effective_weight": (target_pct or 0) * layer["weight"],
                        "protocol": layer.get("protocol", ""),
                        "group": "core",
                        "role": "satellite" if ticker in satellites else "core",
                    })
        else:
            for ticker in section["tickers"]:
                rows.append({
                    "ticker": ticker,
                    "section": section_name,
                    "layer": section_name,
                    "layer_weight": 1.0,
                    "section_target_pct": target_pct,
                    "effective_weight": target_pct or 0,
                    "protocol": section.get("protocol", ""),
                    "group": "core",
                    "role": "core",
                })
    for section_name, section in SATELLITE.items():
        target_pct = section.get("target_pct")
        for ticker in section["tickers"]:
            rows.append({
                "ticker": ticker,
                "section": section_name,
                "layer": section_name,
                "layer_weight": 1.0,
                "section_target_pct": target_pct,
                "effective_weight": target_pct or 0,
                "protocol": section.get("protocol", ""),
                "group": "satellite",
                "role": "satellite",
            })
    return rows


# Non-equity placeholders (skip in engines that need P/S / revenue data)
NON_EQUITY_TICKERS = {"BTC", "GOLD", "CASH"}

# Tickers explicitly marked "core eligible" in the grid, or a natural core read
# (land/royalty/monopoly-style holdings) -- drives is_core in the Valuation Engine.
CORE_ELIGIBLE_TICKERS = {
    "TPL", "ADPORTS.AD", "ICTSY", "CNI", "CP", "FNV", "WPM", "TSM", "ASML", "PANW",
    "NVO", "XYL", "WM", "RSG",
}

# ---------------------------------------------------------------------------
# BACKWARD-COMPAT ALIASES -- v4.1 Home.py import safety net.
# Older builds of this module / older pages imported these names; keep them
# resolving so `from structural_grid import (...)` can never fail on a rename.
# ---------------------------------------------------------------------------
CORE_SECTIONS = SECTIONS                      # pre-revision export name
GRID = SECTIONS                               # earliest export name
SAT = SATELLITE
NON_EQUITY = NON_EQUITY_TICKERS
CORE_ELIGIBLE = CORE_ELIGIBLE_TICKERS
UNIVERSE = flatten_universe()                 # precomputed rows
SECTION_TARGETS = {n: s.get("target_pct") for n, s in SECTIONS.items()}

__all__ = [
    "SECTIONS", "CORE_SECTIONS", "GRID", "SATELLITE", "SAT",
    "flatten_universe", "UNIVERSE", "NON_EQUITY_TICKERS", "NON_EQUITY",
    "CORE_ELIGIBLE_TICKERS", "CORE_ELIGIBLE", "SECTION_TARGETS",
]


def __getattr__(name):  # PEP 562 -- must raise AttributeError, never ImportError
    # Dunder lookups (__path__, __file__, __spec__, ...) are normal attribute
    # probes by the import system / Streamlit's watcher -- fail silently.
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    raise AttributeError(
        f"module 'structural_grid' has no attribute {name!r}. "
        f"Available exports: {sorted(__all__)}"
    )
