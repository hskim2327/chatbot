from rank_bm25 import BM25Okapi

from src.retriever.metadata_filter import matches_metadata


class BM25Retriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.tokenized_corpus = [
            chunk["text"].split()
            for chunk in chunks
        ]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

    def retrieve(self, query, top_k=5, metadata_filter=None):
        tokenized_query = query.split()
        scores = self.bm25.get_scores(tokenized_query)

        ranked = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True
        )

        results = []
        for corpus_rank, (idx, score) in enumerate(ranked, 1):
            item = self.chunks[idx].copy()
            if not matches_metadata(item, metadata_filter):
                continue
            item["score"] = float(score)
            item["bm25_score"] = float(score)
            item["bm25_rank"] = corpus_rank
            results.append(item)
            if len(results) >= top_k:
                break

        return results
