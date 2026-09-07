
import re
import io
import base64
import html as html_lib
import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

try:
    from scipy.stats import mannwhitneyu
    SCIPY_AVAILABLE = True
except Exception:
    SCIPY_AVAILABLE = False

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score
    SKLEARN_AVAILABLE = True
except Exception:
    SKLEARN_AVAILABLE = False


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
    "peeling and white powder after customer deep-drawing / forming."
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

    "AFP_TOP_MEAN": "AFP Top Film Thickness - 3 Point Mean",
    "AFP_BOTTOM_MEAN": "AFP Bottom Film Thickness - 3 Point Mean",
    "AFP_OVERALL_MEAN": "AFP Overall Film Thickness - 6 Point Mean",
    "AFP_RECHECK_MEAN": "AFP Recheck Thickness Mean",

    "AFP_TOP_RANGE": "AFP Top Thickness Range",
    "AFP_BOTTOM_RANGE": "AFP Bottom Thickness Range",
    "AFP_OVERALL_RANGE": "AFP Overall Thickness Range",
    "AFP_OVERALL_CV": "AFP Thickness CV (%)",

    "XRAY_TOP_MEAN": "Metal Coating Thickness - Top Mean",
    "XRAY_BOTTOM_MEAN": "Metal Coating Thickness - Bottom Mean",
    "XRAY_TOTAL": "Metal Coating Thickness - Total",
    "XRAY_SIDE_DIFFERENCE": "Top-Bottom Metal Coating Difference",

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

        # Numeric interval
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



# ============================================================
# HTML REPORT HELPERS
# ============================================================
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
    """
    Generate a self-contained management report.
    """
    report_title = "AFP Coating OK vs NG Root Cause Screening Report"

    n_rows = len(df)
    n_coils = df[coil_col].nunique() if coil_col in df.columns else n_rows
    n_orders = df[order_col].nunique() if order_col in df.columns else np.nan
    n_ok = int((df[quality_col] == "OK").sum())
    n_ng = int((df[quality_col] == "NG").sum())
    ng_rate = n_ng / max(n_ok + n_ng, 1) * 100

    if date_col in df.columns and df[date_col].notna().any():
        date_text = (
            f"{df[date_col].min().strftime('%Y-%m-%d')} to "
            f"{df[date_col].max().strftime('%Y-%m-%d')}"
        )
    else:
        date_text = "Not available"

    conclusion_lines = build_executive_conclusion(screening_df)

    # Top screening table
    if screening_df is not None and not screening_df.empty:
        top_screening = screening_df.copy()
        top_screening["Screening Result"] = top_screening.apply(
            classify_screening_result,
            axis=1,
        )
        top_screening = top_screening.head(12)
    else:
        top_screening = pd.DataFrame()

    # Create up to 4 boxplots
    chart_html = ""
    if screening_df is not None and not screening_df.empty:
        top_vars = (
            screening_df["Source Variable"]
            .dropna()
            .head(4)
            .tolist()
        )

        chart_blocks = []
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
                        <img src="data:image/png;base64,{encoded}" alt="{html_lib.escape(DISPLAY.get(variable, variable))}">
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

    conclusion_html = "".join(
        f"<li>{html_lib.escape(line)}</li>"
        for line in conclusion_lines
    )

    # Mechanical-property interpretation
    mechanical_table = dataframe_to_html(
        mechanical_summary_df,
        columns=[
            "Parameter",
            "OK n",
            "OK Mean",
            "NG n",
            "NG Mean",
            "NG - OK",
            "SMD",
            "|SMD|",
            "Mann-Whitney p",
        ],
    )

    mechanical_lines = []

    if mechanical_summary_df is None or mechanical_summary_df.empty:
        mechanical_lines.append(
            "No usable mechanical-property data were available for OK-versus-NG comparison."
        )
    else:
        mech = mechanical_summary_df.copy()

        def _find_row(keyword):
            mask = mech["Parameter"].astype(str).str.contains(keyword, case=False, regex=False)
            return mech[mask].iloc[0] if mask.any() else None

        ys_row = _find_row("Yield Strength")
        ts_row = _find_row("Tensile Strength")
        el_row = _find_row("Elongation")
        hard_row = _find_row("Steel Hardness Mean")

        if ys_row is not None and pd.notna(ys_row["NG - OK"]):
            direction = "higher" if ys_row["NG - OK"] > 0 else "lower"
            mechanical_lines.append(
                f"NG Yield Strength is {direction} than OK by approximately "
                f"{abs(ys_row['NG - OK']):.3f} in the source unit."
            )

        if ts_row is not None and pd.notna(ts_row["NG - OK"]):
            direction = "higher" if ts_row["NG - OK"] > 0 else "lower"
            mechanical_lines.append(
                f"NG Tensile Strength is {direction} than OK by approximately "
                f"{abs(ts_row['NG - OK']):.3f} in the source unit."
            )

        if el_row is not None and pd.notna(el_row["NG - OK"]):
            direction = "higher" if el_row["NG - OK"] > 0 else "lower"
            mechanical_lines.append(
                f"NG Elongation is {direction} than OK by approximately "
                f"{abs(el_row['NG - OK']):.3f} in the source unit."
            )

        if hard_row is not None and pd.notna(hard_row["NG - OK"]):
            direction = "higher" if hard_row["NG - OK"] > 0 else "lower"
            mechanical_lines.append(
                f"NG steel hardness is {direction} than OK by approximately "
                f"{abs(hard_row['NG - OK']):.3f} in the source unit."
            )

        if not mechanical_lines:
            mechanical_lines.append(
                "Mechanical-property variables are present, but the available data do not support a clear directional interpretation."
            )

    mechanical_lines.append(
        "For deep drawing, mechanical properties are interpreted as substrate/formability factors. "
        "They can change the strain and forming load transferred to the AFP coating, but they do not directly measure AFP adhesion."
    )

    mechanical_lines.append(
        "r-value and n-value are not included unless corresponding source columns are available in the uploaded dataset."
    )

    mechanical_html = "".join(
        f"<li>{html_lib.escape(line)}</li>"
        for line in mechanical_lines
    )

    screening_table = dataframe_to_html(
        top_screening,
        columns=[
            "Parameter",
            "OK n",
            "OK Mean",
            "NG n",
            "NG Mean",
            "NG - OK",
            "SMD",
            "|SMD|",
            "Mann-Whitney p",
            "Screening Result",
        ],
    )

    order_table = dataframe_to_html(
        order_summary_df,
        columns=[
            "Parameter",
            "OK n",
            "OK Mean",
            "NG n",
            "NG Mean",
            "NG - OK",
            "SMD",
            "|SMD|",
            "Mann-Whitney p",
        ],
    )

    html_report = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{report_title}</title>
