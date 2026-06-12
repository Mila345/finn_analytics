"""
FINN - Final Invoice & Churn Operational Dashboard
===================================================
Streamlit app to monitor the FI damage ↔ churn/CSAT issue day-to-day and
track whether the Operations initiatives (Return-Ready, small-invoice waiver,
€2k+ playbook) are working.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py

Deploy: push app.py + requirements.txt (+ the two CSVs, or use the upload
widgets) to a GitHub repo and deploy on share.streamlit.io.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ----------------------------------------------------------------------------- config
st.set_page_config(page_title="FINN · FI & Churn Monitor", layout="wide")

st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] {
    background-color: #1E2761;
    border-radius: 6px 6px 0 0;
    padding: 6px 20px;
}
.stTabs [data-baseweb="tab"] p { color: #FFFFFF; font-weight: 600; }
.stTabs [aria-selected="true"] { background-color: #028090; }
.stTabs [data-baseweb="tab-highlight"] { background-color: transparent; }
.stTabs [data-baseweb="tab-border"] { background-color: #1E2761; }
</style>
""", unsafe_allow_html=True)

NAVY, TEAL, CORAL, GREY, GREEN = "#1E2761", "#028090", "#F96167", "#8A8F98", "#2C8C5A"
BANDS = [-np.inf, 0, 250, 500, 1000, 2000, np.inf]
BAND_LABELS = ["€0", "€0–250", "€250–500", "€500–1k", "€1k–2k", "€2k+"]
TYPE_FLAGS = {
    "Scratch": "has_paid_scratch", "Dent": "has_paid_dent", "Stone chip": "has_paid_stonechip",
    "Cleaning": "has_paid_cleaning", "Defect": "has_paid_defect", "Missing part": "has_paid_missing_part",
}
# Alert thresholds - tune with Ops leadership
# anchored at historical baselines (churn 53.9%, detractor 50.1%, small-FI 7.9%, €2k+ ~5%)
THRESHOLDS = {"pct_small_fi": 0.08, "detractor": 0.50, "churn": 0.54, "pct_2k": 0.08}

# ----------------------------------------------------------------------------- data
@st.cache_data(show_spinner="Loading data …")
def load_data(fi_file, dmg_file):
    fi = pd.read_csv(fi_file)
    dmg = pd.read_csv(dmg_file)
    fi["return_date"] = pd.to_datetime(fi["return_date"])
    fi["subscription_start_date"] = pd.to_datetime(fi["subscription_start_date"])
    fi["return_month"] = fi["return_date"].dt.to_period("M").dt.to_timestamp()
    fi["duration_m"] = (fi["return_date"] - fi["subscription_start_date"]).dt.days / 30.44
    fi["any_dmg"] = (fi["total_damage_amount"] > 0).astype(int)
    fi["dmg_band"] = pd.cut(fi["total_damage_amount"], BANDS, labels=BAND_LABELS)
    fi["responded"] = (fi["csat_score"] > 0).astype(int)
    fi["detractor"] = np.where(fi["responded"] == 1,
                               (fi["csat_classification"] == "Detractor").astype(float), np.nan)
    fi["small_fi"] = ((fi["total_damage_amount"] > 0) & (fi["total_damage_amount"] <= 150)).astype(int)
    fi["big_fi"] = (fi["total_damage_amount"] > 2000).astype(int)
    return fi, dmg


def kpi(col, label, value, delta=None, help_=None, invert=False):
    col.metric(label, value, delta=delta, delta_color="inverse" if invert else "normal", help=help_)


def alert_badge(col, cond):
    col.markdown(":red[above threshold]" if cond else ":green[within target]")


# ----------------------------------------------------------------------------- sidebar
st.sidebar.title("FI & Churn Monitor")
st.sidebar.caption("Operations · Final Invoice quality")

with st.sidebar.expander("Data source", expanded=False):
    up_fi = st.file_uploader("final_invoice_churn_data.csv", type="csv", key="fi")
    up_dmg = st.file_uploader("damage_items_detail.csv", type="csv", key="dmg")

try:
    fi, dmg = load_data(up_fi or "final_invoice_churn_data.csv", up_dmg or "damage_items_detail.csv")
except FileNotFoundError:
    st.info("Upload the two CSVs in the sidebar (or place them next to app.py) to start.")
    st.stop()

