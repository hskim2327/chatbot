"""
RFP 문서 검색 chatbot 실행 파일입니다.

권장 실행:
1. FastAPI 서버: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
2. Streamlit UI:  python -m streamlit run main.py

이 파일은 Streamlit UI 진입점이며, 실제 RAG API는 app/ 폴더의 FastAPI 서버에서 실행됩니다.
"""

from frontend.app import *  # noqa: F401,F403
