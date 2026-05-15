import os
import sys
from dotenv import load_dotenv

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.data import load_chunks_jsonl
from src.retriever import BM25Retriever
from src.generator.openai_generator import OpenAIGenerator

load_dotenv()

chunks = load_chunks_jsonl("data/processed/chunks_v2.jsonl")

retriever = BM25Retriever(chunks)

generator = OpenAIGenerator(
    api_key=os.getenv("OPENAI_API_KEY")
)

query = "한국가스공사의 '차세대 통합정보시스템(ERP) 구축' 사업 예산 규모는 얼마입니까?"

results = retriever.retrieve(query, top_k=5)

contexts = [r["text"] for r in results]

answer = generator.generate(query, contexts)

print("\n[QUESTION]")
print(query)

print("\n[RETRIEVED CHUNKS]")
for i, r in enumerate(results, 1):
    print(f"\n--- chunk {i} ---")
    print("score:", r["score"])
    print("doc_id:", r["doc_id"])
    print("project:", r["metadata"].get("project_name"))
    print("issuer:", r["metadata"].get("issuer"))
    print(r["text"][:300])

print("\n[ANSWER]")
print(answer)