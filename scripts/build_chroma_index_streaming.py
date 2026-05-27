import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.data import load_chunks_jsonl
from src.embeddings import create_embedder, embedding_preset_choices
from src.vectorstore.chroma_store import ChromaVectorStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Chroma index without keeping all embeddings in RAM.")
    parser.add_argument("--chunks", required=True)
    parser.add_argument("--index-dir", required=True)
    parser.add_argument("--embedding-preset", choices=embedding_preset_choices(), default="kure")
    parser.add_argument("--embedding-provider", choices=["openai", "huggingface"])
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-batch-size", type=int, default=32)
    parser.add_argument("--upsert-batch-size", type=int, default=500)
    parser.add_argument("--chroma-collection", default="rfp_chunks")
    args = parser.parse_args()

    load_dotenv()
    chunks = load_chunks_jsonl(args.chunks)
    if not chunks:
        raise SystemExit(f"No chunks loaded from {args.chunks}")

    embedder = create_embedder(
        preset=args.embedding_preset,
        provider=args.embedding_provider,
        model=args.embedding_model,
        api_key=os.getenv("OPENAI_API_KEY"),
        batch_size=args.embedding_batch_size,
    )
    store = ChromaVectorStore(args.index_dir, collection_name=args.chroma_collection)
    store.chunks = chunks
    store._reset_collection()
    store._save_chunks_sidecar()

    total = len(chunks)
    for start in tqdm(range(0, total, args.upsert_batch_size), desc="indexing"):
        end = min(start + args.upsert_batch_size, total)
        batch = chunks[start:end]
        texts = [chunk.get("text", "") for chunk in batch]
        embeddings = embedder.embed_texts(texts, batch_size=args.embedding_batch_size)
        ids = [
            f"{chunk.get('doc_id') or 'doc'}:{chunk.get('chunk_id') or idx}:{idx}"
            for idx, chunk in enumerate(batch, start)
        ]
        metadatas = [store._metadata_for_chroma(idx, chunk) for idx, chunk in enumerate(batch, start)]
        store.collection.upsert(
            ids=ids,
            embeddings=[[float(value) for value in vector] for vector in embeddings],
            documents=texts,
            metadatas=metadatas,
        )

    print(f"vector_store: chroma")
    print(f"chunks: {args.chunks}")
    print(f"indexed_chunks: {total}")
    print(f"index_dir: {args.index_dir}")
    print(f"embedding_preset: {args.embedding_preset}")
    print(f"embedding_model: {getattr(embedder, 'model', args.embedding_model)}")
    print(f"chroma_collection: {args.chroma_collection}")


if __name__ == "__main__":
    main()