<style>
    body {{
        font-family: Arial, Helvetica, sans-serif;
        margin: 0;
        background: #f5f7fa;
        color: #1f2937;
    }}
    .page {{
        max-width: 1180px;
        margin: 24px auto;
        background: white;
        padding: 32px 38px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    }}
    h1 {{ margin-bottom: 5px; }}
    h2 {{
        border-bottom: 2px solid #d1d5db;
        padding-bottom: 7px;
        margin-top: 32px;
    }}
    .subtitle {{
        color: #6b7280;
        margin-bottom: 22px;
    }}
    .kpi-grid {{
        display: grid;
        grid-template-columns: repeat(5, minmax(120px, 1fr));
        gap: 12px;
        margin: 18px 0;
    }}
    .kpi {{
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 14px;
        background: #fafafa;
    }}
    .kpi-label {{
        font-size: 12px;
        color: #6b7280;
    }}
    .kpi-value {{
        font-size: 23px;
        font-weight: bold;
        margin-top: 4px;
    }}
    .conclusion {{
        border-left: 5px solid #374151;
        padding: 14px 20px;
        background: #f9fafb;
    }}
    .report-table {{
        border-collapse: collapse;
        width: 100%;
        font-size: 12px;
        margin: 12px 0 20px 0;
    }}
    .report-table th,
    .report-table td {{
        border: 1px solid #d1d5db;
        padding: 7px 8px;
        text-align: right;
    }}
    .report-table th:first-child,
    .report-table td:first-child {{
        text-align: left;
    }}
    .report-table th {{
        background: #f3f4f6;
    }}
    .chart-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
    }}
    .chart-card {{
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 8px;
    }}
    .chart-card img {{
        width: 100%;
        height: auto;
    }}
    .note {{
        font-size: 12px;
        color: #6b7280;
        line-height: 1.5;
    }}
    .action-box {{
        background: #f9fafb;
        padding: 16px 20px;
        border-radius: 8px;
    }}
    @media print {{
        body {{ background: white; }}
        .page {{ box-shadow: none; margin: 0; max-width: none; }}
    }}
