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
st.set_page_config(page_title="AI 交易复盘与智能诊断工作台", layout="wide", page_icon="📈")
st.title("AI 交易复盘与智能诊断系统")

ai_manager = get_ai_manager()
engine = get_rule_engine()

# Tabs
tab1, tab2, tab3 = st.tabs(["🩺 持仓体检", "🧠 每日复盘", "📡 雷达监控"])

# ==================== TAB 1: Position Check ====================
with tab1:
    st.header("自选股/持仓深度诊断")
    st.markdown("输入股票代码与你的买入逻辑，系统将调用大模型与 Serenity 防伪插件出具供应链与风险体检报告。")

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("输入信息")
        symbol_input = st.text_input("股票代码 (例如: 000001)", value="000001")
        logic_input = st.text_area("买入逻辑 / 投研假设", value="基本面确定性高，目前估值低，存在认知分歧。")
        submit_btn = st.button("运行智能诊断")

    with col2:
        st.subheader("诊断报告")
        if submit_btn:
            if not symbol_input or not logic_input:
                st.warning("请输入股票代码和投资逻辑。")
            else:
                with st.spinner("正在调用 Serenity 插件与 Gemini 深度分析..."):
                    report = ai_manager.diagnose_position(symbol_input, logic_input)
                    st.markdown(report)

# ==================== TAB 2: Daily Review ====================
with tab2:
    st.header("AI 盘后复盘与明日预案")
    st.markdown("结合今日 Triple Funnel（三重漏斗）跑出的雷达名单，由 AI 为您提炼核心教训并生成结构化明日预案。")

    if st.button("生成今日复盘报告"):
        with st.spinner("正在运行漏斗计算并获取 AI 洞察..."):
            # Run funnel
            results = engine.run_all()

            # Fetch AI Review
            review_md = ai_manager.review_daily(
                macro_data={"macro_healthy": results['macro_healthy'], "macro_ratio": results['macro_ratio']},
                top_sectors=results['top_sectors'],
                radar_list=results['selected_stocks']
            )

            st.markdown("### AI 投研复盘简报")
            st.markdown(review_md)

# ==================== TAB 3: Radar Monitor ====================
with tab3:
    st.header("全市场雷达与宏观监控")

    colA, colB = st.columns([2, 1])

    with colA:
        st.subheader("宏观水位 (沪深300走势)")
        df_index = fetch_macro_chart_data()

        if not df_index.empty:
            fig = px.line(df_index, x='date', y='close', title='沪深300指数')
            fig.update_layout(xaxis_title="日期", yaxis_title="收盘价")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无指数数据，请先运行 data_fetcher 数据底座。")

    with colB:
        st.subheader("今日漏斗选股结果")
        if st.button("执行三重漏斗", key="run_funnel_tab3"):
            with st.spinner("正在扫描全市场数据..."):
                results = engine.run_all()

                st.metric("宏观环境健康度", "健康 (做多区间)" if results['macro_healthy'] else "谨慎 (防守区间)")
                st.metric("市场宽度 (站上50日均线比例)", f"{results['macro_ratio']:.2%}")

                st.markdown("**强势领涨板块 (Top RPS):**")
                st.write(results['top_sectors'])

                st.markdown(f"**符合特征个股 ({len(results['selected_stocks'])} 只):**")
                if len(results['selected_stocks']) > 0:
                    df_stocks = pd.DataFrame(results['selected_stocks'])
                    st.dataframe(df_stocks)
                else:
                    st.write("今日无个股满足所有严苛过滤条件。")
