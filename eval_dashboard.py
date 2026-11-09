"""
RAG Evaluation Dashboard
Run: streamlit run eval_dashboard.py
"""
import os

import pandas as pd
import plotly.express as px
import sqlalchemy as sa
import streamlit as st

VERDICT_COLORS = {
    "pass": "#2ecc71",
    "needs_review": "#f39c12",
    "fail": "#e74c3c",
}

st.set_page_config(page_title="RAG Eval Dashboard", page_icon="📊", layout="wide")
st.title("📊 RAG Evaluation Dashboard")

_JUDGE_RENAMES = {
    "judge_grounded": "judge.grounded",
    "judge_answers_question": "judge.answers_question",
    "judge_missing_context": "judge.missing_context",
    "judge_missing_parts": "judge.missing_parts",
    "judge_unsupported_claims": "judge.unsupported_claims",
    "judge_entity_errors": "judge.entity_errors",
    "judge_reason": "judge.reason",
}


# ── Load data ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=10)
def load_data() -> pd.DataFrame:
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        st.error("DATABASE_URL environment variable is not set.")
        return pd.DataFrame()
    # Pin the sync driver explicitly: SQLAlchemy 2.1 made bare postgresql:// default to psycopg (v3).
    db_url = sa.engine.make_url(raw_url).set(drivername="postgresql+psycopg2")
    engine = sa.create_engine(db_url)
    try:
        df = pd.read_sql("SELECT * FROM chat_eval_records ORDER BY created_at DESC", engine)
    except Exception as exc:
        st.error(f"Failed to load data from database: {exc}")
        return pd.DataFrame()
    finally:
        engine.dispose()
    if df.empty:
        return df
    df = df.rename(columns=_JUDGE_RENAMES)
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    df["date"] = df["created_at"].dt.date
    df = df.dropna(subset=["date"])
    return df


df_all = load_data()

if df_all.empty:
    st.warning("No eval data found in the database. Send some chat messages first.")
    st.stop()


# ── Sidebar filters ───────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Filters")

    run_ids = sorted(df_all["run_id"].dropna().unique())
    selected_runs = st.multiselect("Run ID", run_ids, default=run_ids)

    verdicts = ["pass", "needs_review", "fail"]
    selected_verdicts = st.multiselect("Verdict", verdicts, default=verdicts)

    sessions = sorted(df_all["session_id"].dropna().unique())
    selected_sessions = st.multiselect("Session", sessions, default=sessions)

    date_min = df_all["date"].min()
    date_max = df_all["date"].max()
    date_range = st.date_input("Date range", value=(date_min, date_max))

    st.divider()
    if st.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()

df = df_all[
    df_all["run_id"].isin(selected_runs)
    & df_all["judge_verdict"].isin(selected_verdicts)
    & df_all["session_id"].isin(selected_sessions)
]
if len(date_range) == 2:
    df = df[(df["date"] >= date_range[0]) & (df["date"] <= date_range[1])]

if df.empty:
    st.warning("No data matches the current filters.")
    st.stop()


# ── Summary cards ─────────────────────────────────────────────────────────────

total = len(df)
pass_pct = (df["judge_verdict"] == "pass").mean() * 100
avg_latency = df["latency_ms"].mean() / 1000 if "latency_ms" in df.columns else 0
total_cost = df["cost_estimate_usd"].sum() if "cost_estimate_usd" in df.columns else 0
regen_rate = df["regenerated"].mean() * 100 if "regenerated" in df.columns else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total questions", total)
c2.metric("Pass rate", f"{pass_pct:.1f}%")
c3.metric("Avg latency", f"{avg_latency:.1f}s")
c4.metric("Total cost", f"${total_cost:.4f}")
c5.metric("Regeneration rate", f"{regen_rate:.1f}%")

st.divider()


# ── Charts row ────────────────────────────────────────────────────────────────