</style>
</head>
<body>
<div class="page">

<h1>{report_title}</h1>
<div class="subtitle">
Problem: AFP coating peeling / white powder after customer deep drawing or forming.
</div>

<h2>1. Analysis Scope</h2>
<div class="kpi-grid">
    <div class="kpi">
        <div class="kpi-label">Production Period</div>
        <div class="kpi-value" style="font-size:16px;">{date_text}</div>
    </div>
    <div class="kpi">
        <div class="kpi-label">Unique Coils</div>
        <div class="kpi-value">{n_coils:,}</div>
    </div>
    <div class="kpi">
        <div class="kpi-label">Orders</div>
        <div class="kpi-value">{int(n_orders) if pd.notna(n_orders) else "N/A"}</div>
    </div>
    <div class="kpi">
        <div class="kpi-label">NG Records</div>
        <div class="kpi-value">{n_ng:,}</div>
    </div>
    <div class="kpi">
        <div class="kpi-label">NG Rate</div>
        <div class="kpi-value">{ng_rate:.1f}%</div>
    </div>
</div>

<h2>2. Executive Conclusion</h2>
<div class="conclusion">
<ul>
{conclusion_html}
</ul>
</div>

<h2>3. What This Analysis Achieved</h2>
<ul>
    <li>Quantified the differences between OK and NG coils instead of relying only on visual judgement.</li>
    <li>Ranked process, AFP film, metal coating and mechanical variables by OK-NG separation.</li>
    <li>Separated high-priority candidate factors from variables showing little difference.</li>
    <li>Kept representative surface-QC measurements at ORDER level to avoid pseudo-replication.</li>
    <li>Created a shortlist of factors that should be verified before establishing process control limits.</li>
</ul>

<h2>4. Candidate Factor Ranking</h2>
{screening_table}
<p class="note">
SMD = standardized mean difference. A larger absolute SMD indicates stronger OK-NG separation.
The Mann-Whitney p-value is used only as supporting statistical evidence.
Neither metric alone proves root cause.
</p>

<h2>5. Main OK vs NG Charts</h2>
{chart_html if chart_html else "<p>No chart available.</p>"}

<h2>6. Representative Surface QC</h2>
{order_table}
<p class="note">
Slip / COF, adhesion, wear resistance and roughness are analyzed once per ORDER_NUMBER when one representative coil is used for the entire order.
</p>

<h2>7. Mechanical Properties and Deep-Drawing Interpretation</h2>
{mechanical_table}
<div class="conclusion">
<ul>
{mechanical_html}
</ul>
</div>
<p class="note">
Mechanical properties are supporting factors for deep-drawing performance. 
A difference in YS, TS, EL or hardness may increase or reduce the forming demand placed on the AFP layer, 
but a mechanical-property difference alone does not prove that it caused AFP peeling.
</p>

<h2>8. Root-Cause Logic</h2>
<div class="action-box">
<strong>Process / Material Factors</strong>
&rarr; AFP film thickness and uniformity
&rarr; surface / adhesion / wear behavior
&rarr; peeling or white powder after deep drawing.
<br><br>
<strong>Mechanical / Formability Factors</strong>
&rarr; substrate deformation behavior and forming load
&rarr; strain transferred to AFP coating
&rarr; risk of cracking / peeling during deep drawing.
</div>

<h2>9. Recommended Next Step</h2>
<ol>
    <li>Select the top 2-3 candidate factors from the screening table.</li>
    <li>Confirm that OK and NG samples are comparable by product specification, order condition and customer forming condition.</li>
    <li>Collect additional matched coils if the current sample size is small or unbalanced.</li>
    <li>Verify the suspected factors through a controlled process trial or DOE.</li>
    <li>Only after verification, establish production control limits and a reaction plan.</li>
</ol>

<p class="note">
This report is a screening and root-cause prioritization report. It must not be interpreted as proof of causality before verification.
</p>

