import traceback

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.schemas import AskRequest, AskResponse, IssuersResponse
from app.db.chroma_client import get_all_issuers
from app.rag.llm import generate
from app.rag.pipeline import answer_question

app = FastAPI(title="RFP RAG API", version="2.0-clean")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/issuers", response_model=IssuersResponse)
async def issuers():
    try:
        return {"issuers": get_all_issuers()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": str(exc), "traceback": traceback.format_exc()}) from exc


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    try:
        return await answer_question(
            question=req.question,
            issuers=req.issuers,
            max_contexts=req.max_contexts,
            include_debug=req.debug,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": str(exc), "traceback": traceback.format_exc()}) from exc


@app.post("/query", response_model=AskResponse)
async def query(req: AskRequest):
    return await ask(req)


@app.get("/llm-test")
async def llm_test():
    try:
        text = await generate("짧게 답하세요.", "정상 연결이면 OK라고만 답하세요.", max_tokens=20)
        return {"ok": True, "answer": text}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
