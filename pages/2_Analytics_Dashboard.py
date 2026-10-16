import plotly.graph_objects as go
import streamlit as st

from src.analytics import (average_order_value, country_revenue, distinct_orders,
                           monthly_revenue, revenue_growth, top_products,
                           total_revenue, unique_customers)
from src.ui_helpers import require_upload

st.set_page_config(page_title="Analytics Dashboard", layout="wide")
st.title("Analytics Dashboard")

upload = require_upload()
kpis = upload["kpis"]
if kpis is None:
    st.error("No eligible rows, so there are no KPIs to show. "
             "Open the Data Quality page to see why every row was rejected or excluded.")
    st.stop()

BLUE = "#2a78d6"      # single series -> one accent colour; works on light and dark surfaces
GRID = "rgba(128,128,128,0.25)"

elig = upload["quality"].eligible.copy()
elig["Month"] = elig["InvoiceDateValue"].dt.to_period("M").astype(str)
elig["Country"] = elig["Country"].fillna("Unknown")

# ------------------------------------------------------------------ status
st.caption(f"File: {upload['name']}  |  Period: {kpis['period']}  |  "
           f"{kpis['exclusions']['eligible_rows']:,} eligible rows "
           f"({kpis['exclusions']['excluded_rows']:,} excluded)")

# ------------------------------------------------------------------ filters
all_months = sorted(elig["Month"].unique())
all_countries = sorted(elig["Country"].unique())

f1, f2 = st.columns([2, 3])
with f1:
    if len(all_months) > 1:
        month_range = st.select_slider("Months", options=all_months,
                                       value=(all_months[0], all_months[-1]), key="month_range")
    else:
        month_range = (all_months[0], all_months[0])
        st.write(f"Month: {all_months[0]}")
with f2:
    countries = st.multiselect("Countries", all_countries, default=all_countries, key="country_filter")

if not countries:
    st.warning("Select at least one country.")
    st.stop()

view = elig[(elig["Month"] >= month_range[0]) & (elig["Month"] <= month_range[1])
            & (elig["Country"].isin(countries))]
if view.empty:
    st.warning("No data for this selection.")
    st.stop()

is_full = (month_range == (all_months[0], all_months[-1])) and set(countries) == set(all_countries)
db = upload.get("db")
if is_full and db and db["rec"]["ok"]:
    st.success(f"Full dataset. These numbers are reconciled: Python and SQL agree (run #{db['run_id']}).")
elif is_full and db:
    st.warning(f"Python and SQL disagree for run #{db['run_id']}. Treat these numbers as unverified "
               "until the mismatch is reviewed.")
elif is_full:
    st.info("Full dataset, calculated in Python. Use **Save run to SQL Server** on the Home page "
            "to reconcile these numbers with SQL.")
else:
    st.info("Filtered view, calculated in Python. The SQL reconciliation covers the full dataset only.")

# ------------------------------------------------------------------ KPI cards
monthly = monthly_revenue(view)
growth = None
if len(monthly) >= 2:
    growth = revenue_growth(float(monthly["Revenue"].iloc[-1]), float(monthly["Revenue"].iloc[-2]))

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total revenue", f"{total_revenue(view):,.2f}")
k2.metric("Distinct orders", f"{distinct_orders(view):,}")
k3.metric("Average order value", f"{average_order_value(view):,.2f}")
k4.metric("Unique customers", f"{unique_customers(view):,}",
          help="Rows without a CustomerID are not counted, so this is a lower bound.")
k5.metric("Revenue growth (latest month)", "n/a" if growth is None else f"{growth:+.2f}%",
          help=("Needs at least two months in the selection." if growth is None else
                f"{monthly['Month'].iloc[-1]} vs {monthly['Month'].iloc[-2]}. "
                "A partial last month understates growth."))

with st.expander("How these numbers are calculated"):
    for m in kpis["metrics"]:
        st.markdown(f"**{m['name']}**: {m['definition']} {m['limitations']}")


# ------------------------------------------------------------------ charts
def style(fig, height):
    fig.update_layout(height=height, margin=dict(l=0, r=10, t=10, b=0), showlegend=False,
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


st.subheader("Monthly revenue")
labels = [""] * (len(monthly) - 1) + [f"{monthly['Revenue'].iloc[-1]:,.0f}"]   # label the latest point only
trend = go.Figure(go.Scatter(
    x=monthly["Month"], y=monthly["Revenue"], mode="lines+markers+text", text=labels,
    textposition="top center", line=dict(color=BLUE, width=2), marker=dict(color=BLUE, size=8),
    customdata=monthly["Orders"],
    hovertemplate="%{x}<br>Revenue: %{y:,.2f}<br>Orders: %{customdata:,}<extra></extra>"))
trend.update_xaxes(type="category")
trend.update_yaxes(rangemode="tozero", title_text="Revenue")
st.plotly_chart(style(trend, 340), use_container_width=True)


def hbar(df, label_col, title):
    d = df.sort_values("Revenue")
    fig = go.Figure(go.Bar(
        x=d["Revenue"], y=d[label_col], orientation="h", marker_color=BLUE,
        text=d["Revenue"], texttemplate="%{x:,.0f}", textposition="outside", cliponaxis=False,
        hovertemplate="%{y}<br>Revenue: %{x:,.2f}<extra></extra>"))
    fig.update_layout(bargap=0.45)
    fig.update_xaxes(rangemode="tozero", title_text="Revenue")
    return style(fig, max(260, 34 * len(d) + 80))


countries_df = country_revenue(view)
products_df = top_products(view)
products_df["Product"] = products_df["StockCode"] + "  " + products_df["Description"].fillna("")

c_left, c_right = st.columns(2)
with c_left:
    st.subheader("Revenue by country")
    st.plotly_chart(hbar(countries_df, "Country", "Revenue by country"), use_container_width=True)
with c_right:
    st.subheader("Top products by revenue")
    st.plotly_chart(hbar(products_df, "Product", "Top products"), use_container_width=True)

with st.expander("Show the data behind the charts"):
    st.markdown("**Monthly**")
    st.dataframe(monthly, hide_index=True, use_container_width=True)
    t1, t2 = st.columns(2)
    with t1:
        st.markdown("**By country**")
        st.dataframe(countries_df, hide_index=True, use_container_width=True)
    with t2:
        st.markdown("**Top products**")
        st.dataframe(products_df.drop(columns="Product"), hide_index=True, use_container_width=True)