from src.data import load_chunks_jsonl
from src.retriever import BM25Retriever
from src.generator.openai_generator import OpenAIGenerator


class RAGPipeline:
    def __init__(self, chunk_path, api_key, top_k=5):
        self.chunks = load_chunks_jsonl(chunk_path)
        self.retriever = BM25Retriever(self.chunks)
        self.generator = OpenAIGenerator(api_key=api_key)
        self.top_k = top_k

    def run(self, query):
        retrieved = self.retriever.retrieve(query, top_k=self.top_k)
        contexts = [item["text"] for item in retrieved]
        answer = self.generator.generate(query, contexts)

        return {
            "query": query,
            "answer": answer,
            "retrieved": retrieved,
        }