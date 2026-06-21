import streamlit as st
import pandas as pd
import duckdb
import plotly.express as px
import plotly.graph_objects as go
import os

# Import modules from src
try:
    from database_init import DB_PATH, init_db
    from rule_engine import RuleEngine
    from ai_skills import AISkillsManager
except ImportError:
    from src.database_init import DB_PATH, init_db
    from src.rule_engine import RuleEngine
    from src.ai_skills import AISkillsManager

# Initialize components
@st.cache_resource
def get_ai_manager():
    return AISkillsManager()

@st.cache_resource
def get_rule_engine():
    return RuleEngine()

def fetch_macro_chart_data():
    """Fetches HS300 data for plotting."""
    try:
        conn = duckdb.connect(DB_PATH)
        query = """
        SELECT date, close FROM index_daily
        WHERE symbol = '000300'
        ORDER BY date ASC
        """
        df = conn.execute(query).df()
        conn.close()
        return df
    except:
        return pd.DataFrame()

# Main App Config
st.set_page_config(page_title="AI Trading Workbench", layout="wide", page_icon="📈")
st.title("AI Trading Workbench & Diagnostic System")

ai_manager = get_ai_manager()
engine = get_rule_engine()

# Tabs
tab1, tab2, tab3 = st.tabs(["🩺 Position Check", "🧠 Daily Review", "📡 Radar Monitor"])

# ==================== TAB 1: Position Check ====================
with tab1:
    st.header("Holdings / Watchlist Diagnostic Check")
    st.markdown("Enter a stock code and your investment logic. Our AI and Serenity Plugin will diagnose hidden risks.")

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Input")
        symbol_input = st.text_input("Stock Symbol (e.g., 000001)", value="000001")
        logic_input = st.text_area("Your Thesis / Logic", value="Strong fundamentals and cheap valuation.")
        submit_btn = st.button("Run Diagnostic")

    with col2:
        st.subheader("Diagnostic Report")
        if submit_btn:
            if not symbol_input or not logic_input:
                st.warning("Please enter both symbol and logic.")
            else:
                with st.spinner("Calling Serenity Plugin & Gemini AI..."):
                    report = ai_manager.diagnose_position(symbol_input, logic_input)
                    st.markdown(report)

# ==================== TAB 2: Daily Review ====================
with tab2:
    st.header("Daily AI Review & Tomorrow's Pre-Plan")
    st.markdown("Generates actionable advice based on today's Triple Funnel output.")

    if st.button("Generate Daily Report"):
        with st.spinner("Running Triple Funnel and fetching AI insights..."):
            # Run funnel
            results = engine.run_all()

            # Fetch AI Review
            review_md = ai_manager.review_daily(
                macro_data={"macro_healthy": results['macro_healthy'], "macro_ratio": results['macro_ratio']},
                top_sectors=results['top_sectors'],
                radar_list=results['selected_stocks']
            )

            st.markdown("### AI Review Report")
            st.markdown(review_md)

# ==================== TAB 3: Radar Monitor ====================
with tab3:
    st.header("Radar & Macro Monitor")

    colA, colB = st.columns([2, 1])

    with colA:
        st.subheader("Macro Index Trend (HS300)")
        df_index = fetch_macro_chart_data()

        if not df_index.empty:
            fig = px.line(df_index, x='date', y='close', title='HS300 Trend')
            fig.update_layout(xaxis_title="Date", yaxis_title="Close Price")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No index data available. Please run data fetcher first.")

    with colB:
        st.subheader("Today's Triple Funnel Results")
        if st.button("Run Funnel", key="run_funnel_tab3"):
            with st.spinner("Running Funnel..."):
                results = engine.run_all()

                st.metric("Macro Health", "Healthy" if results['macro_healthy'] else "Caution")
                st.metric("Breadth Ratio (>50MA)", f"{results['macro_ratio']:.2%}")

                st.markdown("**Top Sectors:**")
                st.write(results['top_sectors'])

                st.markdown(f"**Stocks Passed Filter ({len(results['selected_stocks'])}):**")
                if len(results['selected_stocks']) > 0:
                    df_stocks = pd.DataFrame(results['selected_stocks'])
                    st.dataframe(df_stocks)
                else:
                    st.write("No stocks passed the strict filter today.")
