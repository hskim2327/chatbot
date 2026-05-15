import json

def load_chunks_jsonl(path: str):
    chunks = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)

            chunks.append({
                "chunk_id": item["chunk_id"],
                "doc_id": item["doc_id"],
                "text": item["content"],
                "metadata": {
                    "source_file": item.get("source_file"),
                    "project_name": item.get("project_name"),
                    "issuer": item.get("issuer"),
                    "budget": item.get("metadata_budget"),
                    "section_path": item.get("section_path"),
                    "section_type": item.get("section_type"),
                    "chunk_type": item.get("chunk_type"),
                    "dates": item.get("dates"),
                    "amounts": item.get("amounts"),
                    "exact_terms": item.get("exact_terms"),
                }
            })

    return chunks