</div>
</body>
</html>
"""
    return html_report


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
    COL["afp_recheck"],
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

all_afp_cols = top_afp_cols + bottom_afp_cols

if all_afp_cols:
    df["AFP_OVERALL_MEAN"] = numeric_mean(df, all_afp_cols)
    df["AFP_OVERALL_RANGE"] = numeric_range(df, all_afp_cols)

    afp_matrix = df[all_afp_cols].apply(pd.to_numeric, errors="coerce")
    afp_sd = afp_matrix.std(axis=1, ddof=1)
    afp_mean = afp_matrix.mean(axis=1)

    df["AFP_OVERALL_CV"] = np.where(
        afp_mean.abs() > 1e-12,
        afp_sd / afp_mean.abs() * 100,
        np.nan,
    )

if COL["afp_recheck"] in df.columns:
    df["AFP_RECHECK_MEAN"] = pd.to_numeric(
        df[COL["afp_recheck"]],
        errors="coerce",
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
        "AFP_OVERALL_MEAN",
        "AFP_RECHECK_MEAN",
    ],
)

afp_uniformity_variables = numeric_variables_available(
    df,
    [
        "AFP_TOP_RANGE",
        "AFP_BOTTOM_RANGE",
        "AFP_OVERALL_RANGE",
        "AFP_OVERALL_CV",
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
        "HTML Report",
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
                    "Metric": "AFP Overall Thickness Range",
                    "Definition": "Maximum minus minimum across all available AFP measurement points",
                },
                {
                    "Metric": "AFP Thickness CV (%)",
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
                    "OK n",
                    "OK Mean",
                    "NG n",
                    "NG Mean",
                    "NG - OK",
                    "SMD",
                    "|SMD|",
                    "Mann-Whitney p",
                    "Screening Priority",
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

    st.markdown("#### Exploratory multivariable model")

    model_variables = numeric_variables_available(
        df,
        screening_variables,
        min_count=3,
    )

    if (
        SKLEARN_AVAILABLE
        and len(model_variables) >= 2
        and len(df) >= 20
        and df[quality_col].nunique() == 2
    ):
        model_df = df[
            [quality_col] + model_variables
        ].copy()

        y = (
            model_df[quality_col] == "NG"
        ).astype(int)

        X = model_df[
            model_variables
        ].apply(
            pd.to_numeric,
            errors="coerce",
        )

        # Remove completely empty or constant predictors.
        usable = [
            c
            for c in X.columns
            if X[c].notna().sum() >= 3
            and X[c].nunique(dropna=True) > 1
        ]

        X = X[usable]

        if len(usable) >= 2:
            for c in X.columns:
                median = X[c].median()
                X[c] = X[c].fillna(median)

            model = RandomForestClassifier(
                n_estimators=500,
                random_state=42,
                class_weight="balanced",
                min_samples_leaf=max(
                    2,
                    int(len(X) * 0.02),
                ),
            )

            model.fit(X, y)

            probability = model.predict_proba(X)[:, 1]

            try:
                auc = roc_auc_score(
                    y,
                    probability,
                )
            except Exception:
                auc = np.nan

            importance = pd.DataFrame(
                {
                    "Parameter": [
                        DISPLAY.get(c, c)
                        for c in X.columns
                    ],
                    "Random Forest Importance":
                        model.feature_importances_,
                }
            ).sort_values(
                "Random Forest Importance",
                ascending=False,
            )

            if pd.notna(auc):
                st.metric(
                    "In-sample Random Forest AUC",
                    f"{auc:.3f}",
                )

            st.dataframe(
                importance.head(15),
                hide_index=True,
                use_container_width=True,
            )

            st.caption(
                "Random Forest importance is exploratory only. "
                "It can rank variables associated with NG but cannot "
                "establish causation."
            )
    else:
        st.caption(
            "The multivariable model requires scikit-learn, "
            "at least two usable predictors and sufficient OK/NG rows."
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
        "Peeling or White Powder after Deep Drawing",
        language="text",
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
        "AFP_OVERALL_MEAN",
        "AFP_RECHECK_MEAN",
        "XRAY_TOTAL",
        "HARDNESS_MEAN",
        "YS",
        "TS",
        "EL",
    ]

    default_columns = [
        c
        for c in default_columns
        if c in df.columns
    ]

    selected_columns = st.multiselect(
        "Columns to display",
        options=list(df.columns),
        default=default_columns,
    )

    if not selected_columns:
        selected_columns = default_columns

    st.dataframe(
        df[selected_columns],
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
# TAB 8 - HTML REPORT
# ============================================================
with tabs[7]:
    st.subheader("Management Summary and HTML Report")

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

    report_mechanical_summary = build_summary(
        df,
        mechanical_variables,
        quality_col,
    ) if mechanical_variables else pd.DataFrame()

    conclusion_lines = build_executive_conclusion(
        report_screening
    )

    st.markdown("#### Executive Conclusion")

    for line in conclusion_lines:
        st.write(f"- {line}")

    st.markdown("#### Mechanical Properties and Deep-Drawing Interpretation")

    if report_mechanical_summary.empty:
        st.info("No usable mechanical-property data are available for OK vs NG comparison.")
    else:
        st.dataframe(
            report_mechanical_summary.drop(
                columns=["Source Variable"],
                errors="ignore",
            ),
            use_container_width=True,
        )
        st.caption(
            "YS, TS, EL and steel hardness are interpreted as substrate/formability factors. "
            "They can affect the strain transferred to the AFP layer during deep drawing, "
            "but they do not directly measure AFP adhesion."
        )

    st.markdown("#### What the analysis delivers")

    st.write(
        "1. Quantifies the OK-versus-NG differences.\n"
        "2. Ranks candidate factors by the size of their separation.\n"
        "3. Separately evaluates YS, TS, EL and steel hardness for deep-drawing relevance.\n"
        "4. Identifies low-priority variables that currently show little difference.\n"
        "5. Provides a shortlist for process verification / DOE.\n"
        "6. Prevents representative order-level QC values from being over-counted."
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

    st.download_button(
        "Download HTML Root Cause Report",
        data=html_report.encode("utf-8"),
        file_name="AFP_OK_NG_Root_Cause_Report.html",
        mime="text/html",
    )

    st.caption(
        "The HTML file is self-contained and can be opened directly in a browser or sent to management."
    )


# ============================================================
# DATA DICTIONARY
# ============================================================
with st.expander("Data Dictionary", expanded=False):
    dictionary = pd.DataFrame(
        [
            ["COIL_NO", "Raw", "Steel coil number"],
            ["PRODUCTION_DATE", "Raw", "Production date"],
            ["Quality class", "Raw", "OK / NG classification"],
            ["ORDER_NUMBER", "Raw", "Customer / production order number"],
            ["OVEN_TEMPERATURE", "Raw", "Drying oven temperature"],
            ["ROLL_TEMPERATURE", "Raw", "Temperature of the coating / treatment roll"],
            ["AFP Top Film Thickness - 3 Point Mean", "Derived", "Average of North, Center and South AFP thickness on the top side"],
            ["AFP Bottom Film Thickness - 3 Point Mean", "Derived", "Average of North, Center and South AFP thickness on the bottom side"],
            ["AFP Overall Film Thickness - 6 Point Mean", "Derived", "Average of all available AFP thickness points on both sides"],
            ["AFP Recheck Thickness Mean", "Derived", "Mean of the values stored in AFP thickness recheck field, e.g. 1.07/1.20"],
            ["Metal Coating Thickness - Top Mean", "Derived", "Mean of XRAY top North, Center and South"],
            ["Metal Coating Thickness - Bottom Mean", "Derived", "Mean of XRAY bottom North, Center and South"],
            ["Metal Coating Thickness - Total", "Derived", "Top mean plus bottom mean"],
            ["Steel Hardness Mean", "Derived", "Mean of North and South steel hardness"],
            ["Yield Strength", "Raw / renamed", "TENSILE_YIELD_RAW"],
            ["Tensile Strength", "Raw / renamed", "TENSILE_TENSILE_RAW"],
            ["Elongation", "Raw / renamed", "TENSILE_ELONG_RAW"],
            ["Slip / COF", "Order-level QC", "Representative slip / coefficient of friction result"],
            ["AFP Adhesion", "Order-level QC", "Representative AFP adhesion result"],
            ["AFP Wear Resistance", "Order-level QC", "Representative wear-resistance result"],
            ["Surface Roughness Ra", "Order-level QC", "Representative surface roughness result"],
        ],
        columns=[
            "Displayed Metric",
            "Type",
            "Definition",
        ],
    )

    st.dataframe(
        dictionary,
        hide_index=True,
        use_container_width=True,
    )
