import os
import sys
from dotenv import load_dotenv

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.pipeline import RAGPipeline

load_dotenv()

pipeline = RAGPipeline(
    chunk_path="data/processed/chunks_v2.jsonl",
    api_key=os.getenv("OPENAI_API_KEY"),
    top_k=5,
)

query = "한국가스공사의 '차세대 통합정보시스템(ERP) 구축' 사업 예산 규모는 얼마입니까?"

result = pipeline.run(query)

print("[QUESTION]")
print(result["query"])

print("\n[ANSWER]")
print(result["answer"])

print("\n[SOURCES]")
for i, item in enumerate(result["retrieved"], 1):
    print(f"\n--- source {i} ---")
    print("score:", item["score"])
    print("doc_id:", item["doc_id"])
    print("project:", item["metadata"].get("project_name"))
    print("issuer:", item["metadata"].get("issuer"))