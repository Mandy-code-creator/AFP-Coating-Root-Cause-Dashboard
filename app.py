
import re
import io
import base64
import html as html_lib
import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

try:
    from scipy.stats import mannwhitneyu
    SCIPY_AVAILABLE = True
except Exception:
    SCIPY_AVAILABLE = False


# ============================================================
# PAGE CONFIGURATION
# ============================================================
st.set_page_config(
    page_title="AFP Coating Root Cause Dashboard",
    page_icon="📊",
    layout="wide"
)

st.title("AFP Coating - OK vs NG Root Cause Dashboard")
st.caption(
    "Objective: identify the factors associated with anti-fingerprint coating "
    "peeling, powder shedding (掉粉) and white powder after customer deep-drawing / forming."
)


# ============================================================
# SOURCE COLUMN NAMES
# Keep source names here only.
# The dashboard UI uses English display names.
# ============================================================
COL = {
    "coil": "COIL_NO",
    "date": "PRODUCTION_DATE",
    "quality": "Quality class",
    "order": "ORDER_NUMBER",

    "oven_temp": "OVEN_TEMPERATURE",
    "roll_temp": "ROLL_TEMPERATURE",

    "up_n": "NORTH_UP_FILM_THICK",
    "up_c": "CENTER_UP_FILM_THICK",
    "up_s": "SOUTH_UP_FILM_THICK",

    # Several source files may use slightly different names for the lower side.
    "down_n_candidates": [
        "NORTH_DOWN_FILM_THICK",
        "NORTH_UP_DOWN_THICK",
        "NORTH_UP_ DOWN_THICK",
    ],
    "down_c_candidates": [
        "CENTER_DOWN_FILM_THICK",
        "CENTER_ DOWN_FILM_THICK",
    ],
    "down_s_candidates": [
        "SOUTH_DOWN_FILM_THICK",
        "SOUTH_ DOWN_FILM_THICK",
    ],

    "afp_recheck": "AFP膜厚(um)",

    "slip": "滑度",
    "adhesion": "附著性",
    "wear": "耐磨性",
    "roughness": "粗糙度(Ra)",

    "xray_top_n": "XRAY_A_T_N",
    "xray_top_c": "XRAY_A_T_C",
    "xray_top_s": "XRAY_A_T_S",

    "xray_bottom_n": "XRAY_A_B_N",
    "xray_bottom_c": "XRAY_A_B_C",
    "xray_bottom_s": "XRAY_A_B_S",

    "hardness_s": "NEAR_SOUTH_HARDNESS",
    "hardness_n": "NEAR_NORTH_HARDNESS",

    "ys": "TENSILE_YIELD_RAW",
    "ts": "TENSILE_TENSILE_RAW",
    "el": "TENSILE_ELONG_RAW",
}


# ============================================================
# DISPLAY LABELS
# ============================================================
DISPLAY = {
    "OVEN_TEMPERATURE": "Oven Temperature",
    "ROLL_TEMPERATURE": "Roll Temperature",

    "AFP_TOP_MEAN": "AFP Up Film Thickness Mean (N-C-S)",
    "AFP_BOTTOM_MEAN": "AFP Down Film Thickness Mean (N-C-S)",

    "AFP_TOP_RANGE": "AFP Up Thickness Range (N-C-S)",
    "AFP_BOTTOM_RANGE": "AFP Down Thickness Range (N-C-S)",

    "XRAY_TOP_MEAN": "Metal Coating Thickness - Up Mean",
    "XRAY_BOTTOM_MEAN": "Metal Coating Thickness - Down Mean",
    "XRAY_TOTAL": "Metal Coating Thickness - Total",
    "XRAY_SIDE_DIFFERENCE": "Up-Down Metal Coating Difference",

    "HARDNESS_MEAN": "Steel Hardness Mean",
    "HARDNESS_DIFFERENCE": "North-South Hardness Difference",
    "YS": "Yield Strength",
    "TS": "Tensile Strength",
    "EL": "Elongation",

    "滑度": "Slip / COF",
    "附著性": "AFP Adhesion",
    "耐磨性": "AFP Wear Resistance",
    "粗糙度(Ra)": "Surface Roughness Ra",
}


# ============================================================
# SUPPLIER BENCHMARK - SUPPORTING TECHNICAL EVIDENCE
# ============================================================

SUPPLIER_COATING_WEIGHT_RISK_BENCHMARK = 700.0  # mg/m²

# Supplier simulation data transcribed from the provided benchmark tables.
# This dataset is kept separate from internal OK/NG screening and is used
# only as supporting technical evidence for coating-weight / friction behavior.
SUPPLIER_BENCHMARK_DATA = pd.DataFrame(
    [
        # LOT, Side, Coating Weight, Cr content, Mobility Low, Mobility High, 60kgf, 120kgf, 240kgf
        ["62A076X", "UP",   970, 0.0135, 0.08, 0.10, 0.5166, 0.3335, 0.2399],
        ["62A076X", "DOWN", 920, 0.0135, 0.08, 0.10, 0.5377, 0.3468, 0.2571],
        ["62A075X", "UP",  1028, 0.0145, 0.08, 0.10, 0.5034, 0.3200, 0.2441],
        ["62A075X", "DOWN", 930, 0.0145, 0.08, 0.11, 0.5196, 0.3504, 0.2623],
        ["62A074X", "UP",  1030, 0.0120, 0.08, 0.10, 0.4776, 0.3067, 0.2411],
        ["62A074X", "DOWN", 920, 0.0120, 0.08, 0.10, 0.4949, 0.3618, 0.2607],
        ["62A073X", "UP",  1017, 0.0112, 0.07, 0.08, 0.4689, 0.3045, 0.2361],
        ["62A073X", "DOWN", 925, 0.0112, 0.08, 0.10, 0.5353, 0.3511, 0.2626],
        ["62A072X", "UP",  1003, 0.0127, 0.08, 0.10, 0.5385, 0.3570, 0.2607],
        ["62A072X", "DOWN", 875, 0.0127, 0.09, 0.11, 0.5274, 0.3796, 0.2569],
        ["61B962X", "UP",   985, 0.0120, 0.08, 0.10, 0.5486, 0.3531, 0.2524],
        ["61B962X", "DOWN",1001, 0.0120, 0.07, 0.09, 0.4792, 0.3416, 0.2339],
        ["61B961X", "UP",  1021, 0.0120, 0.08, 0.10, 0.4872, 0.3331, 0.2546],
        ["61B961X", "DOWN", 948, 0.0120, 0.09, 0.11, 0.5105, 0.3287, 0.2403],
        ["61B960X", "UP",  1072, 0.0123, 0.08, 0.09, 0.4774, 0.3246, 0.2473],
        ["61B960X", "DOWN", 930, 0.0123, 0.08, 0.10, 0.4642, 0.2948, 0.2274],

        ["62A103X", "UP",  1073, 0.0108, 0.07, 0.08, 0.4492, 0.2940, 0.2252],
        ["62A103X", "DOWN", 895, 0.0108, 0.08, 0.10, 0.5288, 0.3563, 0.2639],
        ["62A102X", "UP",   780, 0.0109, 0.08, 0.10, 0.5820, 0.3953, 0.2834],
        ["62A102X", "DOWN", 835, 0.0109, 0.08, 0.10, 0.5717, 0.3722, 0.3002],
        ["62A101X", "UP",   785, 0.0110, 0.09, 0.11, 0.5338, 0.3575, 0.2719],
        ["62A101X", "DOWN", 805, 0.0110, 0.09, 0.11, 0.5548, 0.3429, 0.2579],
        ["62A100X", "UP",   820, 0.0110, 0.08, 0.11, 0.5393, 0.3651, 0.2774],
        ["62A100X", "DOWN", 780, 0.0110, 0.08, 0.11, 0.5556, 0.3565, 0.2762],
        ["62A099X", "UP",   825, 0.0094, 0.08, 0.10, 0.5828, 0.3734, 0.2692],
        ["62A099X", "DOWN", 780, 0.0094, 0.09, 0.11, 0.5931, 0.3736, 0.2933],
        ["62A098X", "UP",   837, 0.0117, 0.08, 0.10, 0.5481, 0.4204, 0.2741],
        ["62A098X", "DOWN", 850, 0.0117, 0.08, 0.10, 0.5075, 0.3406, 0.2710],
        ["62A097X", "UP",   820, 0.0099, 0.08, 0.10, 0.5293, 0.3415, 0.2746],
        ["62A097X", "DOWN", 870, 0.0099, 0.08, 0.10, 0.5325, 0.3414, 0.2617],
        ["62A077X", "UP",   896, 0.0109, 0.08, 0.10, 0.4932, 0.3390, 0.2501],
        ["62A077X", "DOWN", 856, 0.0109, 0.08, 0.10, 0.5035, 0.3520, 0.2400],

        ["5BB404X", "UP",   750, 0.0087, 0.10, 0.11, 0.6709, 0.4372, 0.2950],
        ["5BB404X", "DOWN",1000, 0.0087, 0.06, 0.08, 0.3609, 0.2412, 0.1759],
        ["5BB405X", "UP",   800, 0.0123, 0.08, 0.10, 0.5212, 0.3260, 0.2264],
        ["5BB405X", "DOWN",1030, 0.0123, 0.07, 0.08, 0.3514, 0.2417, 0.1725],
        ["5BB406X", "UP",   450, 0.0064, 0.19, 0.22, 0.9407, 0.6192, 0.4208],
        ["5BB406X", "DOWN", 650, 0.0064, 0.10, 0.12, 0.7071, 0.4646, 0.3136],
        ["5BB439X", "UP",   800, 0.0111, 0.07, 0.09, 0.4692, 0.3112, 0.2019],
        ["5BB439X", "DOWN",1100, 0.0111, 0.06, 0.07, 0.3497, 0.2317, 0.1753],
        ["5BB440X", "UP",   700, 0.0096, 0.10, 0.115,0.5549, 0.3845, 0.2661],
        ["5BB440X", "DOWN",1080, 0.0096, 0.06, 0.08, 0.3287, 0.2400, 0.1640],
        ["5BB441X", "UP",   960, 0.0116, 0.06, 0.08, 0.3508, 0.2386, 0.1543],
        ["5BB441X", "DOWN", 750, 0.0116, 0.10, 0.11, 0.4881, 0.3392, 0.2380],
        ["5BB442X", "UP",   880, 0.0114, 0.07, 0.09, 0.4370, 0.2754, 0.1905],
        ["5BB442X", "DOWN",1170, 0.0114, 0.06, 0.08, 0.3083, 0.2204, 0.1637],
        ["5BB443X", "UP",  1100, 0.0125, 0.05, 0.07, 0.3346, 0.2270, 0.1705],
        ["5BB443X", "DOWN", 800, 0.0125, 0.08, 0.10, 0.4751, 0.3427, 0.2479],
        ["5BB444X", "UP",  1300, 0.0143, 0.05, 0.06, 0.3317, 0.2226, 0.1455],
        ["5BB444X", "DOWN", 860, 0.0143, 0.08, 0.09, 0.4235, 0.2703, 0.1973],
        ["5BB445X", "UP",  1100, 0.0113, 0.05, 0.07, 0.3557, 0.2267, 0.1569],
        ["5BB445X", "DOWN", 780, 0.0113, 0.08, 0.10, 0.4872, 0.3366, 0.2443],
    ],
    columns=[
        "LOT",
        "Side",
        "Coating Weight (mg/m²)",
        "Cr content (%)",
        "Mobility Low",
        "Mobility High",
        "Friction 60kgf",
        "Friction 120kgf",
        "Friction 240kgf",
    ],
)