min_d, max_d = fi["return_month"].min(), fi["return_month"].max()
d_from, d_to = st.sidebar.slider(
    "Return month", min_value=min_d.to_pydatetime(), max_value=max_d.to_pydatetime(),
    value=(max(min_d, max_d - pd.DateOffset(months=23)).to_pydatetime(), max_d.to_pydatetime()),
    format="MMM YYYY",
)
band_sel = st.sidebar.multiselect("Damage band", BAND_LABELS, default=BAND_LABELS)
type_sel = st.sidebar.multiselect("Damage type on FI", list(TYPE_FLAGS), default=[])
churn_sel = st.sidebar.radio("Customer outcome", ["All", "Churned", "Renewed"], horizontal=True)

mask = fi["return_month"].between(d_from, d_to) & fi["dmg_band"].isin(band_sel)
if type_sel:
    mask &= np.logical_or.reduce([fi[TYPE_FLAGS[t]] == 1 for t in type_sel])
if churn_sel != "All":
    mask &= fi["churned"] == (1 if churn_sel == "Churned" else 0)
f = fi[mask]
d = dmg[dmg["subscription_id"].isin(f["subscription_id"])]
st.sidebar.markdown(f"**{len(f):,}** FIs in selection")

# ----------------------------------------------------------------------------- header
st.title("Final Invoice & Churn - Operations Monitor")
st.caption(f"Returns {d_from:%b %Y} – {d_to:%b %Y}")

tab_ov, tab_drv, tab_cust, tab_init = st.tabs(
    ["Overview", "Damage drivers", "Customer impact", "Monitoring"]
)

# ============================================================================= OVERVIEW
with tab_ov:
    resp = f[f["responded"] == 1]
    c = st.columns(6)
    kpi(c[0], "Final invoices", f"{len(f):,}")
    kpi(c[1], "% FIs with damage", f"{f['any_dmg'].mean():.1%}", help_="Share of FIs with damage > €0")
    kpi(c[2], "Avg damage € / FI", f"€{f['total_damage_amount'].mean():,.0f}")
    kpi(c[3], "Churn rate", f"{f['churned'].mean():.1%}",
        help_="Same-subscription churn - the renewal decision precedes the FI.")
    kpi(c[4], "Detractor share", f"{resp['detractor'].mean():.1%}" if len(resp) else "–",
        help_=f"Among {len(resp):,} survey respondents")
    kpi(c[5], "Complaint rate", f"{f['filed_complaint'].mean():.1%}")

    st.divider()
    m = (f.groupby("return_month")
           .agg(fis=("churned", "size"), churn=("churned", "mean"), any_dmg=("any_dmg", "mean"),
                avg_dmg=("total_damage_amount", "mean"), small=("small_fi", "mean"),
                big=("big_fi", "mean"), complaint=("filed_complaint", "mean"),
                detractor=("detractor", "mean"))
           .reset_index())

    l, r = st.columns(2)
    with l:
        fig = go.Figure()
        fig.add_bar(x=m.return_month, y=m.fis, name="FIs", marker_color=GREY, opacity=0.45, yaxis="y2")
        fig.add_scatter(x=m.return_month, y=m.churn, name="Churn", line=dict(color=NAVY, width=3))
        fig.add_scatter(x=m.return_month, y=m.detractor, name="Detractor", line=dict(color=CORAL, width=3))
        fig.update_layout(title="Churn & detractor share by return month", yaxis=dict(tickformat=".0%"),
                          yaxis2=dict(overlaying="y", side="right", showgrid=False, title="FIs"),
                          height=360, legend=dict(orientation="h"), margin=dict(t=50, b=10))
        st.plotly_chart(fig, width='stretch')
    with r:
        fig = go.Figure()
        fig.add_scatter(x=m.return_month, y=m.any_dmg, name="% FIs with damage", line=dict(color=TEAL, width=3))
        fig.add_scatter(x=m.return_month, y=m.avg_dmg, name="Avg damage € / FI",
                        yaxis="y2", line=dict(color=NAVY, width=2, dash="dot"))
        fig.update_layout(title="Damage exposure trend",
                          yaxis=dict(tickformat=".0%", title="% FIs with damage"),
                          yaxis2=dict(overlaying="y", side="right", showgrid=False,
                                      title="avg damage € / FI", tickprefix="€", tickformat=",.0f"),
                          height=360, legend=dict(orientation="h"), margin=dict(t=50, b=10))
        st.plotly_chart(fig, width='stretch')

    st.divider()
    ql, yr = st.columns(2)
    qd = (f.assign(quarter=f.return_date.dt.to_period("Q").astype(str))
            .groupby("quarter")
            .agg(fis=("churned", "size"), churn=("churned", "mean"), detractor=("detractor", "mean"))
            .reset_index())
    with ql:
        fig = go.Figure()
        fig.add_bar(x=qd.quarter, y=qd.fis, name="FIs", marker_color=GREY, opacity=0.45, yaxis="y2")
        fig.add_scatter(x=qd.quarter, y=qd.churn, name="Churn", line=dict(color=NAVY, width=3))
        fig.add_scatter(x=qd.quarter, y=qd.detractor, name="Detractor", line=dict(color=CORAL, width=3))
        fig.update_layout(title="Churn & detractor share by return quarter",
                          yaxis=dict(tickformat=".0%"),
                          yaxis2=dict(overlaying="y", side="right", showgrid=False, title="FIs"),
                          height=320, legend=dict(orientation="h"), margin=dict(t=50, b=10))
        st.plotly_chart(fig, width='stretch')
    yd = (f.assign(year=f.return_date.dt.year.astype(str))
            .groupby("year")
            .agg(fis=("churned", "size"), churn=("churned", "mean"), detractor=("detractor", "mean"))
            .reset_index())
    with yr:
        fig = go.Figure()
        fig.add_bar(x=yd.year, y=yd.fis, name="FIs", marker_color=GREY, opacity=0.45, yaxis="y2")
        fig.add_scatter(x=yd.year, y=yd.churn, name="Churn", line=dict(color=NAVY, width=3),
                        mode="lines+markers+text", text=[f"{v:.0%}" for v in yd.churn],
                        textposition="top center")
        fig.add_scatter(x=yd.year, y=yd.detractor, name="Detractor", line=dict(color=CORAL, width=3),
                        mode="lines+markers+text", text=[f"{v:.0%}" for v in yd.detractor],
                        textposition="bottom center")
        fig.update_layout(title="Churn & detractor share by return year",
                          yaxis=dict(tickformat=".0%"),
                          yaxis2=dict(overlaying="y", side="right", showgrid=False, title="FIs"),
                          height=320, legend=dict(orientation="h"), margin=dict(t=50, b=10))
        st.plotly_chart(fig, width='stretch')

