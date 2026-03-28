from __future__ import annotations

import streamlit as st

from app.components import render_answer_card, render_quick_facts, render_source_panel
from app.example_questions import EXAMPLE_QUESTIONS
from nepse_analyst.pipeline import run


def _init_state() -> None:
    if "query_input" not in st.session_state:
        st.session_state.query_input = ""
    if "last_result" not in st.session_state:
        st.session_state.last_result = None


def _render_sidebar() -> None:
    st.sidebar.title("NEPSE Analyst")
    st.sidebar.caption("Natural language research assistant for Nepal's stock market")

    st.sidebar.markdown("### Example Questions")
    for idx, question in enumerate(EXAMPLE_QUESTIONS):
        if st.sidebar.button(question, key=f"example_{idx}", use_container_width=True):
            st.session_state.query_input = question

    st.sidebar.markdown("---")
    st.sidebar.info(
        "This tool is for research information only. It does not provide buy/sell advice "
        "or price predictions."
    )


def _render_header() -> None:
    st.markdown(
        """
        <style>
        .hero {
            border: 1px solid #e8dfcf;
            border-radius: 12px;
            padding: 18px 20px;
            background: linear-gradient(135deg, #fff8ef 0%, #f8fbff 100%);
            margin-bottom: 14px;
        }
        .hero h1 {
            font-size: 1.8rem;
            margin-bottom: 0.3rem;
        }
        .hero p {
            color: #5a5f6d;
            margin-bottom: 0;
        }
        </style>
        <div class='hero'>
          <h1>NEPSE Analyst</h1>
          <p>Ask in English or Nepali. Get grounded answers with transparent sources.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _submit_query() -> None:
    query = (st.session_state.query_input or "").strip()
    if not query:
        st.warning("Please enter a question.")
        return

    with st.spinner("Analyzing query..."):
        result = run(query)
    st.session_state.last_result = result


def main() -> None:
    st.set_page_config(
        page_title="NEPSE Analyst",
        page_icon="chart_with_upwards_trend",
        layout="wide",
    )
    _init_state()
    _render_sidebar()
    _render_header()

    st.text_area(
        "Ask a NEPSE question",
        key="query_input",
        height=120,
        placeholder="Example: Which commercial bank has the highest EPS in the latest fiscal year?",
    )

    c1, c2 = st.columns([1, 5])
    if c1.button("Run", use_container_width=True):
        _submit_query()

    if st.session_state.last_result is not None:
        st.markdown("---")
        result = st.session_state.last_result
        render_answer_card(result)
        render_quick_facts(result, st.session_state.query_input)
        render_source_panel(result)


if __name__ == "__main__":
    main()