SUPPLIER_BENCHMARK_DATA["Benchmark Status"] = np.where(
    SUPPLIER_BENCHMARK_DATA["Coating Weight (mg/m²)"]
    < SUPPLIER_COATING_WEIGHT_RISK_BENCHMARK,
    "Below 700 mg/m²",
    "At / Above 700 mg/m²",
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def clean_column_name(name):
    """Trim spaces and normalize repeated spaces around underscores."""
    name = str(name).strip()
    name = re.sub(r"\s+", " ", name)
    return name


def find_first_existing(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def parse_numeric_value(value):
    """
    Convert common source formats to one numeric value.

    Examples:
        1.07/1.20              -> 1.135
        0.14-0.16             -> 0.150
        0.46-0.52/0.47-0.56   -> average of both interval centers
        100                    -> 100.0

    This function is used only when a column is expected to contain
    numeric or numeric-range information.
    """
    if pd.isna(value):
        return np.nan

    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)

    text = str(value).strip()
    if not text:
        return np.nan

    text = (
        text.replace("～", "-")
        .replace("~", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("／", "/")
        .replace(",", ".")
    )

    part_values = []

    for part in text.split("/"):
        part = part.strip()
        if not part:
            continue

        # Exact numeric value
        try:
            part_values.append(float(part))
            continue
        except Exception:
            pass

        # Numeric interval, e.g. 0.14-0.16 -> 0.150.
        # The hyphen between two positive values is a RANGE separator,
        # not a negative sign for the second number.
        interval_match = re.fullmatch(
            r"\s*([-+]?\d*\.?\d+)\s*-\s*([-+]?\d*\.?\d+)\s*",
            part,
        )
        if interval_match:
            a = float(interval_match.group(1))
            b = float(interval_match.group(2))
            part_values.append((a + b) / 2.0)
            continue

        numbers = re.findall(r"[-+]?\d*\.?\d+", part)
        numbers = [float(x) for x in numbers]

        if len(numbers) >= 2:
            part_values.append(np.mean(numbers[:2]))
        elif len(numbers) == 1:
            part_values.append(numbers[0])

    if not part_values:
        return np.nan

    return float(np.mean(part_values))


def normalize_quality(value):
    if pd.isna(value):
        return np.nan

    text = str(value).strip().upper()

    ok_terms = {"OK", "PASS", "GOOD", "O", "合格", "良品"}
    ng_terms = {"NG", "FAIL", "BAD", "N", "不合格", "不良"}

    if text in ok_terms:
        return "OK"
    if text in ng_terms:
        return "NG"

    if "NG" in text or "FAIL" in text or "不合格" in text or "不良" in text:
        return "NG"
    if "OK" in text or "PASS" in text or "合格" in text:
        return "OK"

    return text


def numeric_mean(df, columns):
    existing = [c for c in columns if c and c in df.columns]
    if not existing:
        return pd.Series(np.nan, index=df.index)

    values = df[existing].apply(pd.to_numeric, errors="coerce")
    return values.mean(axis=1)


def numeric_range(df, columns):
    existing = [c for c in columns if c and c in df.columns]
    if not existing:
        return pd.Series(np.nan, index=df.index)

    values = df[existing].apply(pd.to_numeric, errors="coerce")
    return values.max(axis=1) - values.min(axis=1)


def numeric_minimum(df, columns):
    existing = [c for c in columns if c and c in df.columns]
    if not existing:
        return pd.Series(np.nan, index=df.index)

    values = df[existing].apply(pd.to_numeric, errors="coerce")
    return values.min(axis=1)


def effect_size_smd(ok_values, ng_values):
    """
    Standardized mean difference.
    Positive value: NG mean > OK mean.
    Negative value: NG mean < OK mean.
    """
    ok = pd.to_numeric(ok_values, errors="coerce").dropna()
    ng = pd.to_numeric(ng_values, errors="coerce").dropna()

    if len(ok) < 2 or len(ng) < 2:
        return np.nan

    s_ok = ok.std(ddof=1)
    s_ng = ng.std(ddof=1)

    pooled_sd = np.sqrt(
        ((len(ok) - 1) * s_ok**2 + (len(ng) - 1) * s_ng**2)
        / (len(ok) + len(ng) - 2)
    )

    if pooled_sd == 0 or pd.isna(pooled_sd):
        return np.nan

    return (ng.mean() - ok.mean()) / pooled_sd


def mann_whitney_p(ok_values, ng_values):
    if not SCIPY_AVAILABLE:
        return np.nan

    ok = pd.to_numeric(ok_values, errors="coerce").dropna()
    ng = pd.to_numeric(ng_values, errors="coerce").dropna()

    if len(ok) < 2 or len(ng) < 2:
        return np.nan

    try:
        return mannwhitneyu(ok, ng, alternative="two-sided").pvalue
    except Exception:
        return np.nan


def build_summary(df, variables, quality_col):
    rows = []

    for variable in variables:
        if variable not in df.columns:
            continue

        values = pd.to_numeric(df[variable], errors="coerce")
        ok = values[df[quality_col] == "OK"].dropna()
        ng = values[df[quality_col] == "NG"].dropna()

        if len(ok) == 0 and len(ng) == 0:
            continue

        smd = effect_size_smd(ok, ng)

        rows.append(
            {
                "Parameter": DISPLAY.get(variable, variable),
                "Source Variable": variable,
                "OK n": len(ok),
                "OK Mean": ok.mean() if len(ok) else np.nan,
                "OK Median": ok.median() if len(ok) else np.nan,
                "NG n": len(ng),
                "NG Mean": ng.mean() if len(ng) else np.nan,
                "NG Median": ng.median() if len(ng) else np.nan,
                "NG - OK": (
                    ng.mean() - ok.mean()
                    if len(ok) and len(ng)
                    else np.nan
                ),
                "SMD": smd,
                "|SMD|": abs(smd) if pd.notna(smd) else np.nan,
                "Mann-Whitney p": mann_whitney_p(ok, ng),
            }
        )

    out = pd.DataFrame(rows)

    if not out.empty:
        out["Factor Role"] = out["Source Variable"].map(factor_role)
        out["Technical Interpretation"] = out.apply(
            lambda r: technical_interpretation(
                r["Source Variable"],
                r["OK Mean"],
                r["NG Mean"],
                r["SMD"],
                r["Mann-Whitney p"],
            ),
            axis=1,
        )

        out = out.sort_values(
            by=["|SMD|", "Parameter"],
            ascending=[False, True],
            na_position="last",
        )

    return out


def make_boxplot(df, variable, quality_col, title=None):
    values = pd.to_numeric(df[variable], errors="coerce")

    ok = values[df[quality_col] == "OK"].dropna()
    ng = values[df[quality_col] == "NG"].dropna()

    fig, ax = plt.subplots(figsize=(6.5, 4.3))

    plot_data = []
    labels = []

    if len(ok):
        plot_data.append(ok.values)
        labels.append(f"OK (n={len(ok)})")

    if len(ng):
        plot_data.append(ng.values)
        labels.append(f"NG (n={len(ng)})")

    if plot_data:
        # Matplotlib >= 3.9 uses 'tick_labels' instead of the older 'labels'
        # argument. Keep a fallback for compatibility with older versions.
        try:
            ax.boxplot(
                plot_data,
                tick_labels=labels,
                showmeans=True,
            )
        except TypeError:
            ax.boxplot(
                plot_data,
                labels=labels,
                showmeans=True,
            )

        ax.grid(axis="y", alpha=0.25)
        ax.set_ylabel(DISPLAY.get(variable, variable))

    ax.set_title(
        title or f"{DISPLAY.get(variable, variable)}: OK vs NG",
        fontweight="bold",
    )

    fig.tight_layout()
    return fig


def numeric_variables_available(df, candidates, min_count=2):
    result = []

    for c in candidates:
        if c in df.columns:
            x = pd.to_numeric(df[c], errors="coerce")
            if x.notna().sum() >= min_count:
                result.append(c)

    return result


def prepare_order_level_data(df, order_col, quality_col, qc_columns):
    """
    Surface QC columns may represent one coil sampled for the complete order.
    Therefore they are analyzed once per ORDER_NUMBER, not repeated per coil.
    """
    if order_col not in df.columns:
        return pd.DataFrame()

    available = [c for c in qc_columns if c in df.columns]
    if not available:
        return pd.DataFrame()

    work = df[[order_col, quality_col] + available].copy()

    # For each order:
    # - if any coil is NG, the order is treated as NG
    # - otherwise OK
    order_quality = (
        work.groupby(order_col)[quality_col]
        .apply(
            lambda s: (
                "NG"
                if (s == "NG").any()
                else ("OK" if (s == "OK").any() else np.nan)
            )
        )
        .rename(quality_col)
    )

    # First non-null representative result for each order.
    order_qc = work.groupby(order_col)[available].first()

    return order_qc.join(order_quality).reset_index()


def factor_role(variable):
    """Classify variables by their role in the root-cause chain."""
    process_x = {
        "OVEN_TEMPERATURE",
        "ROLL_TEMPERATURE",
    }

    material_x = {
        "XRAY_TOP_MEAN",
        "XRAY_BOTTOM_MEAN",
        "XRAY_TOTAL",
        "XRAY_SIDE_DIFFERENCE",
        "HARDNESS_MEAN",
        "HARDNESS_DIFFERENCE",
        "YS",
        "TS",
        "EL",
    }

    intermediate_y = {
        "AFP_TOP_MEAN",
        "AFP_BOTTOM_MEAN",
        "AFP_TOP_RANGE",
        "AFP_BOTTOM_RANGE",
        "AFP_UP_MINIMUM",
        "AFP_DOWN_MINIMUM",
    }

    confirmation_y = {
        "滑度",
        "附著性",
        "耐磨性",
        "粗糙度(Ra)",
    }

    if variable in process_x:
        return "Upstream Process X"
    if variable in material_x:
        return "Upstream Material X"
    if variable in intermediate_y:
        return "Intermediate Coating Y"
    if variable in confirmation_y:
        return "Confirmation Response Y"
    return "Screening Variable"

def technical_interpretation(variable, ok_mean, ng_mean, smd, p_value):
    """
    Short management-oriented interpretation.
    Descriptive only; not a causal claim.
    """
    if pd.isna(ok_mean) or pd.isna(ng_mean):
        return "Insufficient data"

    diff = ng_mean - ok_mean
    direction = "higher" if diff > 0 else "lower"

    if variable == "ROLL_TEMPERATURE":
        return f"NG roll temperature is {direction}; candidate upstream coating-process factor."
    if variable == "OVEN_TEMPERATURE":
        return f"NG oven temperature is {direction}; possible drying / film-formation factor."
    if variable == "AFP_BOTTOM_MEAN":
        return f"NG down-side AFP thickness is {direction}; intermediate coating-performance response."
    if variable == "AFP_BOTTOM_RANGE":
        return f"NG down-side thickness variation is {direction}; intermediate film-uniformity response."

    if variable == "AFP_UP_MINIMUM":
        return f"NG up-side minimum AFP thickness is {direction}; local thin spots may increase friction risk."

    if variable == "AFP_DOWN_MINIMUM":
        return f"NG down-side minimum AFP thickness is {direction}; local thin spots may increase friction risk."

    if variable == "HARDNESS_MEAN":
        return f"NG steel hardness is {direction}; mechanical difference, but not direct AFP adhesion evidence."
    if variable == "EL":
        return f"NG elongation is {direction}; interpret as formability support factor, not direct AFP cause."
    if variable in {"YS", "TS"}:
        return f"NG mechanical strength is {direction}; supporting formability factor only."
    if variable == "粗糙度(Ra)":
        return f"NG roughness is {direction}; surface-condition candidate, but current replication is limited."
    if variable == "滑度":
        return f"NG slip/COF is {direction}; friction candidate, but current replication is limited."
    if variable == "附著性":
        return "AFP adhesion is directly relevant to peeling; treat as a key confirmation response."
    if variable == "耐磨性":
        return "AFP wear resistance is directly relevant to powder shedding (掉粉); treat as a key confirmation response."

    if pd.notna(smd) and abs(smd) >= 0.8:
        return "Large OK-NG separation; verify technical mechanism before causal interpretation."
    if pd.notna(p_value) and p_value < 0.05:
        return "Statistically different, but technical mechanism must still be verified."
    return "Limited OK-NG separation in current data."


def order_level_limitation_text(df, order_col, quality_col):
    """
    Explain independence limitation based on number of orders.
    """
    if order_col not in df.columns:
        return "ORDER_NUMBER is unavailable, so order-level independence cannot be assessed."

    order_quality = (
        df[[order_col, quality_col]]
        .dropna(subset=[order_col, quality_col])
        .drop_duplicates()
    )

    if order_quality.empty:
        return "No usable order-level quality data are available."

    # One order may contain mixed classifications; count unique orders by whether NG appears.
    grouped = (
        df.groupby(order_col)[quality_col]
        .apply(lambda s: "NG" if (s == "NG").any() else ("OK" if (s == "OK").any() else np.nan))
        .dropna()
    )

    ok_orders = int((grouped == "OK").sum())
    ng_orders = int((grouped == "NG").sum())
    total_orders = int(grouped.shape[0])

    if total_orders <= 2 or ok_orders < 2 or ng_orders < 2:
        return (
            f"Major limitation: current analysis contains only {total_orders} independent orders "
            f"({ok_orders} OK, {ng_orders} NG). Coil-level statistical significance may reflect "
            f"order-level differences. Root cause cannot be confirmed until additional independent "
            f"OK and NG orders are collected."
        )

    return (
        f"Current analysis contains {total_orders} independent orders "
        f"({ok_orders} OK, {ng_orders} NG). Order-level replication is available, "
        f"but causal confirmation is still required."
    )


def build_working_hypothesis(screening_df):
    """
    Build a data-driven screening hypothesis from the strongest upstream X
    and intermediate coating Y signals. It deliberately avoids hard-coding
    one historical mechanism.
    """
    if screening_df is None or screening_df.empty:
        return "Insufficient data to construct a working hypothesis."

    work = screening_df.dropna(subset=["|SMD|"]).copy()
    if work.empty:
        return "Insufficient data to construct a working hypothesis."

    strong = work[work["|SMD|"] >= 0.80].copy()
    upstream = strong[
        strong["Factor Role"].isin(["Upstream Process X", "Upstream Material X"])
    ]
    intermediate = strong[
        strong["Factor Role"] == "Intermediate Coating Y"
    ]

    if not upstream.empty and not intermediate.empty:
        x_names = upstream.head(2)["Parameter"].tolist()
        y_names = intermediate.head(2)["Parameter"].tolist()
        return (
            "Current screening hypothesis: strong upstream difference(s) in "
            + ", ".join(x_names)
            + " are associated with coating-response difference(s) in "
            + ", ".join(y_names)
            + ". Verify this X -> coating Y relationship against peeling / powder shedding before calling it root cause."
        )

    if not upstream.empty:
        names = upstream.head(3)["Parameter"].tolist()
        return (
            "Strong upstream screening signals are present in: "
            + ", ".join(names)
            + ". A corresponding coating-response mechanism has not yet been demonstrated."
        )

    if not intermediate.empty:
        names = intermediate.head(3)["Parameter"].tolist()
        return (
            "Strong coating-response differences are present in: "
            + ", ".join(names)
            + ". The upstream process/material driver has not yet been identified."
        )

    top = work.head(3)["Parameter"].tolist()
    return (
        "No mechanism-specific chain is established yet. Leading screening factors: "
        + ", ".join(top)
        + "."
    )


# ============================================================
# HTML REPORT HELPERS
# ============================================================


def make_supplier_benchmark_chart():
    """
    Supplier supporting-evidence chart:
    coating weight vs friction under 60 kgf.
    """
    d = SUPPLIER_BENCHMARK_DATA.copy()

    fig, ax = plt.subplots(figsize=(7.4, 4.8))

    for side in ["UP", "DOWN"]:
        sub = d[d["Side"] == side]
        if sub.empty:
            continue

        ax.scatter(
            sub["Coating Weight (mg/m²)"],
            sub["Friction 60kgf"],
            label=side,
            alpha=0.85,
        )

    ax.axvline(
        SUPPLIER_COATING_WEIGHT_RISK_BENCHMARK,
        linestyle="--",
        linewidth=1.2,
        label="Supplier risk benchmark: 700 mg/m²",
    )

    ax.set_xlabel("Supplier Coating Weight (mg/m²)")
    ax.set_ylabel("Friction Coefficient at 60 kgf")
    ax.set_title(
        "Supplier Benchmark: Coating Weight vs Friction",
        fontweight="bold",
    )
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    return fig


def supplier_benchmark_summary():
    d = SUPPLIER_BENCHMARK_DATA.copy()

    summary = (
        d.groupby("Benchmark Status", observed=True)
        .agg(
            Samples=("Coating Weight (mg/m²)", "size"),
            Mean_Coating_Weight=("Coating Weight (mg/m²)", "mean"),
            Mean_Friction_60kgf=("Friction 60kgf", "mean"),
            Mean_Friction_120kgf=("Friction 120kgf", "mean"),
            Mean_Friction_240kgf=("Friction 240kgf", "mean"),
        )
        .reset_index()
    )

    return summary


def supplier_internal_link_summary(df, quality_col):
    """
    Compare internal AFP minimum thickness by OK/NG.
    No direct unit conversion is attempted because supplier benchmark
    is mg/m² while internal AFP data are µm.
    """
    vars_to_use = [
        v for v in ["AFP_UP_MINIMUM", "AFP_DOWN_MINIMUM"]
        if v in df.columns
    ]

    if not vars_to_use:
        return pd.DataFrame()

    return build_summary(
        df,
        vars_to_use,
        quality_col,
    )


def make_signed_smd_chart(screening_df, top_n=15):
    """
    Signed SMD chart.
    Positive SMD: NG mean > OK mean.
    Negative SMD: NG mean < OK mean.
    Absolute magnitude indicates standardized OK-NG separation strength.
    """
    if screening_df is None or screening_df.empty:
        return None

    chart_df = screening_df.dropna(subset=["SMD"]).copy()
    if chart_df.empty:
        return None

    chart_df = (
        chart_df
        .assign(_abs=chart_df["SMD"].abs())
        .sort_values("_abs", ascending=False)
        .head(top_n)
        .sort_values("SMD", ascending=True)
    )

    fig, ax = plt.subplots(
        figsize=(8.8, max(5.2, 0.42 * len(chart_df) + 1.4))
    )
    ax.barh(chart_df["Parameter"], chart_df["SMD"])
    ax.axvline(0, linewidth=1)
    ax.set_xlabel("Signed Standardized Mean Difference (SMD)")
    ax.set_title("OK vs NG Direction and Separation (Signed SMD)", fontweight="bold")
    ax.grid(axis="x", alpha=0.25)

    for i, value in enumerate(chart_df["SMD"]):
        offset = 3 if value >= 0 else -3
        ha = "left" if value >= 0 else "right"
        ax.annotate(
            f"{value:+.2f}",
            xy=(value, i),
            xytext=(offset, 0),
            textcoords="offset points",
            va="center",
            ha=ha,
            fontsize=8,
        )

    fig.tight_layout()
    return fig

def make_smd_ranking_chart(screening_df, top_n=15):
    """
    Horizontal ranking chart using absolute SMD.
    This chart shows OK-vs-NG separation strength only.
    It does NOT prove root cause.
    """
    if screening_df is None or screening_df.empty:
        return None

    chart_df = (
        screening_df
        .dropna(subset=["|SMD|"])
        .copy()
        .sort_values("|SMD|", ascending=False)
        .head(top_n)
        .sort_values("|SMD|", ascending=True)
    )

    if chart_df.empty:
        return None

    fig, ax = plt.subplots(
        figsize=(
            8.5,
            max(5.0, 0.42 * len(chart_df) + 1.2),
        )
    )

    ax.barh(
        chart_df["Parameter"],
        chart_df["|SMD|"],
    )

    ax.set_xlabel(
        "Absolute Standardized Mean Difference"
    )
    ax.set_title(
        "OK vs NG Separation - Screening Only",
        fontweight="bold",
    )
    ax.grid(
        axis="x",
        alpha=0.25,
    )

    fig.tight_layout()
    return fig


def figure_to_base64(fig):
    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format="png",
        dpi=150,
        bbox_inches="tight",
    )
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


def classify_screening_result(row):
    """
    Descriptive screening only.
    This does not label a factor as a proven root cause.
    """
    effect = row.get("|SMD|", np.nan)
    p_value = row.get("Mann-Whitney p", np.nan)

    if pd.isna(effect):
        return "Insufficient data"

    if effect >= 0.80 and (pd.isna(p_value) or p_value < 0.05):
        return "High-priority candidate"
    if effect >= 0.50:
        return "Moderate-priority candidate"
    if effect < 0.20:
        return "Low separation"
    return "Needs review"


def build_executive_conclusion(screening_df):
    """
    Return a short, management-friendly conclusion.
    """
    if screening_df is None or screening_df.empty:
        return [
            "The available data are insufficient to establish a reliable OK-versus-NG ranking.",
            "Additional matched OK and NG coils are required before root-cause screening."
        ]

    ranked = screening_df.dropna(subset=["|SMD|"]).copy()
    if ranked.empty:
        return [
            "The available variables do not contain enough numeric OK-versus-NG information for effect-size screening."
        ]

    high = ranked[ranked["|SMD|"] >= 0.80]
    low = ranked[ranked["|SMD|"] < 0.20]

    lines = []

    if not high.empty:
        top_names = high["Parameter"].head(3).tolist()
        lines.append(
            "The strongest OK-versus-NG separation is currently observed in: "
            + ", ".join(top_names)
            + ". These variables should be prioritized for root-cause verification."
        )
    else:
        top_names = ranked["Parameter"].head(3).tolist()
        lines.append(
            "No variable currently shows a very large OK-versus-NG separation. "
            "The leading screening candidates are: "
            + ", ".join(top_names)
            + "."
        )

    if not low.empty:
        low_names = low["Parameter"].head(3).tolist()
        lines.append(
            "The following variables currently show little OK-versus-NG separation and can be treated as lower-priority screening factors: "
            + ", ".join(low_names)
            + "."
        )

    lines.append(
        "These findings identify candidate factors only. Root cause is confirmed only after process review, matched sampling, controlled verification or DOE."
    )

    return lines


def dataframe_to_html(df, columns=None, float_digits=3):
    if df is None or df.empty:
        return "<p>No data available.</p>"

    out = df.copy()

    if columns:
        columns = [c for c in columns if c in out.columns]
        out = out[columns]

    for c in out.select_dtypes(include=[np.number]).columns:
        out[c] = out[c].map(
            lambda x: "" if pd.isna(x) else f"{x:.{float_digits}f}"
        )

    return out.to_html(
        index=False,
        border=0,
        classes="report-table",
        escape=True,
    )


def _report_scope_values(
    df,
    quality_col,
    coil_col,
    order_col,
    date_col,
):
    n_rows = len(df)
    n_coils = df[coil_col].nunique() if coil_col in df.columns else n_rows
    n_orders = df[order_col].nunique() if order_col in df.columns else np.nan
    n_ng = int((df[quality_col] == "NG").sum())
    n_total = int(df[quality_col].isin(["OK", "NG"]).sum())
    ng_rate = n_ng / max(n_total, 1) * 100

    if date_col in df.columns and df[date_col].notna().any():
        date_text = (
            f"{df[date_col].min().strftime('%Y-%m-%d')} to "
            f"{df[date_col].max().strftime('%Y-%m-%d')}"
        )
    else:
        date_text = "Not available"

    return {
        "coils": n_coils,
        "orders": n_orders,
        "ng": n_ng,
        "ng_rate": ng_rate,
        "period": date_text,
    }


def _prepare_report_screening(screening_df, top_n=10):
    if screening_df is None or screening_df.empty:
        return pd.DataFrame()

    out = screening_df.copy()
    out["Screening Result"] = out.apply(
        classify_screening_result,
        axis=1,
    )
    return out.head(top_n).copy()


def _concise_mechanical_conclusion(mechanical_summary_df):
    if mechanical_summary_df is None or mechanical_summary_df.empty:
        return "No usable mechanical-property data are available."

    try:
        idx = mechanical_summary_df.set_index("Source Variable")
        statements = []

        if "HARDNESS_MEAN" in idx.index:
            d = idx.loc["HARDNESS_MEAN", "NG - OK"]
            if pd.notna(d):
                statements.append(
                    f"NG hardness is {'higher' if d > 0 else 'lower'} than OK."
                )

        if "EL" in idx.index:
            d = idx.loc["EL", "NG - OK"]
            if pd.notna(d):
                statements.append(
                    f"NG elongation is {'higher' if d > 0 else 'lower'} than OK."
                )

        if "YS" in idx.index:
            p = idx.loc["YS", "Mann-Whitney p"]
            if pd.notna(p) and p >= 0.05:
                statements.append(
                    "Yield strength difference is not statistically significant at p < 0.05."
                )

        if "TS" in idx.index:
            p = idx.loc["TS", "Mann-Whitney p"]
            if pd.notna(p) and p >= 0.05:
                statements.append(
                    "Tensile strength difference is not statistically significant at p < 0.05."
                )

        if (
            "HARDNESS_MEAN" in idx.index
            and "EL" in idx.index
        ):
            h = idx.loc["HARDNESS_MEAN", "NG - OK"]
            e = idx.loc["EL", "NG - OK"]
            if pd.notna(h) and pd.notna(e) and h < 0 and e > 0:
                statements.append(
                    "Current direction does not indicate poorer formability in NG; "
                    "mechanical properties are not the leading hypothesis."
                )

        return " ".join(statements) if statements else (
            "Mechanical-property differences are present but do not identify the AFP failure cause."
        )
    except Exception:
        return (
            "Mechanical-property differences are present but do not identify the AFP failure cause."
        )


def _key_result_sentence(screening_df):
    if screening_df is None or screening_df.empty:
        return "No reliable OK-versus-NG ranking is available."

    ranked = screening_df.dropna(subset=["|SMD|"]).copy()
    if ranked.empty:
        return "No reliable OK-versus-NG ranking is available."

    top = ranked.head(3)["Parameter"].tolist()
    return (
        "Highest OK-versus-NG separation: "
        + ", ".join(top)
        + ". These are screening priorities, not confirmed root causes."
    )


def generate_html_report(
    df,
    order_df,
    screening_df,
    order_summary_df,
    mechanical_summary_df,
    quality_col,
    coil_col,
    order_col,
    date_col,
):
    scope = _report_scope_values(
        df,
        quality_col,
        coil_col,
        order_col,
        date_col,
    )

    top_screening = _prepare_report_screening(
        screening_df,
        top_n=10,
    )

    limitation_text = order_level_limitation_text(
        df,
        order_col,
        quality_col,
    )

    key_sentence = _key_result_sentence(screening_df)
    mechanical_conclusion = _concise_mechanical_conclusion(
        mechanical_summary_df
    )

    screening_table = dataframe_to_html(
        top_screening,
        columns=[
            "Parameter",
            "Factor Role",
            "OK Mean",
            "NG Mean",
            "NG - OK",
            "|SMD|",
            "Mann-Whitney p",
            "Screening Result",
        ],
    )

    mechanical_table = dataframe_to_html(
        mechanical_summary_df,
        columns=[
            "Parameter",
            "OK Mean",
            "NG Mean",
            "NG - OK",
            "|SMD|",
            "Mann-Whitney p",
        ],
    )

    order_table = dataframe_to_html(
        order_summary_df,
        columns=[
            "Parameter",
            "OK Mean",
            "NG Mean",
            "NG - OK",
            "|SMD|",
            "Mann-Whitney p",
        ],
    )

    signed_smd_chart_html = ""
    try:
        signed_smd_fig = make_signed_smd_chart(
            screening_df,
            top_n=15,
        )
        if signed_smd_fig is not None:
            signed_smd_encoded = figure_to_base64(signed_smd_fig)
            signed_smd_chart_html = (
                '<div class="chart-card">'
                f'<img src="data:image/png;base64,{signed_smd_encoded}" '
                'alt="OK vs NG Direction and Separation (Signed SMD)">'
                '</div>'
            )
    except Exception:
        signed_smd_chart_html = ""

    supplier_chart_html = ""
    try:
        supplier_fig = make_supplier_benchmark_chart()
        supplier_encoded = figure_to_base64(supplier_fig)
        supplier_chart_html = (
            '<div class="chart-card">'
            f'<img src="data:image/png;base64,{supplier_encoded}" '
            'alt="Supplier Benchmark: Coating Weight vs Friction">'
            '</div>'
        )
    except Exception:
        supplier_chart_html = ""

    supplier_summary_html = dataframe_to_html(
        supplier_benchmark_summary(),
        columns=[
            "Benchmark Status",
            "Samples",
            "Mean_Coating_Weight",
            "Mean_Friction_60kgf",
            "Mean_Friction_120kgf",
            "Mean_Friction_240kgf",
        ],
    )

    internal_min_summary_html = dataframe_to_html(
        supplier_internal_link_summary(
            df,
            quality_col,
        ),
        columns=[
            "Parameter",
            "OK Mean",
            "NG Mean",
            "NG - OK",
            "SMD",
            "Mann-Whitney p",
        ],
    )

    smd_chart_html = ""
    try:
        smd_fig = make_smd_ranking_chart(
            screening_df,
            top_n=15,
        )
        if smd_fig is not None:
            smd_encoded = figure_to_base64(smd_fig)
            smd_chart_html = (
                '<div class="chart-card">'
                f'<img src="data:image/png;base64,{smd_encoded}" '
                'alt="OK vs NG Separation - Screening Only">'
                '</div>'
            )
    except Exception:
        smd_chart_html = ""

    chart_html = ""
    if screening_df is not None and not screening_df.empty:
        chart_blocks = []
        top_vars = (
            screening_df["Source Variable"]
            .dropna()
            .head(6)
            .tolist()
        )

        for variable in top_vars:
            if variable not in df.columns:
                continue
            try:
                fig = make_boxplot(
                    df,
                    variable,
                    quality_col,
                )
                encoded = figure_to_base64(fig)
                chart_blocks.append(
                    f"""
                    <div class="chart-card">
                        <img src="data:image/png;base64,{encoded}"
                             alt="{html_lib.escape(DISPLAY.get(variable, variable))}">
                    </div>
                    """
                )
            except Exception:
                pass

        if chart_blocks:
            chart_html = (
                '<div class="chart-grid">'
                + "".join(chart_blocks)
                + "</div>"
            )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AFP Coating OK vs NG Analysis Report</title>
<style>
body {{
    font-family: Arial, Helvetica, sans-serif;
    background: #f5f7fa;
    color: #1f2937;
}}
.page {{
    max-width: 1160px;
    margin: 24px auto;
    background: white;
    padding: 32px 38px;
}}
h2 {{
    border-bottom: 1px solid #d1d5db;
    padding-bottom: 6px;
    margin-top: 28px;
}}
.kpi-grid {{
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
}}
.kpi {{
    border: 1px solid #e5e7eb;
    padding: 12px;
}}
.kpi-label {{ font-size: 11px; color: #6b7280; }}
.kpi-value {{ font-size: 18px; font-weight: bold; }}
.report-table {{
    border-collapse: collapse;
    width: 100%;
    font-size: 12px;
}}
.report-table th, .report-table td {{
    border: 1px solid #d1d5db;
    padding: 6px;
}}
.report-table th {{ background: #f3f4f6; }}
.summary-box {{
    border-left: 4px solid #374151;
    background: #f9fafb;
    padding: 12px 16px;
    margin: 10px 0;
}}
.chart-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
}}
.chart-card img {{ width: 100%; }}
.note {{ font-size: 12px; color: #6b7280; }}
</style>
</head>
<body>
<div class="page">

<h1>AFP Coating OK vs NG Analysis Report</h1>
<p>Customer issue: AFP peeling / powder shedding after deep drawing or forming.</p>

<h2>1. Analysis Scope</h2>
<div class="kpi-grid">
<div class="kpi"><div class="kpi-label">Period</div><div class="kpi-value" style="font-size:13px;">{scope["period"]}</div></div>
<div class="kpi"><div class="kpi-label">Coils</div><div class="kpi-value">{scope["coils"]}</div></div>
<div class="kpi"><div class="kpi-label">Orders</div><div class="kpi-value">{int(scope["orders"]) if pd.notna(scope["orders"]) else "N/A"}</div></div>
<div class="kpi"><div class="kpi-label">NG Records</div><div class="kpi-value">{scope["ng"]}</div></div>
<div class="kpi"><div class="kpi-label">NG Rate</div><div class="kpi-value">{scope["ng_rate"]:.1f}%</div></div>
</div>

<h2>2. Key Findings</h2>
<div class="summary-box">{html_lib.escape(key_sentence)}</div>
<div class="summary-box"><strong>Data limitation:</strong> {html_lib.escape(limitation_text)}</div>

<h2>3. Candidate Factor Ranking</h2>
{screening_table}
<p class="note">
p &lt; 0.05 supports a statistical OK-NG difference. |SMD| indicates the size of the difference.
These results do not prove root cause.
</p>

<h2>4. OK vs NG Direction and Separation (Signed SMD)</h2>
{signed_smd_chart_html if signed_smd_chart_html else "<p>No trend chart available.</p>"}
<p class="note">
Positive SMD means NG &gt; OK; negative SMD means NG &lt; OK.
The absolute magnitude indicates standardized OK-NG separation strength.
</p>


<h2>5. OK vs NG Screening Priority</h2>
{smd_chart_html if smd_chart_html else "<p>No screening chart available.</p>"}
<p class="note">
This chart ranks variables by |SMD|. A longer bar means stronger OK-NG separation,
but it does not identify root cause or direction.
</p>

<h2>6. Top Factor Boxplots - OK vs NG Distribution</h2>
{chart_html if chart_html else "<p>No chart available.</p>"}
<p class="note">
Boxplots show the actual distribution of OK and NG values. Greater separation and less overlap
support a stronger screening signal; overlap means the factor alone may not explain all NG cases.
</p>

<h2>7. Supporting Analysis - Mechanical Properties</h2>
{mechanical_table}
<div class="summary-box">{html_lib.escape(mechanical_conclusion)}</div>

<h2>8. Supporting Analysis - Surface QC</h2>
{order_table}
<p class="note">
If one representative coil is used for the complete order, these results are descriptive at ORDER level.
</p>

<h2>9. Recommended Next Actions</h2>
<ol>
<li>Collect additional independent OK and NG orders.</li>
<li>Verify the top 2-3 screening factors with matched samples or a controlled trial.</li>
<li>Record peeling and powder shedding separately after customer-equivalent forming.</li>
<li>After verification, establish process control limits and a reaction plan.</li>
</ol>


</div>
</body>
</html>
"""


def _set_cell_shading(cell, fill="D9EAF7"):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _add_word_table(document, df, columns, max_rows=None):
    if df is None or df.empty:
        document.add_paragraph("No data available.")
        return

    use_cols = [c for c in columns if c in df.columns]
    if not use_cols:
        document.add_paragraph("No data available.")
        return

    out = df[use_cols].copy()
    if max_rows is not None:
        out = out.head(max_rows)

    table = document.add_table(
        rows=1,
        cols=len(use_cols),
    )
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for i, col in enumerate(use_cols):
        cell = table.rows[0].cells[i]
        cell.text = str(col)
        _set_cell_shading(cell)
        for run in cell.paragraphs[0].runs:
            run.bold = True
            run.font.size = Pt(8)

    for _, row in out.iterrows():
        cells = table.add_row().cells
        for i, col in enumerate(use_cols):
            value = row[col]
            if pd.isna(value):
                txt = ""
            elif isinstance(value, (float, np.floating)):
                txt = (
                    f"{value:.4f}"
                    if col == "Mann-Whitney p"
                    else f"{value:.3f}"
                )
            else:
                txt = str(value)

            cells[i].text = txt
            cells[i].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for p in cells[i].paragraphs:
                for run in p.runs:
                    run.font.size = Pt(8)


def generate_word_report(
    df,
    screening_df,
    order_summary_df,
    mechanical_summary_df,
    quality_col,
    coil_col,
    order_col,
    date_col,
):
    scope = _report_scope_values(
        df,
        quality_col,
        coil_col,
        order_col,
        date_col,
    )

    top_screening = _prepare_report_screening(
        screening_df,
        top_n=10,
    )

    limitation_text = order_level_limitation_text(
        df,
        order_col,
        quality_col,
    )
    key_sentence = _key_result_sentence(screening_df)
    mechanical_conclusion = _concise_mechanical_conclusion(
        mechanical_summary_df
    )

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.55)
    section.right_margin = Inches(0.55)

    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(9)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("AFP Coating OK vs NG Analysis Report")
    r.bold = True
    r.font.name = "Arial"
    r.font.size = Pt(16)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(
        "Customer issue: AFP peeling / powder shedding after deep drawing or forming"
    )
    r.italic = True
    r.font.size = Pt(9)

    doc.add_heading("1. Analysis Scope", level=1)
    scope_table = doc.add_table(rows=2, cols=5)
    scope_table.style = "Table Grid"
    headers = ["Period", "Coils", "Orders", "NG Records", "NG Rate"]
    values = [
        scope["period"],
        scope["coils"],
        int(scope["orders"]) if pd.notna(scope["orders"]) else "N/A",
        scope["ng"],
        f'{scope["ng_rate"]:.1f}%',
    ]
    for i, val in enumerate(headers):
        scope_table.cell(0, i).text = str(val)
        _set_cell_shading(scope_table.cell(0, i))
        for run in scope_table.cell(0, i).paragraphs[0].runs:
            run.bold = True
            run.font.size = Pt(8)
    for i, val in enumerate(values):
        scope_table.cell(1, i).text = str(val)
        for run in scope_table.cell(1, i).paragraphs[0].runs:
            run.font.size = Pt(8)

    doc.add_heading("2. Key Findings", level=1)
    p = doc.add_paragraph()
    p.add_run("Main result: ").bold = True
    p.add_run(key_sentence)
    p = doc.add_paragraph()
    p.add_run("Data limitation: ").bold = True
    p.add_run(limitation_text)

    doc.add_heading("3. Candidate Factor Ranking", level=1)
    _add_word_table(
        doc,
        top_screening,
        [
            "Parameter",
            "Factor Role",
            "OK Mean",
            "NG Mean",
            "NG - OK",
            "|SMD|",
            "Mann-Whitney p",
            "Screening Result",
        ],
        max_rows=10,
    )
    p = doc.add_paragraph(
        "Note: p < 0.05 supports a statistical OK-NG difference; "
        "|SMD| indicates the size of the difference. "
        "These results do not prove root cause."
    )
    for run in p.runs:
        run.italic = True
        run.font.size = Pt(8)


    doc.add_heading("4. OK vs NG Direction and Separation (Signed SMD)", level=1)

    try:
        signed_smd_fig = make_signed_smd_chart(
            screening_df,
            top_n=15,
        )

        if signed_smd_fig is not None:
            signed_smd_buffer = io.BytesIO()
            signed_smd_fig.savefig(
                signed_smd_buffer,
                format="png",
                dpi=160,
                bbox_inches="tight",
            )
            plt.close(signed_smd_fig)
            signed_smd_buffer.seek(0)

            doc.add_picture(
                signed_smd_buffer,
                width=Inches(6.8),
            )

            p = doc.add_paragraph(
                "Positive SMD means NG > OK; negative SMD means NG < OK. "
                "The absolute magnitude indicates standardized separation strength."
            )
            for run in p.runs:
                run.italic = True
                run.font.size = Pt(8)
    except Exception:
        doc.add_paragraph(
            "OK vs NG relative difference chart could not be generated."
        )

    doc.add_heading("5. OK vs NG Screening Priority", level=1)

    try:
        smd_fig = make_smd_ranking_chart(
            screening_df,
            top_n=15,
        )

        if smd_fig is not None:
            image_buffer = io.BytesIO()
            smd_fig.savefig(
                image_buffer,
                format="png",
                dpi=160,
                bbox_inches="tight",
            )
            plt.close(smd_fig)
            image_buffer.seek(0)

            doc.add_picture(
                image_buffer,
                width=Inches(6.8),
            )

            p = doc.add_paragraph(
                "The chart ranks variables by |SMD|. "
                "Longer bars indicate stronger OK-NG separation only; "
                "they do not prove root cause or show direction."
            )
            for run in p.runs:
                run.italic = True
                run.font.size = Pt(8)
    except Exception:
        doc.add_paragraph(
            "Screening ranking chart could not be generated."
        )

    doc.add_heading("6. Top Factor Boxplots - OK vs NG Distribution", level=1)

    try:
        top_box_vars = (
            screening_df["Source Variable"]
            .dropna()
            .head(6)
            .tolist()
            if screening_df is not None and not screening_df.empty
            else []
        )

        if not top_box_vars:
            doc.add_paragraph("No boxplot variables are available.")
        else:
            for variable in top_box_vars:
                if variable not in df.columns:
                    continue

                fig = make_boxplot(
                    df,
                    variable,
                    quality_col,
                    title=DISPLAY.get(variable, variable),
                )

                box_buffer = io.BytesIO()
                fig.savefig(
                    box_buffer,
                    format="png",
                    dpi=160,
                    bbox_inches="tight",
                )
                plt.close(fig)
                box_buffer.seek(0)

                doc.add_picture(
                    box_buffer,
                    width=Inches(6.4),
                )

            p = doc.add_paragraph(
                "Boxplots show the actual OK and NG distributions. "
                "Greater separation and less overlap support a stronger screening signal; "
                "overlap indicates that the factor alone may not explain all NG cases."
            )
            for run in p.runs:
                run.italic = True
                run.font.size = Pt(8)

    except Exception as exc:
        doc.add_paragraph(
            f"Boxplots could not be generated: {exc}"
        )

    doc.add_heading("7. Supporting Analysis - Mechanical Properties", level=1)
    _add_word_table(
        doc,
        mechanical_summary_df,
        [
            "Parameter",
            "OK Mean",
            "NG Mean",
            "NG - OK",
            "|SMD|",
            "Mann-Whitney p",
        ],
    )
    doc.add_paragraph(mechanical_conclusion)

    doc.add_heading("8. Supporting Analysis - Surface QC", level=1)
    _add_word_table(
        doc,
        order_summary_df,
        [
            "Parameter",
            "OK Mean",
            "NG Mean",
            "NG - OK",
            "|SMD|",
            "Mann-Whitney p",
        ],
    )

    doc.add_heading("9. Supplier Benchmark Analysis", level=1)

    p = doc.add_paragraph()
    p.add_run("Supplier experimental risk benchmark: ").bold = True
    p.add_run(
        "Coating weight < 700 mg/m². "
        "This is supporting technical evidence and is not an internal specification limit."
    )

    supplier_summary_df = supplier_benchmark_summary()
    _add_word_table(
        doc,
        supplier_summary_df,
        [
            "Benchmark Status",
            "Samples",
            "Mean_Coating_Weight",
            "Mean_Friction_60kgf",
            "Mean_Friction_120kgf",
            "Mean_Friction_240kgf",
        ],
    )

    try:
        supplier_fig = make_supplier_benchmark_chart()
        supplier_buffer = io.BytesIO()
        supplier_fig.savefig(
            supplier_buffer,
            format="png",
            dpi=160,
            bbox_inches="tight",
        )
        plt.close(supplier_fig)
        supplier_buffer.seek(0)

        doc.add_picture(
            supplier_buffer,
            width=Inches(6.6),
        )
    except Exception as exc:
        doc.add_paragraph(
            f"Supplier benchmark chart could not be generated: {exc}"
        )

    internal_min_summary = supplier_internal_link_summary(
        df,
        quality_col,
    )

    if not internal_min_summary.empty:
        doc.add_paragraph("Internal AFP Minimum Thickness Comparison")
        _add_word_table(
            doc,
            internal_min_summary,
            [
                "Parameter",
                "OK Mean",
                "NG Mean",
                "NG - OK",
                "SMD",
                "Mann-Whitney p",
            ],
        )

    p = doc.add_paragraph(
        "Supplier coating weight is measured in mg/m² while internal AFP thickness is measured in µm. "
        "No direct conversion is applied until dry-film density or an empirical calibration is available."
    )
    for run in p.runs:
        run.italic = True
        run.font.size = Pt(8)

    doc.add_heading("10. Recommended Next Actions", level=1)

    actions = [
        "Collect additional independent OK and NG orders.",
        "Verify the top 2-3 screening factors with matched samples or a controlled trial.",
        "Record peeling and powder shedding separately after customer-equivalent forming.",
        "After verification, establish process control limits and a reaction plan.",
    ]
    for action in actions:
        doc.add_paragraph(action, style="List Bullet")

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


# ============================================================
# FILE UPLOAD
# ============================================================
with st.sidebar:
    st.header("Data Input")
    uploaded_file = st.file_uploader(
        "Upload production data",
        type=["xlsx", "xls", "csv"],
    )

if uploaded_file is None:
    st.info("Upload an Excel or CSV file to start the analysis.")
    st.stop()


# ============================================================
# LOAD DATA
# ============================================================
try:
    if uploaded_file.name.lower().endswith(".csv"):
        raw_df = pd.read_csv(uploaded_file)
    else:
        raw_df = pd.read_excel(uploaded_file)
except Exception as exc:
    st.error(f"Unable to read the uploaded file: {exc}")
    st.stop()

df = raw_df.copy()
df.columns = [clean_column_name(c) for c in df.columns]

# Warn if the uploaded source contains duplicate column names.
duplicate_source_columns = (
    pd.Index(df.columns)[pd.Index(df.columns).duplicated()].unique().tolist()
)
if duplicate_source_columns:
    st.warning(
        "Duplicate source column names detected: "
        + ", ".join(map(str, duplicate_source_columns))
        + ". The Data Detail view will keep the first occurrence for display. "
        "Please check the source Excel header if these columns are expected to be different."
    )

quality_col = COL["quality"]
coil_col = COL["coil"]
order_col = COL["order"]
date_col = COL["date"]

if quality_col not in df.columns:
    st.error(f"Required column not found: {quality_col}")
    with st.expander("Available columns"):
        st.write(list(df.columns))
    st.stop()

df[quality_col] = df[quality_col].map(normalize_quality)
df = df[df[quality_col].isin(["OK", "NG"])].copy()

if date_col in df.columns:
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")


# ============================================================
# RESOLVE LOWER-SIDE AFP COLUMN NAMES
# ============================================================
down_n = find_first_existing(df, COL["down_n_candidates"])
down_c = find_first_existing(df, COL["down_c_candidates"])
down_s = find_first_existing(df, COL["down_s_candidates"])

top_afp_cols = [
    c for c in [COL["up_n"], COL["up_c"], COL["up_s"]]
    if c in df.columns
]

bottom_afp_cols = [
    c for c in [down_n, down_c, down_s]
    if c and c in df.columns
]


# ============================================================
# NUMERIC CONVERSION
# ============================================================
numeric_source_columns = [
    COL["oven_temp"],
    COL["roll_temp"],
    COL["up_n"],
    COL["up_c"],
    COL["up_s"],
    down_n,
    down_c,
    down_s,
    COL["slip"],
    COL["roughness"],
    COL["xray_top_n"],
    COL["xray_top_c"],
    COL["xray_top_s"],
    COL["xray_bottom_n"],
    COL["xray_bottom_c"],
    COL["xray_bottom_s"],
    COL["hardness_s"],
    COL["hardness_n"],
    COL["ys"],
    COL["ts"],
    COL["el"],
]

for c in numeric_source_columns:
    if c and c in df.columns:
        df[c] = df[c].map(parse_numeric_value)


# ============================================================
# DERIVED METRICS
# ============================================================
# Main AFP thickness metrics
if top_afp_cols:
    df["AFP_TOP_MEAN"] = numeric_mean(df, top_afp_cols)
    df["AFP_TOP_RANGE"] = numeric_range(df, top_afp_cols)

if bottom_afp_cols:
    df["AFP_BOTTOM_MEAN"] = numeric_mean(df, bottom_afp_cols)
    df["AFP_BOTTOM_RANGE"] = numeric_range(df, bottom_afp_cols)


df["AFP_UP_MINIMUM"] = numeric_minimum(
    df,
    [COL["up_n"], COL["up_c"], COL["up_s"]],
)

df["AFP_DOWN_MINIMUM"] = numeric_minimum(
    df,
    [down_n_col, down_c_col, down_s_col],
)


# Metal coating thickness
xray_top_cols = [
    c for c in [
        COL["xray_top_n"],
        COL["xray_top_c"],
        COL["xray_top_s"],
    ]
    if c in df.columns
]

xray_bottom_cols = [
    c for c in [
        COL["xray_bottom_n"],
        COL["xray_bottom_c"],
        COL["xray_bottom_s"],
    ]
    if c in df.columns
]

if xray_top_cols:
    df["XRAY_TOP_MEAN"] = numeric_mean(df, xray_top_cols)

if xray_bottom_cols:
    df["XRAY_BOTTOM_MEAN"] = numeric_mean(df, xray_bottom_cols)

if "XRAY_TOP_MEAN" in df.columns and "XRAY_BOTTOM_MEAN" in df.columns:
    df["XRAY_TOTAL"] = (
        df["XRAY_TOP_MEAN"] + df["XRAY_BOTTOM_MEAN"]
    )
    df["XRAY_SIDE_DIFFERENCE"] = (
        df["XRAY_TOP_MEAN"] - df["XRAY_BOTTOM_MEAN"]
    ).abs()


# Steel hardness
hardness_cols = [
    c for c in [COL["hardness_s"], COL["hardness_n"]]
    if c in df.columns
]

if hardness_cols:
    df["HARDNESS_MEAN"] = numeric_mean(df, hardness_cols)

if len(hardness_cols) == 2:
    df["HARDNESS_DIFFERENCE"] = (
        pd.to_numeric(df[hardness_cols[0]], errors="coerce")
        - pd.to_numeric(df[hardness_cols[1]], errors="coerce")
    ).abs()


# Mechanical properties
if COL["ys"] in df.columns:
    df["YS"] = pd.to_numeric(df[COL["ys"]], errors="coerce")

if COL["ts"] in df.columns:
    df["TS"] = pd.to_numeric(df[COL["ts"]], errors="coerce")

if COL["el"] in df.columns:
    df["EL"] = pd.to_numeric(df[COL["el"]], errors="coerce")


# ============================================================
# SIDEBAR FILTERS
# ============================================================
with st.sidebar:
    st.header("Filters")

    if date_col in df.columns and df[date_col].notna().any():
        min_date = df[date_col].min().date()
        max_date = df[date_col].max().date()

        selected_dates = st.date_input(
            "Production date",
            value=(min_date, max_date),
        )

        if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
            start_date = pd.Timestamp(selected_dates[0])
            end_date = pd.Timestamp(selected_dates[1]) + pd.Timedelta(days=1)

            df = df[
                (df[date_col] >= start_date)
                & (df[date_col] < end_date)
            ].copy()

    if order_col in df.columns:
        order_options = sorted(
            df[order_col].dropna().astype(str).unique()
        )

        selected_orders = st.multiselect(
            "ORDER_NUMBER",
            order_options,
        )

        if selected_orders:
            df = df[
                df[order_col].astype(str).isin(selected_orders)
            ].copy()


# ============================================================
# VARIABLE GROUPS
# ============================================================
process_variables = numeric_variables_available(
    df,
    [
        COL["oven_temp"],
        COL["roll_temp"],
    ],
)

main_afp_variables = numeric_variables_available(
    df,
    [
        "AFP_TOP_MEAN",
        "AFP_BOTTOM_MEAN",

    ],
)

afp_uniformity_variables = numeric_variables_available(
    df,
    [
        "AFP_TOP_RANGE",
        "AFP_BOTTOM_RANGE",

    ],
)

metal_coating_variables = numeric_variables_available(
    df,
    [
        "XRAY_TOP_MEAN",
        "XRAY_BOTTOM_MEAN",
        "XRAY_TOTAL",
        "XRAY_SIDE_DIFFERENCE",
    ],
)

mechanical_variables = numeric_variables_available(
    df,
    [
        "HARDNESS_MEAN",
        "HARDNESS_DIFFERENCE",
        "YS",
        "TS",
        "EL",
    ],
)

order_level_qc_columns = [
    c for c in [
        COL["slip"],
        COL["adhesion"],
        COL["wear"],
        COL["roughness"],
    ]
    if c in df.columns
]

order_df = prepare_order_level_data(
    df,
    order_col,
    quality_col,
    order_level_qc_columns,
)

order_numeric_variables = numeric_variables_available(
    order_df,
    order_level_qc_columns,
) if not order_df.empty else []


# ============================================================
# KPI HEADER
# ============================================================
row_count = len(df)
coil_count = (
    df[coil_col].nunique()
    if coil_col in df.columns
    else row_count
)
order_count = (
    df[order_col].nunique()
    if order_col in df.columns
    else np.nan
)

ok_count = int((df[quality_col] == "OK").sum())
ng_count = int((df[quality_col] == "NG").sum())

total_classified = ok_count + ng_count
ng_rate = (
    ng_count / total_classified * 100
    if total_classified > 0
    else np.nan
)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Rows", f"{row_count:,}")
k2.metric("Unique Coils", f"{coil_count:,}")
k3.metric(
    "Orders",
    f"{int(order_count):,}"
    if pd.notna(order_count)
    else "N/A",
)
k4.metric("NG Rows", f"{ng_count:,}")
k5.metric(
    "NG Rate",
    f"{ng_rate:.1f}%"
    if pd.notna(ng_rate)
    else "N/A",
)


# ============================================================
# DASHBOARD TABS
# ============================================================
tabs = st.tabs(
    [
        "Executive Summary",
        "AFP Film Thickness",
        "Process Conditions",
        "Surface QC",
        "Mechanical Properties",
        "Root Cause Screening",
        "Data Detail",
        "Report Export",
    ]
)


# ============================================================
# TAB 1 - EXECUTIVE SUMMARY
# ============================================================
with tabs[0]:
    st.subheader("Executive OK vs NG Comparison")

    candidate_variables = (
        process_variables
        + main_afp_variables
        + afp_uniformity_variables
        + metal_coating_variables
        + mechanical_variables
    )

    summary = build_summary(
        df,
        candidate_variables,
        quality_col,
    )

    if summary.empty:
        st.warning(
            "Not enough numeric OK/NG data is available for comparison."
        )
    else:
        st.markdown("#### Main coil-level differences")

        display_summary = summary.drop(
            columns=["Source Variable"],
            errors="ignore",
        ).copy()

        st.dataframe(
            display_summary.style.format(
                {
                    "OK Mean": "{:.3f}",
                    "OK Median": "{:.3f}",
                    "NG Mean": "{:.3f}",
                    "NG Median": "{:.3f}",
                    "NG - OK": "{:+.3f}",
                    "SMD": "{:+.2f}",
                    "|SMD|": "{:.2f}",
                    "Mann-Whitney p": "{:.4f}",
                }
            ),
            use_container_width=True,
        )

        st.caption(
            "SMD measures the size of the OK-NG difference. "
            "A large absolute SMD indicates stronger separation, "
            "but does not prove causation."
        )

        top_source_variables = (
            summary["Source Variable"]
            .dropna()
            .head(4)
            .tolist()
        )

        if top_source_variables:
            chart_cols = st.columns(2)

            for i, variable in enumerate(top_source_variables):
                with chart_cols[i % 2]:
                    st.pyplot(
                        make_boxplot(
                            df,
                            variable,
                            quality_col,
                        ),
                        use_container_width=True,
                    )

    if not order_df.empty:
        st.markdown("#### Representative surface QC")

        st.info(
            "Slip / COF, adhesion, wear resistance and roughness "
            "are evaluated once per ORDER_NUMBER because one sampled "
            "coil may represent the complete order."
        )

        if order_numeric_variables:
            order_summary = build_summary(
                order_df,
                order_numeric_variables,
                quality_col,
            )

            st.dataframe(
                order_summary.drop(
                    columns=["Source Variable"],
                    errors="ignore",
                ),
                use_container_width=True,
            )


# ============================================================
# TAB 2 - AFP FILM THICKNESS
# ============================================================
with tabs[1]:
    st.subheader("AFP Film Thickness")

    st.info(
        "AFP膜厚(um) is interpreted as Up / Down thickness. "
        "Example: 1.07/1.20 means Up = 1.07 µm and Down = 1.20 µm. "
        "The dashboard does not average the Up and Down values together."
    )

    st.markdown("#### Main thickness metrics")

    if not main_afp_variables:
        st.warning(
            "No AFP film-thickness columns were recognized."
        )
    else:
        main_afp_summary = build_summary(
            df,
            main_afp_variables,
            quality_col,
        )

        st.dataframe(
            main_afp_summary.drop(
                columns=["Source Variable"],
                errors="ignore",
            ),
            use_container_width=True,
        )

        selected_afp = st.selectbox(
            "Select a film-thickness metric",
            main_afp_variables,
            format_func=lambda x: DISPLAY.get(x, x),
            key="main_afp_metric",
        )

        st.pyplot(
            make_boxplot(
                df,
                selected_afp,
                quality_col,
            ),
            use_container_width=True,
        )

    with st.expander(
        "Film thickness uniformity - derived metrics",
        expanded=False,
    ):
        st.write(
            "These variables are calculated by the dashboard. "
            "They are not raw source columns."
        )

        metric_definition = pd.DataFrame(
            [
                {
                    "Metric": "AFP Top Thickness Range",
                    "Definition": "Maximum minus minimum of North, Center and South on the top side",
                },
                {
                    "Metric": "AFP Bottom Thickness Range",
                    "Definition": "Maximum minus minimum of North, Center and South on the bottom side",
                },
                {
                    "Metric": "",
                    "Definition": "Maximum minus minimum across all available AFP measurement points",
                },
                {
                    "Metric": " (%)",
                    "Definition": "Standard deviation divided by mean thickness, multiplied by 100",
                },
            ]
        )

        st.dataframe(
            metric_definition,
            hide_index=True,
            use_container_width=True,
        )

        if afp_uniformity_variables:
            uniformity_summary = build_summary(
                df,
                afp_uniformity_variables,
                quality_col,
            )

            st.dataframe(
                uniformity_summary.drop(
                    columns=["Source Variable"],
                    errors="ignore",
                ),
                use_container_width=True,
            )


# ============================================================
# TAB 3 - PROCESS CONDITIONS
# ============================================================
with tabs[2]:
    st.subheader("Process Conditions")

    st.write(
        "Oven temperature and roll temperature are treated as "
        "candidate process factors. Their influence should be evaluated "
        "together with AFP film thickness and surface performance."
    )

    if not process_variables:
        st.warning(
            "No process temperature variables were found."
        )
    else:
        process_summary = build_summary(
            df,
            process_variables,
            quality_col,
        )

        st.dataframe(
            process_summary.drop(
                columns=["Source Variable"],
                errors="ignore",
            ),
            use_container_width=True,
        )

        chart_cols = st.columns(
            min(2, len(process_variables))
        )

        for i, variable in enumerate(process_variables):
            with chart_cols[i % len(chart_cols)]:
                st.pyplot(
                    make_boxplot(
                        df,
                        variable,
                        quality_col,
                    ),
                    use_container_width=True,
                )


# ============================================================
# TAB 4 - SURFACE QC
# ============================================================
with tabs[3]:
    st.subheader("Surface QC - Order-Level Analysis")

    st.info(
        "These measurements are analyzed at ORDER_NUMBER level. "
        "This prevents one representative measurement from being "
        "incorrectly counted as multiple independent coil measurements."
    )

    if not order_df.empty and len(order_df) <= 2:
        st.warning(
            "Insufficient replication: current representative Surface QC contains only "
            f"{len(order_df)} independent order-level observations. "
            "These values are descriptive only and should not be used for statistical root-cause confirmation."
        )

    if order_df.empty:
        st.warning(
            "No order-level surface QC data was found."
        )
    else:
        # Numeric QC
        if order_numeric_variables:
            qc_summary = build_summary(
                order_df,
                order_numeric_variables,
                quality_col,
            )

            st.dataframe(
                qc_summary.drop(
                    columns=["Source Variable"],
                    errors="ignore",
                ),
                use_container_width=True,
            )

            selected_qc = st.selectbox(
                "Select a numeric surface QC metric",
                order_numeric_variables,
                format_func=lambda x: DISPLAY.get(x, x),
                key="surface_qc_metric",
            )

            st.pyplot(
                make_boxplot(
                    order_df,
                    selected_qc,
                    quality_col,
                ),
                use_container_width=True,
            )

        # Categorical QC
        st.markdown("#### Categorical surface QC")

        categorical_found = False

        for c in order_level_qc_columns:
            if c not in order_df.columns:
                continue

            numeric_ratio = (
                pd.to_numeric(
                    order_df[c],
                    errors="coerce",
                ).notna().mean()
            )

            if numeric_ratio < 0.5:
                categorical_found = True
                st.markdown(
                    f"**{DISPLAY.get(c, c)}**"
                )

                frequency = pd.crosstab(
                    order_df[c].astype(str),
                    order_df[quality_col],
                    margins=True,
                )

                st.dataframe(
                    frequency,
                    use_container_width=True,
                )

        if not categorical_found:
            st.caption(
                "No categorical surface-QC variable was detected."
            )


# ============================================================
# TAB 5 - MECHANICAL PROPERTIES
# ============================================================
with tabs[4]:
    st.subheader("Mechanical Properties and Formability")

    st.write(
        "Yield strength, tensile strength, elongation and hardness "
        "describe the steel substrate. They can change the strain and "
        "stress transferred to the AFP layer during deep drawing."
    )

    if not mechanical_variables:
        st.warning(
            "No usable mechanical-property variables were found."
        )
    else:
        mech_summary = build_summary(
            df,
            mechanical_variables,
            quality_col,
        )

        st.dataframe(
            mech_summary.drop(
                columns=["Source Variable"],
                errors="ignore",
            ),
            use_container_width=True,
        )

        selected_mech = st.selectbox(
            "Select a mechanical-property metric",
            mechanical_variables,
            format_func=lambda x: DISPLAY.get(x, x),
            key="mechanical_metric",
        )

        st.pyplot(
            make_boxplot(
                df,
                selected_mech,
                quality_col,
            ),
            use_container_width=True,
        )


# ============================================================
# TAB 6 - ROOT CAUSE SCREENING
# ============================================================
with tabs[5]:
    st.subheader("Root Cause Screening")

    st.warning(
        "This page screens candidate factors associated with NG. "
        "Association does not prove root cause. A suspected factor must "
        "be verified by process review, controlled trial or DOE."
    )

    st.error(order_level_limitation_text(df, order_col, quality_col))

    screening_variables = (
        process_variables
        + main_afp_variables
        + afp_uniformity_variables
        + metal_coating_variables
        + mechanical_variables
    )

    screening = build_summary(
        df,
        screening_variables,
        quality_col,
    )

    if screening.empty:
        st.warning(
            "Not enough data is available for root-cause screening."
        )
    else:
        st.info(build_working_hypothesis(screening))

        st.markdown("#### OK vs NG Direction and Separation (Signed SMD)")
        signed_smd_fig = make_signed_smd_chart(
            screening,
            top_n=15,
        )
        if signed_smd_fig is not None:
            st.pyplot(
                signed_smd_fig,
                use_container_width=True,
            )
        st.caption(
            "Positive SMD means NG > OK; negative SMD means NG < OK. "
            "The absolute magnitude shows standardized separation strength."
        )
        screening["Screening Priority"] = pd.cut(
            screening["|SMD|"],
            bins=[
                -np.inf,
                0.20,
                0.50,
                0.80,
                np.inf,
            ],
            labels=[
                "Low",
                "Moderate",
                "High",
                "Very High",
            ],
        )

        st.dataframe(
            screening[
                [
                    "Parameter",
                    "Factor Role",
                    "OK n",
                    "OK Mean",
                    "NG n",
                    "NG Mean",
                    "NG - OK",
                    "SMD",
                    "|SMD|",
                    "Mann-Whitney p",
                    "Screening Priority",
                    "Technical Interpretation",
                ]
            ],
            use_container_width=True,
        )

        chart_df = (
            screening
            .dropna(subset=["|SMD|"])
            .head(15)
            .sort_values("|SMD|")
        )

        if not chart_df.empty:
            fig, ax = plt.subplots(
                figsize=(
                    8,
                    max(
                        4.5,
                        0.40 * len(chart_df) + 1,
                    ),
                )
            )

            ax.barh(
                chart_df["Parameter"],
                chart_df["|SMD|"],
            )

            ax.set_xlabel(
                "Absolute Standardized Mean Difference"
            )

            ax.set_title(
                "OK vs NG Separation - Screening Only",
                fontweight="bold",
            )

            ax.grid(
                axis="x",
                alpha=0.25,
            )

            fig.tight_layout()
            st.pyplot(
                fig,
                use_container_width=True,
            )

    st.caption(
        "Multivariable machine-learning ranking is intentionally disabled at the current sample size. "
        "Use additional independent OK/NG orders before multivariable modeling."
    )

    st.markdown("#### Root-cause logic")

    st.code(
        "Process / Material Factors\n"
        "        |\n"
        "        v\n"
        "AFP Film Thickness and Uniformity\n"
        "        |\n"
        "        v\n"
        "Surface / Adhesion / Wear Behavior\n"
        "        |\n"
        "        v\n"
        "Peeling / Powder Shedding (掉粉) / White Powder after Deep Drawing",
        language="text",
    )


    st.markdown("#### Supplier Benchmark Analysis")

    st.info(
        "Supplier experimental benchmark: coating weight below 700 mg/m² is treated as a "
        "risk benchmark from supplier simulation data, not as an internal specification limit."
    )

    supplier_summary_df = supplier_benchmark_summary()
    st.dataframe(
        supplier_summary_df,
        use_container_width=True,
        hide_index=True,
    )

    supplier_fig = make_supplier_benchmark_chart()
    st.pyplot(
        supplier_fig,
        use_container_width=True,
    )

    st.caption(
        "Supplier evidence is used only to support the mechanism that lower coating weight "
        "can be associated with higher friction. It is not mixed into internal SMD or p-value ranking."
    )

    internal_min_summary = supplier_internal_link_summary(
        df,
        quality_col,
    )

    if not internal_min_summary.empty:
        st.markdown("##### Internal AFP minimum thickness comparison")
        st.dataframe(
            internal_min_summary.drop(
                columns=["Source Variable"],
                errors="ignore",
            ),
            use_container_width=True,
            hide_index=True,
        )

        for variable in [
            v for v in ["AFP_UP_MINIMUM", "AFP_DOWN_MINIMUM"]
            if v in df.columns
        ]:
            st.pyplot(
                make_boxplot(
                    df,
                    variable,
                    quality_col,
                ),
                use_container_width=True,
            )

    st.warning(
        "Direct conversion of the supplier benchmark 700 mg/m² to internal AFP thickness (µm) "
        "is not performed because dry-film density or an empirical mg/m²-to-µm calibration is not yet available."
    )


# ============================================================
# TAB 7 - DATA DETAIL
# ============================================================
with tabs[6]:
    st.subheader("Cleaned and Derived Data")

    default_columns = [
        coil_col,
        order_col,
        date_col,
        quality_col,
        COL["oven_temp"],
        COL["roll_temp"],
        "AFP_TOP_MEAN",
        "AFP_BOTTOM_MEAN",

        "XRAY_TOTAL",
        "HARDNESS_MEAN",
        "YS",
        "TS",
        "EL",
    ]

    # Keep only existing columns and remove duplicate names while
    # preserving their original display order. PyArrow / Streamlit
    # cannot render a DataFrame with duplicate column names.
    default_columns = list(
        dict.fromkeys(
            c for c in default_columns
            if c in df.columns
        )
    )

    # The source file itself may also contain duplicate column names.
    # Use unique options for the selector and protect the rendered
    # DataFrame against duplicate selections.
    available_display_columns = list(dict.fromkeys(df.columns.tolist()))

    selected_columns = st.multiselect(
        "Columns to display",
        options=available_display_columns,
        default=default_columns,
    )

    if not selected_columns:
        selected_columns = default_columns

    selected_columns = list(dict.fromkeys(selected_columns))

    detail_df = df.loc[:, ~df.columns.duplicated()].copy()
    selected_columns = [
        c for c in selected_columns
        if c in detail_df.columns
    ]

    st.dataframe(
        detail_df[selected_columns],
        use_container_width=True,
        height=520,
    )

    cleaned_csv = df.to_csv(
        index=False,
    ).encode("utf-8-sig")

    st.download_button(
        "Download cleaned analysis data",
        data=cleaned_csv,
        file_name="AFP_OK_NG_cleaned_analysis.csv",
        mime="text/csv",
    )


# ============================================================
# TAB 8 - REPORT EXPORT
# ============================================================
with tabs[7]:
    st.subheader("Analysis Report Export")

    report_screening_variables = (
        process_variables
        + main_afp_variables
        + afp_uniformity_variables
        + metal_coating_variables
        + mechanical_variables
    )

    report_screening = build_summary(
        df,
        report_screening_variables,
        quality_col,
    )

    if not order_df.empty and order_numeric_variables:
        report_order_summary = build_summary(
            order_df,
            order_numeric_variables,
            quality_col,
        )
    else:
        report_order_summary = pd.DataFrame()

    report_mechanical_summary = (
        build_summary(
            df,
            mechanical_variables,
            quality_col,
        )
        if mechanical_variables
        else pd.DataFrame()
    )

    st.markdown("#### Key Findings")
    st.write(_key_result_sentence(report_screening))
    st.warning(
        order_level_limitation_text(
            df,
            order_col,
            quality_col,
        )
    )

    if not report_screening.empty:
        st.markdown("#### OK vs NG Direction and Separation (Signed SMD)")

        report_signed_smd_fig = make_signed_smd_chart(
            report_screening,
            top_n=15,
        )

        if report_signed_smd_fig is not None:
            st.pyplot(
                report_signed_smd_fig,
                use_container_width=True,
            )

        st.caption(
            "Positive SMD means NG > OK; negative SMD means NG < OK. "
            "The absolute magnitude shows standardized separation strength."
        )

        st.markdown("#### OK vs NG Screening Priority")

        smd_preview_fig = make_smd_ranking_chart(
            report_screening,
            top_n=15,
        )

        if smd_preview_fig is not None:
            st.pyplot(
                smd_preview_fig,
                use_container_width=True,
            )

        st.caption(
            "The ranking uses |SMD| to show the strength of OK-NG separation. "
            "It does not prove root cause and does not show direction."
        )


        st.markdown("#### Top Factor Boxplots - OK vs NG Distribution")

        top_box_vars = (
            report_screening["Source Variable"]
            .dropna()
            .head(6)
            .tolist()
        )

        for variable in top_box_vars:
            if variable not in df.columns:
                continue

            fig = make_boxplot(
                df,
                variable,
                quality_col,
            )
            st.pyplot(
                fig,
                use_container_width=True,
            )

        st.caption(
            "Boxplots show the actual distribution and overlap between OK and NG."
        )

        report_preview = _prepare_report_screening(
            report_screening,
            top_n=10,
        )

        preview_cols = [
            "Parameter",
            "Factor Role",
            "OK Mean",
            "NG Mean",
            "NG - OK",
            "|SMD|",
            "Mann-Whitney p",
            "Screening Result",
        ]
        preview_cols = [
            c for c in preview_cols
            if c in report_preview.columns
        ]

        st.dataframe(
            report_preview[preview_cols],
            use_container_width=True,
            hide_index=True,
        )

    html_report = generate_html_report(
        df=df,
        order_df=order_df,
        screening_df=report_screening,
        order_summary_df=report_order_summary,
        mechanical_summary_df=report_mechanical_summary,
        quality_col=quality_col,
        coil_col=coil_col,
        order_col=order_col,
        date_col=date_col,
    )

    word_report = generate_word_report(
        df=df,
        screening_df=report_screening,
        order_summary_df=report_order_summary,
        mechanical_summary_df=report_mechanical_summary,
        quality_col=quality_col,
        coil_col=coil_col,
        order_col=order_col,
        date_col=date_col,
    )

    col_html, col_word = st.columns(2)

    with col_html:
        st.download_button(
            "Download HTML Report",
            data=html_report.encode("utf-8"),
            file_name="AFP_OK_NG_Analysis_Report.html",
            mime="text/html",
            use_container_width=True,
        )

    with col_word:
        st.download_button(
            "Download Word Report",
            data=word_report,
            file_name="AFP_OK_NG_Analysis_Report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

    st.caption(
        "Both reports use the current dashboard filters. Time-trend charts are intentionally excluded."
    )


# ============================================================