# ============================================================================= DRIVERS
with tab_drv:
    l, r = st.columns([3, 2])
    rows = []
    for name, flag in TYPE_FLAGS.items():
        sub = f[f[flag] == 1]
        amt_col = flag.replace("has_paid_", "") + "_amount"
        rows.append({
            "Damage type": name, "FIs charged": len(sub),
            "€ billed": f[amt_col].sum() if amt_col in f.columns else np.nan,
            "Churn": sub["churned"].mean() if len(sub) else np.nan,
            "Complaint rate": sub["filed_complaint"].mean() if len(sub) else np.nan,
            "Detractor": sub.loc[sub.responded == 1, "detractor"].mean() if len(sub) else np.nan,
        })
    tt = pd.DataFrame(rows)
    with l:
        fig = px.bar(tt.sort_values("FIs charged"), x="FIs charged", y="Damage type", orientation="h",
                     color="Detractor", color_continuous_scale=["#CADCFC", CORAL],
                     title="FIs charged by type - color = detractor share")
        fig.update_layout(height=380, margin=dict(t=50, b=10))
        st.plotly_chart(fig, width='stretch')
    with r:
        st.dataframe(tt.style.format({"€ billed": "€{:,.0f}", "Churn": "{:.1%}",
                                      "Complaint rate": "{:.1%}", "Detractor": "{:.1%}"}),
                     width='stretch', height=380, hide_index=True)

    st.divider()
    l2, r2 = st.columns(2)
    with l2:
        billed = d[d["invoiced_amount"] > 0]
        share_small_items = (billed["invoiced_amount"] <= 100).mean() if len(billed) else 0
        st.metric("Appraised items waived (€0)", f"{(d['invoiced_amount'] == 0).mean():.1%}",
                  help="Share of appraisal line items invoiced at €0")
        st.metric("Billed items ≤ €100", f"{share_small_items:.1%}",
                  help="FIs billed €0-150 in the current filter")
        st.metric("FIs ≤ €150 total (waiver candidates)", f"{f['small_fi'].sum():,}",
                  f"€{f.loc[f.small_fi == 1, 'total_damage_amount'].sum():,.0f} billed")
    with r2:
        hist = px.histogram(f[f.total_damage_amount > 0], x="total_damage_amount", nbins=60,
                            title="FI damage amount distribution", color_discrete_sequence=[NAVY])
        hist.add_vline(x=150, line_dash="dash", line_color=GREEN, annotation_text="small-invoice waiver line €150")
        hist.add_vline(x=2000, line_dash="dash", line_color=CORAL, annotation_text="large-invoice line €2k")
        hist.update_layout(height=330, margin=dict(t=50, b=10), xaxis_range=[0, 5000])
        st.plotly_chart(hist, width='stretch')

    st.divider()
    chg = f[f.total_damage_amount > 0]
    cl, cr = st.columns(2)
    cm = (chg.groupby("return_month")["total_damage_amount"].mean().reset_index())
    with cl:
        fig = go.Figure()
        fig.add_scatter(x=cm.return_month, y=cm.total_damage_amount, name="Avg € per charged FI",
                        line=dict(color=TEAL, width=3))
        fig.update_layout(title="Avg damage € per charged FI by month (FIs > €0 only)",
                          yaxis=dict(tickprefix="€", tickformat=",.0f"),
                          height=320, margin=dict(t=50, b=10))
        st.plotly_chart(fig, width='stretch')
    cy = (chg.assign(year=chg.return_date.dt.year.astype(str))
             .groupby("year")["total_damage_amount"].mean().reset_index())
    with cr:
        fig = go.Figure()
        fig.add_bar(x=cy.year, y=cy.total_damage_amount, marker_color=NAVY,
                    text=[f"€{v:,.0f}" for v in cy.total_damage_amount], textposition="outside")
        fig.update_layout(title="Avg damage € per charged FI by year (FIs > €0 only)",
                          yaxis=dict(tickprefix="€", tickformat=",.0f"),
                          height=320, margin=dict(t=50, b=10))
        st.plotly_chart(fig, width='stretch')
    st.caption("Read together with '% FIs with damage' (Overview): exposure = how many customers get "
               "charged × how much when charged. This pair isolates the second lever.")

