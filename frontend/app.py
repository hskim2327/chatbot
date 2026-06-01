import os

import requests
import streamlit as st

API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="RFP RAG Search", page_icon="🔎", layout="wide")

st.markdown(
    """
    <style>
    :root {
        --blue: #2563eb;
        --blue-dark: #1d4ed8;
        --blue-soft: #eff6ff;
        --blue-border: #bfdbfe;
        --ink: #0f172a;
    }
    .stButton button, div[data-testid="stFormSubmitButton"] button {
        background: var(--blue);
        border-color: var(--blue);
        color: white;
        border-radius: 8px;
    }
    .stButton button:hover, div[data-testid="stFormSubmitButton"] button:hover {
        background: var(--blue-dark);
        border-color: var(--blue-dark);
        color: white;
    }
    .panel {
        border: 1px solid var(--blue-border);
        background: var(--blue-soft);
        color: var(--ink);
        border-radius: 8px;
        padding: 14px 16px;
        margin: 12px 0 16px;
    }
    .chip {
        display: inline-block;
        padding: 4px 8px;
        margin: 0 6px 6px 0;
        border-radius: 999px;
        border: 1px solid var(--blue-border);
        background: white;
        color: #1e3a8a;
        font-size: 0.85rem;
    }
    .app-title {
        display: flex;
        align-items: center;
        gap: 14px;
        margin: 4px 0 14px;
    }
    .app-title-icon {
        width: 34px;
        height: 34px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 4px;
        background: #f1eef8;
        color: #7c6aa6;
        font-size: 24px;
        line-height: 1;
        text-decoration: none;
        cursor: pointer;
    }
    .app-title-icon:hover {
        background: #e8e1f3;
    }
    .app-title-text {
        font-size: 32px;
        font-weight: 800;
        letter-spacing: 0;
        color: #1f2937;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="app-title">
      <a class="app-title-icon" href="/" target="_self" title="새로고침">📄</a>
      <div class="app-title-text">TEAM 3_RFP 문서 검색 chatbot</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption("나라장터 RFP 문서검색 chatbot입니다. 발주기관 필터에서 기관 선택 후, 질문사항을 빈칸에 적어주세요.")


@st.cache_data(ttl=60, show_spinner=False)
def fetch_issuers() -> list[str]:
    res = requests.get(f"{API_URL}/issuers", timeout=5)
    res.raise_for_status()
    return res.json().get("issuers", [])


def render_result(data: dict, show_debug: bool) -> None:
    st.divider()
    st.subheader("답변")
    st.markdown(
        f"""
        <div class="panel">
        <b>검색 대상</b>: {", ".join(data.get("issuers", []))}<br>
        <b>질문 유형</b>: {data.get("question_type", "")}<br>
        <b>Latency</b>: {data.get("latency_sec", 0):.2f}s
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write(data.get("answer", ""))

    debug = data.get("debug", {}) or {}
    if "llm_fallback" in data.get("route", []):
        st.warning("LLM 답변 생성에 실패하여 검색 근거 기반 fallback 답변을 표시했습니다.")
        if show_debug and debug.get("llm_error"):
            st.code(debug["llm_error"])

    manual = data.get("manual_lookup_contexts", [])
    if manual:
        st.info("문서에서 확인된 나라장터 공고번호로 추가 확인할 수 있습니다.")
        for item in manual:
            st.markdown(
                f"- 공고번호: `{item.get('notice_number', '')}` · "
                f"[나라장터 바로가기]({item.get('g2b_url', 'https://www.g2b.go.kr/index.jsp')})"
            )

    with st.expander("참고 문서 보기", expanded=False):
        for ctx in data.get("retrieved_contexts", []):
            meta = ctx.get("metadata", {})
            st.markdown(f"**[{ctx.get('rank')}] {ctx.get('filename') or 'context'}**")
            st.caption(f"{ctx.get('retriever', '')} · {meta.get('fact_type', '')} · {meta.get('section_path', '')}")
            st.write((ctx.get("text") or "")[:1200])
            st.divider()

    if show_debug:
        with st.expander("Debug", expanded=False):
            st.json({"route": data.get("route", []), "debug": data.get("debug", {})})


if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "last_error" not in st.session_state:
    st.session_state.last_error = None
if "last_show_debug" not in st.session_state:
    st.session_state.last_show_debug = True

try:
    issuers = fetch_issuers()
except Exception as exc:
    issuers = []
    st.warning(f"발주기관 목록을 불러오지 못했습니다: {exc}")

with st.form("ask_form", clear_on_submit=False):
    left, right = st.columns([0.36, 0.64], gap="large")
    with left:
        st.subheader("발주기관 선택")
        selected_from_list = st.multiselect(
            "반드시 하나 이상의 기관을 선택해주세요",
            options=issuers,
            placeholder="발주기관을 검색하거나 여러 개 선택하세요",
        )
        selected_issuers = []
        for issuer in selected_from_list:
            if issuer and issuer not in selected_issuers:
                selected_issuers.append(issuer)
        if selected_issuers:
            st.caption(f"검색 대상: {', '.join(selected_issuers)}")
        max_contexts = st.slider("최대 context 수", min_value=2, max_value=8, value=5, step=1)
        show_debug = st.checkbox("Debug 보기", value=True)

    with right:
        st.subheader("질문")
        question = st.text_area(
            "질문",
            placeholder="예) 한국가스공사의 차세대 ERP 구축 사업 예산 규모는 얼마입니까?",
            height=138,
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("검색", type="primary", use_container_width=True)

if submitted:
    st.session_state.last_error = None
    if not selected_issuers:
        st.session_state.last_error = "발주기관을 최소 1개 입력하거나 선택해주세요."
    elif not question.strip():
        st.session_state.last_error = "질문을 입력해주세요."
    else:
        with st.spinner("검색과 답변 생성을 진행 중입니다..."):
            try:
                res = requests.post(
                    f"{API_URL}/ask",
                    json={
                        "question": question,
                        "issuers": selected_issuers,
                        "max_contexts": max_contexts,
                        "debug": show_debug,
                    },
                    timeout=240,
                )
                res.raise_for_status()
                st.session_state.last_result = res.json()
                st.session_state.last_show_debug = show_debug
            except requests.exceptions.Timeout:
                st.session_state.last_error = "요청 시간이 초과되었습니다. FastAPI 또는 LLM 생성 로그를 확인해주세요."
            except requests.exceptions.HTTPError:
                try:
                    detail = res.json().get("detail", res.text)
                except Exception:
                    detail = res.text
                st.session_state.last_error = f"오류: {detail}"
            except Exception as exc:
                st.session_state.last_error = f"요청 실패: {exc}"

if st.session_state.last_error:
    st.error(st.session_state.last_error)

if st.session_state.last_result:
    render_result(st.session_state.last_result, show_debug=st.session_state.last_show_debug)
