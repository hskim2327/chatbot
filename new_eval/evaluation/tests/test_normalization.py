from rag_eval.normalization import extract_top_unique_documents, parse_doc_list


def test_ground_truth_docs_string_list_is_parsed():
    docs = parse_doc_list('["doc-a.hwp", {"filename": "doc-b.pdf"}]')

    assert docs == ["doc-a.hwp", "doc-b.pdf"]


def test_unique_top_k_prefers_filename_and_deduplicates_by_rank():
    contexts = [
        {"rank": 3, "filename": "doc-b.hwp", "doc_id": "wrong-b"},
        {"rank": 1, "filename": "doc-a.hwp", "doc_id": "wrong-a", "chunk_id": "a1"},
        {"rank": 2, "filename": "doc-a.hwp", "doc_id": "wrong-a-2", "chunk_id": "a2"},
        {"rank": 4, "doc_id": "doc-c"},
        {"rank": 5, "filename": "doc-d.hwp"},
        {"rank": 6, "filename": "doc-e.hwp"},
        {"rank": 7, "filename": "doc-f.hwp"},
    ]

    result = extract_top_unique_documents(contexts, top_k=5)

    assert result == ["doc-a.hwp", "doc-b.hwp", "doc-c", "doc-d.hwp", "doc-e.hwp"]