# ============================================================================= CUSTOMER IMPACT
with tab_cust:
    g = (f.groupby("dmg_band", observed=True)
           .agg(n=("churned", "size"), churn=("churned", "mean"),
                complaint=("filed_complaint", "mean"), detractor=("detractor", "mean"))
           .reindex(BAND_LABELS))
    l, r = st.columns(2)
    with l:
        fig = px.bar(g.reset_index(), x="dmg_band", y="churn", text_auto=".1%",
                     title="Churn by FI damage band - jumps at any charge, then flat",
                     color_discrete_sequence=[NAVY])
        fig.update_layout(height=340, yaxis_tickformat=".0%", margin=dict(t=50, b=10))
        st.plotly_chart(fig, width='stretch')
    with r:
        fig = go.Figure()
        fig.add_scatter(x=g.index, y=g.detractor, name="Detractor", line=dict(color=CORAL, width=3))
        fig.add_scatter(x=g.index, y=g.complaint, name="Complaint rate", line=dict(color=NAVY, width=3))
        fig.update_layout(title="Detractor & complaint rate by FI damage band", height=340,
                          yaxis_tickformat=".0%", legend=dict(orientation="h"), margin=dict(t=50, b=10))
        st.plotly_chart(fig, width='stretch')

    st.divider()
    st.subheader("Repeat-customer panel: does the FI affect the *next* renewal?")
    fu = fi[fi.follow_up_subscription_id.notna()].copy()
    fu["follow_up_subscription_id"] = fu["follow_up_subscription_id"].astype("int64")
    nxt = fi[["subscription_id", "churned"]].rename(
        columns={"subscription_id": "follow_up_subscription_id", "churned": "next_churned"})
    panel = fu.merge(nxt, on="follow_up_subscription_id", how="inner")
    panel["prior_band"] = pd.cut(panel["total_damage_amount"], BANDS, labels=BAND_LABELS)
    p = panel.groupby("prior_band", observed=True)["next_churned"].agg(["size", "mean"]).reindex(BAND_LABELS)
    base = p["mean"].iloc[0]
    fig = px.bar(p.reset_index(), x="prior_band", y="mean", text_auto=".1%",
                 title=f"Next-subscription churn by PRIOR FI band (panel n={len(panel):,}) - only €2k+ carries over",
                 color=p["mean"] > base + 0.05, color_discrete_map={True: CORAL, False: GREY})
    fig.add_hline(y=base, line_dash="dash", annotation_text=f"baseline {base:.1%}")
    fig.update_layout(height=340, yaxis_tickformat=".0%", showlegend=False, margin=dict(t=50, b=10))
    st.plotly_chart(fig, width='stretch')