col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("Verdict distribution")
    verdict_counts = df["judge_verdict"].value_counts().reset_index()
    verdict_counts.columns = ["verdict", "count"]
    fig = px.pie(
        verdict_counts, values="count", names="verdict",
        color="verdict",
        color_discrete_map=VERDICT_COLORS,
        hole=0.4,
    )
    fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), showlegend=True)
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Latency distribution (s)")
    if "latency_ms" in df.columns:
        fig = px.histogram(
            df, x=df["latency_ms"] / 1000,
            nbins=20, labels={"x": "Latency (s)"},
            color_discrete_sequence=["#3498db"],
        )
        fig.update_layout(margin=dict(t=0, b=0), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No latency data.")

with col3:
    st.subheader("Cost over time")
    if "cost_estimate_usd" in df.columns:
        daily_cost = df.groupby("date")["cost_estimate_usd"].sum().reset_index()
        fig = px.line(
            daily_cost, x="date", y="cost_estimate_usd",
            labels={"cost_estimate_usd": "Cost (USD)", "date": "Date"},
            markers=True,
            color_discrete_sequence=["#9b59b6"],
        )
        fig.update_layout(margin=dict(t=0, b=0), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No cost data.")

st.divider()


# ── Run comparison ────────────────────────────────────────────────────────────

if len(selected_runs) > 1:
    st.subheader("Run comparison")
    run_stats = df.groupby("run_id").agg(
        questions=("question_id", "count"),
        pass_rate=("judge_verdict", lambda x: (x == "pass").mean() * 100),
        needs_review_rate=("judge_verdict", lambda x: (x == "needs_review").mean() * 100),
        fail_rate=("judge_verdict", lambda x: (x == "fail").mean() * 100),
        avg_latency_s=("latency_ms", lambda x: x.mean() / 1000),
        total_cost_usd=("cost_estimate_usd", "sum"),
        regen_rate=("regenerated", lambda x: x.mean() * 100),
    ).round(2).reset_index()
    st.dataframe(run_stats, use_container_width=True, hide_index=True)
    st.divider()


# ── Verdict by retrieval confidence ──────────────────────────────────────────

st.subheader("Verdict by retrieval confidence")
cross = pd.crosstab(df["retrieval_confidence"], df["judge_verdict"])
cross = cross.reindex(columns=[v for v in verdicts if v in cross.columns])
st.dataframe(cross, use_container_width=True)

st.divider()


# ── Question table ────────────────────────────────────────────────────────────

st.subheader("Questions")
st.caption("Click a row to see its full details below.")

table_cols = ["created_at", "run_id", "judge_verdict", "retrieval_confidence",
              "generation_confidence", "latency_ms", "cost_estimate_usd",
              "regenerated", "question"]
available = [c for c in table_cols if c in df.columns]
df_sorted = df.sort_values("created_at", ascending=False).reset_index(drop=True)
df_display = df_sorted[available]

verdict_filter = st.selectbox("Filter table by verdict", ["All"] + verdicts, index=0)
if verdict_filter != "All":
    df_display = df_display[df_display["judge_verdict"] == verdict_filter]
    df_sorted = df_sorted[df_sorted["judge_verdict"] == verdict_filter].reset_index(drop=True)

selection = st.dataframe(
    df_display.style.apply(
        lambda row: [
            f"background-color: {VERDICT_COLORS.get(row.get('judge_verdict', ''), '#ffffff')}22"
        ] * len(row),
        axis=1,
    ),
    use_container_width=True,
    height=300,
    on_select="rerun",
    selection_mode="single-row",
)

st.divider()


# ── Question detail ───────────────────────────────────────────────────────────

st.subheader("Question detail")

selected_rows = selection.selection.get("rows", [])
if not selected_rows:
    st.info("Click a row in the table above to view its details.")
else:
    row = df_sorted.iloc[selected_rows[0]]

    verdict_color = VERDICT_COLORS.get(row.get("judge_verdict", ""), "#888")
    st.markdown(f"**Verdict:** <span style='color:{verdict_color}'>{row.get('judge_verdict', '—')}</span>", unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Question**")
        st.write(row.get("question", ""))
        st.markdown("**Answer**")
        st.write(row.get("answer", ""))

    with col_b:
        st.markdown("**Judge details**")
        judge_fields = {k: v for k, v in row.items() if k.startswith("judge.")}
        for k, v in judge_fields.items():
            label = k.replace("judge.", "")
            if v or v is False:
                st.write(f"- **{label}**: {v}")

        st.markdown("**Metrics**")
        st.write(f"- Latency: {row.get('latency_ms', 0)} ms")
        st.write(f"- Input tokens: {row.get('input_tokens', 0)}")
        st.write(f"- Output tokens: {row.get('output_tokens', 0)}")
        st.write(f"- Cost: ${row.get('cost_estimate_usd', 0):.6f}")
        st.write(f"- Model: {row.get('model', '—')}")
        st.write(f"- Regenerated: {row.get('regenerated', False)}")

        st.markdown("**Context chunk IDs** (generator)")
        st.code("\n".join(row.get("context_chunk_ids", []) or []))
        st.markdown("**Retrieved chunk IDs** (judge pool)")
        st.code("\n".join(row.get("retrieved_chunk_ids", []) or []))