# ============================================================================= INITIATIVES
with tab_init:
    st.markdown("**North-star metrics**, each compared to the equivalent previous period.")

    def window_stats(days):
        """Current window [max-days, max] vs the previous window of equal length."""
        end = fi.return_date.max()
        cur = fi[fi.return_date > end - pd.Timedelta(days=days)]
        prv = fi[(fi.return_date <= end - pd.Timedelta(days=days))
                 & (fi.return_date > end - pd.Timedelta(days=2 * days))]
        def stats(d):
            r = d[d.responded == 1]
            return {
                "csat": r.csat_score.mean() if len(r) else np.nan,
                "respondents": int(d.responded.sum()),
                "detractors": d.detractor.sum(),
                "churned_cust": int(d.loc[d.churned == 1, "customer_id"].nunique()),
                "big": int(d.big_fi.sum()),
                "billed": d.total_damage_amount.sum(),
                "fis": len(d),
            }
        return stats(cur), stats(prv)

    def render_window(days, label):
        cur, prv = window_stats(days)
        c = st.columns(5)
        c[0].metric(f"Avg CSAT ({label})",
                    f"{cur['csat']:.2f} / 5" if pd.notna(cur["csat"]) else "no responses",
                    delta=(f"{cur['csat'] - prv['csat']:+.2f} vs prior {label}"
                           if pd.notna(cur["csat"]) and pd.notna(prv["csat"]) else None))
        c[0].caption(f"{cur['respondents']:,} respondents of {cur['fis']:,} FIs")
        c[1].metric("Detractors created", f"{cur['detractors']:,.0f}",
                    delta=f"{cur['detractors'] - prv['detractors']:+,.0f} vs prior {label}",
                    delta_color="inverse")
        c[2].metric("Customers churned", f"{cur['churned_cust']:,}",
                    delta=f"{cur['churned_cust'] - prv['churned_cust']:+,} vs prior {label}",
                    delta_color="inverse")
        c[2].caption("Distinct customers whose subscription ended without a follow-up.")
        c[3].metric("FIs over €2k", f"{cur['big']:,}",
                    delta=f"{cur['big'] - prv['big']:+,} vs prior {label}",
                    delta_color="inverse")
        c[4].metric("Damage € billed", f"€{cur['billed']:,.0f}",
                    delta=f"€{cur['billed'] - prv['billed']:+,.0f} vs prior {label}",
                    delta_color="inverse")
        if days == 1:
            st.caption("Note: daily counts are small, so single-day swings are mostly noise "
                       "and can be used for monitoring data anomalies.")

    t_day, t_week, t_month = st.tabs(["Daily", "Weekly", "Monthly"])
    with t_day:
        render_window(1, "last 24 hours")
    with t_week:
        render_window(7, "last 7 days")
    with t_month:
        render_window(30, "last 30 days")

    st.divider()
    st.subheader("Threshold status (last full month)")
    st.caption("Red = worse than the historical baseline.")
    lastm = fi[fi.return_month == fi.return_month.max()]
    a = st.columns(4)
    a[0].metric("Small FIs ≤€150 share", f"{lastm.small_fi.mean():.1%}")
    alert_badge(a[0], lastm.small_fi.mean() > THRESHOLDS["pct_small_fi"])
    a[1].metric("€2k+ FI share", f"{lastm.big_fi.mean():.1%}")
    alert_badge(a[1], lastm.big_fi.mean() > THRESHOLDS["pct_2k"])
    a[2].metric("Detractor share", f"{(lastm.detractor.mean() or 0):.1%}")
    alert_badge(a[2], (lastm.detractor.mean() or 0) > THRESHOLDS["detractor"])
    a[3].metric("Churn rate", f"{lastm.churned.mean():.1%}")
    alert_badge(a[3], lastm.churned.mean() > THRESHOLDS["churn"])


st.caption("Data: final_invoice_churn_data.csv + damage_items_detail.csv · Methodology: see analysis notebook.")
