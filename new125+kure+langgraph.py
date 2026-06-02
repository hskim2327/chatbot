#!/usr/bin/env python
# coding: utf-8
# Converted from new125+kure+langgraph.ipynb


# %% [markdown] cell 1
# # new125 KURE + Detailed LangGraph + G2B Tool Node
#
# This version keeps the detailed LangGraph pipeline and adds a controlled G2B budget lookup node.
#
# - The G2B node runs only when `question_type == budget` and final selected context is empty.
# - It uses the official data.go.kr PPS/Nara BidPublicInfoService service-search endpoint.
# - API key is read from Colab secret or environment variable `G2B_SERVICE_KEY`.
# - The node creates synthetic safe `project_budget` contexts only from budget-like API fields.

# %% [code] cell 2
!pip install -qU chromadb sentence-transformers transformers accelerate bitsandbytes pandas tqdm langgraph requests

# %% [code] cell 3
# 0. Install packages
# If transformers/huggingface_hub import errors occur after install, restart runtime once.
!pip install -qU   "langchain" "langgraph" "requests" "langchain-community" "langchain-chroma" "langchain-huggingface"   "rank-bm25" "sentence-transformers"   "transformers>=4.56.0,<5" "huggingface_hub>=0.34.0,<1.0"   "tokenizers>=0.22.0,<0.23.1" "accelerate" "bitsandbytes"

# %% [code] cell 4
from google.colab import drive
drive.mount('/content/drive')

# %% [markdown] cell 5
# ## 1. 경로 설정

# %% [code] cell 6
from pathlib import Path

DATA_DIR = Path('/content/drive/MyDrive/data/125_new')
CHUNKS_PATH = DATA_DIR / 'chunks_v2_125.jsonl'
EVAL_GOLD_DIR = DATA_DIR / 'eval' / 'eval_gold_agency_from_gt_docs'

DRIVE_CHROMA_PATH = DATA_DIR / 'outputs' / 'chroma_kurev1_125'
LOCAL_CHROMA_PATH = Path('/content/chroma_kurev1_125')
COLLECTION_NAME = 'new_125_kurev1_v2'

EMBED_MODEL_NAME = 'nlpai-lab/KURE-v1'
LLM_MODEL_NAME = 'sh2orc/Llama-3.1-Korean-8B-Instruct'

EVAL_METRIC_K = 5
MAX_CONTEXTS = 5

DENSE_K = 50
SPARSE_K = 50

print('CHUNKS_PATH:', CHUNKS_PATH)
print('EVAL_GOLD_DIR:', EVAL_GOLD_DIR)
print('DRIVE_CHROMA_PATH:', DRIVE_CHROMA_PATH)

# %% [markdown] cell 7
# ## 2. Imports / 유틸

# %% [code] cell 8
import ast, difflib, json, math, os, re, shutil, time, unicodedata
from collections import Counter, defaultdict
from typing import Any, TypedDict

import chromadb
import numpy as np
import pandas as pd
import requests
import torch
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from tqdm.auto import tqdm
from langgraph.graph import END, StateGraph


def nfc(value: Any) -> str:
    return unicodedata.normalize('NFC', '' if value is None else str(value)).strip()


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'true', '1', 'yes', 'y'}


def normalize_doc_for_metric(value) -> str:
    text = unicodedata.normalize('NFC', '' if value is None else str(value)).strip()
    text = re.sub(r'\.(hwp|hwpx|pdf|docx?|xlsx?)$', '', text, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', text)


def format_krw(value: Any) -> str:
    if value in (None, ''):
        return ''
    try:
        return f'{int(float(str(value).replace(",", ""))):,}원'
    except Exception:
        return str(value)

# %% [markdown] cell 9
# ## 3. Chroma DB 복원/로드

# %% [code] cell 10
def restore_drive_chroma_to_local(drive_path=DRIVE_CHROMA_PATH, local_path=LOCAL_CHROMA_PATH, collection_name=COLLECTION_NAME, overwrite=False):
    if local_path.exists() and not overwrite:
        print('Use existing local Chroma:', local_path)
    else:
        assert drive_path.exists(), f'Drive Chroma backup not found: {drive_path}'
        if local_path.exists():
            shutil.rmtree(local_path)
        shutil.copytree(drive_path, local_path)
        print('Restored Drive Chroma to local:', local_path)

    client = chromadb.PersistentClient(path=str(local_path))
    collection = client.get_collection(collection_name)
    print('collection:', collection_name)
    print('count:', collection.count())
    return client, collection


client, collection = restore_drive_chroma_to_local(overwrite=False)

# %% [markdown] cell 11
# ## 4. chunks 로드 / metadata 정리

# %% [code] cell 12
MONEY_PATTERN = re.compile(r'(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<unit>천원|백만원|억원|만원|원)?')
UNIT_MULTIPLIER = {'원': 1, '만원': 10_000, '천원': 1_000, '백만원': 1_000_000, '억원': 100_000_000, None: 1, '': 1}


def normalize_korean_money(text):
    raw = nfc(text)
    if not raw:
        return '', None
    match = MONEY_PATTERN.search(raw)
    if not match:
        return raw, None
    number = float(match.group('num').replace(',', ''))
    unit = match.group('unit') or '원'
    return match.group(0), int(number * UNIT_MULTIPLIER.get(unit, 1))


def first_nonempty(*values):
    for value in values:
        if value not in (None, ''):
            return value
    return ''


def iter_jsonl(path):
    with path.open('r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


records = list(iter_jsonl(CHUNKS_PATH))
CHUNK_BY_ID = {r.get('chunk_id'): r for r in records}
print('records:', len(records))
print('chunk_type:', Counter(r.get('chunk_type') for r in records))


def clean_metadata(record):
    meta = dict(record.get('metadata') or {})
    for key in ['chunk_id', 'doc_id', 'doc_key', 'source_file', 'chunk_type', 'fact_type']:
        if key not in meta or meta.get(key) in (None, ''):
            meta[key] = record.get(key, '')
    source_ref = record.get('source_ref') or {}
    if 'source_store_id' not in meta and source_ref.get('source_store_id'):
        meta['source_store_id'] = source_ref.get('source_store_id')

    raw_money = first_nonempty(meta.get('amount_raw'), meta.get('final_budget'))
    krw_value = first_nonempty(meta.get('amount_krw'), meta.get('final_budget_krw'))
    if krw_value not in (None, ''):
        try:
            krw_value = int(float(str(krw_value).replace(',', '')))
        except Exception:
            krw_value = None
    else:
        extracted_raw, extracted_krw = normalize_korean_money(raw_money or record.get('content', ''))
        raw_money = raw_money or extracted_raw
        krw_value = extracted_krw
    if raw_money:
        meta['money_raw'] = nfc(raw_money)
    if krw_value is not None:
        meta['money_krw'] = int(krw_value)
        meta['money_krw_display'] = format_krw(krw_value)
    meta['money_role'] = first_nonempty(meta.get('budget_value_role'), meta.get('amount_type'), meta.get('budget_type'), record.get('fact_type'))
    return meta

# %% [markdown] cell 13
# ## 5. KURE query embedding / dense 검색

# %% [code] cell 14
embed_model = SentenceTransformer(EMBED_MODEL_NAME, device='cuda' if torch.cuda.is_available() else 'cpu')
print('embed model:', EMBED_MODEL_NAME, '| device:', embed_model.device)


def encode_texts(texts):
    emb = embed_model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    return emb.astype('float32').tolist()


def query_chroma(question, n_results=50, where=None):
    q_emb = encode_texts([question])[0]
    result = collection.query(query_embeddings=[q_emb], n_results=n_results, where=where, include=['documents', 'metadatas', 'distances'])
    rows = []
    for i, chunk_id in enumerate(result.get('ids', [[]])[0]):
        dist = result.get('distances', [[]])[0][i]
        rows.append({
            'rank': i + 1,
            'chunk_id': chunk_id,
            'text': result.get('documents', [[]])[0][i],
            'metadata': result.get('metadatas', [[]])[0][i] or {},
            'distance': dist,
            'similarity': 1 - dist if dist is not None else None,
            'retriever': 'dense',
        })
    return rows


def dense_retrieve(question, k=DENSE_K, where=None):
    return query_chroma(question, n_results=k, where=where)

# %% [markdown] cell 15
# ## 6. Sparse BM25 / alias n-gram

# %% [code] cell 16
def sparse_norm(text):
    text = unicodedata.normalize('NFC', '' if text is None else str(text))
    text = re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip().lower()


def sparse_char_tokens(text, ns=(2, 3)):
    compact = re.sub(r'\s+', '', sparse_norm(text))
    tokens = []
    for n in ns:
        if len(compact) >= n:
            tokens.extend(compact[i:i+n] for i in range(len(compact)-n+1))
    tokens.extend(tok for tok in sparse_norm(text).split() if len(tok) >= 2)
    return tokens


BM25_RECORDS = [r for r in records if nfc(r.get('content'))]
BM25_INDEX = BM25Okapi([sparse_char_tokens(r.get('content', '')) for r in tqdm(BM25_RECORDS, desc='BM25 tokenize')])


def metadata_matches_filter(meta, where=None):
    if not where:
        return True
    for key, expected in where.items():
        actual = nfc(meta.get(key))
        if isinstance(expected, dict) and '$in' in expected:
            allowed = {nfc(value) for value in expected.get('$in', [])}
            if actual not in allowed:
                return False
        elif actual != nfc(expected):
            return False
    return True


def sparse_retrieve(question, k=SPARSE_K, where=None):
    scores = BM25_INDEX.get_scores(sparse_char_tokens(question))
    top_idx = np.argsort(scores)[::-1]
    output = []
    for idx in top_idx:
        score = float(scores[int(idx)])
        if score <= 0:
            break
        record = BM25_RECORDS[int(idx)]
        meta = clean_metadata(record)
        if not metadata_matches_filter(meta, where):
            continue
        output.append({'rank': len(output) + 1, 'chunk_id': record.get('chunk_id'), 'text': record.get('content', ''), 'metadata': meta, 'sparse_score': score, 'retriever': 'sparse'})
        if len(output) >= k:
            break
    return output

# %% [code] cell 17
def alias_norm(text):
    return re.sub(r'[^가-힣a-zA-Z0-9]', '', unicodedata.normalize('NFC', '' if text is None else str(text))).lower()


def alias_ngrams(text, n):
    t = alias_norm(text)
    return {t[i:i+n] for i in range(len(t)-n+1)} if len(t) >= n else set()


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def extract_aliases_from_identity_content(text):
    aliases = []
    for label in ['project_aliases:', 'compact_aliases:', '사업명 alias:']:
        if label in text:
            aliases.extend(part.strip() for part in text.split(label, 1)[1].split('\n', 1)[0].split('/') if part.strip())
    return aliases


def build_alias_rows(records):
    rows, seen = [], set()
    for record in records:
        meta = record.get('metadata') if isinstance(record.get('metadata'), dict) else {}
        raw_aliases = [record.get('source_file'), meta.get('source_file'), meta.get('source_file_nfc'), record.get('doc_key'), meta.get('doc_key'), meta.get('canonical_doc_key'), meta.get('project_name'), meta.get('issuer')]
        if (record.get('fact_type') or meta.get('fact_type')) == 'document_identity':
            raw_aliases.extend(extract_aliases_from_identity_content(record.get('content', '')))
        for alias in raw_aliases:
            alias = nfc(alias)
            if len(alias_norm(alias)) < 3:
                continue
            doc_id = meta.get('canonical_doc_id') or meta.get('doc_id') or record.get('doc_id')
            key = (doc_id, alias_norm(alias))
            if key in seen:
                continue
            seen.add(key)
            rows.append({'doc_id': meta.get('doc_id') or record.get('doc_id'), 'canonical_doc_id': doc_id, 'source_file': meta.get('source_file') or record.get('source_file'), 'project_name': meta.get('project_name', ''), 'issuer': meta.get('issuer', ''), 'alias': alias, 'alias_2grams': alias_ngrams(alias, 2), 'alias_3grams': alias_ngrams(alias, 3)})
    return rows


ALIAS_ROWS = build_alias_rows(records)
print('alias rows:', len(ALIAS_ROWS))


def ngram_alias_lookup(question, limit=10, issuer=None):
    q2, q3 = alias_ngrams(question, 2), alias_ngrams(question, 3)

    if isinstance(issuer, dict) and '$in' in issuer:
        issuer = issuer.get('$in')

    if isinstance(issuer, (list, tuple, set)):
        issuer_set = {alias_norm(x) for x in issuer if str(x).strip()}
    elif issuer:
        issuer_set = {alias_norm(issuer)}
    else:
        issuer_set = set()

    scored = []
    for r in ALIAS_ROWS:
        if issuer_set:
            row_issuer = alias_norm(r.get('issuer', ''))
            if row_issuer not in issuer_set:
                continue

        score = 0.6 * jaccard(q2, r['alias_2grams']) + 0.4 * jaccard(q3, r['alias_3grams'])
        if score > 0:
            scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    results, seen = [], set()
    for score, row in scored:
        doc_id = row.get('canonical_doc_id') or row.get('doc_id')
        if not doc_id or doc_id in seen:
            continue

        seen.add(doc_id)
        item = {k: v for k, v in row.items() if not k.endswith('grams')}
        item['ngram_score'] = float(score)
        results.append(item)

        if len(results) >= limit:
            break

    return results

# %% [markdown] cell 18
# ## 7. Eval CSV 로드

# %% [code] cell 19
def load_eval_gold_csvs(eval_dir):
    frames = []
    for path in sorted(eval_dir.glob('*.csv')):
        df = pd.read_csv(path)
        df['source_eval_file'] = path.name
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f'No CSV files under {eval_dir}')
    out = pd.concat(frames, ignore_index=True)
    if 'id' not in out.columns:
        out['id'] = [f'Q{i+1:05d}' for i in range(len(out))]
    return out


def parse_doc_list_cell(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    try:
        raw = json.loads(text)
    except Exception:
        try:
            raw = ast.literal_eval(text)
        except Exception:
            raw = [part.strip() for part in re.split(r'[|;]', text) if part.strip()]
    if isinstance(raw, str):
        raw = [raw]
    docs = []
    for item in raw or []:
        doc = item.get('filename') or item.get('file_name') or item.get('source_file') or item.get('doc_id') if isinstance(item, dict) else item
        doc = normalize_doc_for_metric(doc)
        if doc:
            docs.append(doc)
    return list(dict.fromkeys(docs))


def infer_question_column(df):
    for col in ['question', 'query', 'input', 'user_question']:
        if col in df.columns:
            return col
    raise ValueError(list(df.columns))


def infer_ground_truth_doc_column(df):
    for col in ['ground_truth_docs', 'gt_docs', 'gold_docs', 'source_docs', 'answer_docs', 'ground_truth_doc', 'gt_doc', 'source_file', 'filename', 'doc_key', 'canonical_doc_key']:
        if col in df.columns:
            return col
    raise ValueError(list(df.columns))


def parse_metadata_filter_dict(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return {}
    if isinstance(value, dict):
        return value
    text = str(value).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def eval_filter_to_chroma_filter(row):
    raw = (
        parse_metadata_filter_dict(row.get('metadata_filter'))
        or parse_metadata_filter_dict(row.get('metadata_filter_dict'))
    )
    agency = raw.get('agency') or raw.get('issuer')

    if not agency or agency == '??':
        return None

    if isinstance(agency, (list, tuple, set)):
        agencies = [
            str(a).strip()
            for a in agency
            if str(a).strip() and str(a).strip() != '??'
        ]
        if len(agencies) == 1:
            return {'issuer': agencies[0]}
        if len(agencies) > 1:
            return {'issuer': {'$in': agencies}}
        return None

    if isinstance(agency, str) and '|' in agency:
        agencies = [
            a.strip()
            for a in agency.split('|')
            if a.strip() and a.strip() != '??'
        ]
        if len(agencies) == 1:
            return {'issuer': agencies[0]}
        if len(agencies) > 1:
            return {'issuer': {'$in': agencies}}
        return None

    agency = str(agency).strip()
    return {'issuer': agency} if agency and agency != '??' else None


eval_gold_df = load_eval_gold_csvs(EVAL_GOLD_DIR)
QUESTION_COL = infer_question_column(eval_gold_df)
GT_DOC_COL = infer_ground_truth_doc_column(eval_gold_df)
eval_gold_df['ground_truth_doc_list'] = eval_gold_df[GT_DOC_COL].apply(parse_doc_list_cell)
eval_gold_df = eval_gold_df[eval_gold_df['ground_truth_doc_list'].apply(bool)].reset_index(drop=True)
print('rows:', len(eval_gold_df), '| question:', QUESTION_COL, '| gt:', GT_DOC_COL)
display(eval_gold_df.head(3))

# %% [markdown] cell 20
# ## 8. Adaptive hybrid-first retrieval

# %% [code] cell 21
FOLLOWUP_MARKERS = ['그럼', '그러면', '그 사업', '그 기관', '거기', '해당', '위', '앞서', '이것', '그것', '방금', '아까', '이 사업', '그 문서']


def parse_history(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if isinstance(value, list):
        return value
    text = str(value).strip()
    if not text or text in {'[]', '{}'}:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            return []
    return parsed if isinstance(parsed, list) else []


def needs_history_rewrite(question, history):
    history = parse_history(history)
    if not history:
        return False
    q = nfc(question)
    if any(m in q for m in FOLLOWUP_MARKERS):
        return True
    has_anchor = any(k in q for k in ['기관', '사업', '시스템', '용역', '구축', '공사', '공단', '대학교', '예산', '제출서류'])
    return len(q) < 30 and not has_anchor


def simple_history_rewrite(question, history):
    history = parse_history(history)
    if not history:
        return question
    last = history[-1]
    return f"{last.get('question') or last.get('q') or ''}\n{last.get('answer') or last.get('a') or ''}\n후속 질문: {question}"


METADATA_PRIORITY_WEIGHT = 0.001

def infer_question_type(question):
    q = nfc(question)

    budget_terms = [
        '예산', '사업비', '사업금액', '금액', '얼마', '추정가격', '기초금액'
    ]
    comparison_terms = [
        '비교', '차이', '차액', '더 큰', '더 작은', '둘 중', '중 어느',
        '공통점', '차이점', '공통적으로', '각각', '각 사업별',
        '세 기관', '두 기관', '두 사업'
    ]
    purpose_terms = [
        '목적', '배경', '효과', '필요성', '왜', '무엇을 위해',
        '개선', '고도화', '목표', '영역', '범위', '요소'
    ]

    has_budget = any(k in q for k in budget_terms)
    has_comparison = any(k in q for k in comparison_terms)
    has_purpose = any(k in q for k in purpose_terms)

    # Mixed question: when purpose/scope/improvement and budget are asked together across docs,
    # route as comparison so detail facts are not removed by the budget allowlist.
    if has_budget and has_purpose and has_comparison:
        return 'comparison'

    # Pure budget amount/difference questions stay in the strict budget route.
    if has_budget:
        return 'budget'
    if any(k in q for k in ['제출서류', '제안서', '서류', '구비서류']):
        return 'submission_documents'
    if any(k in q for k in ['참가자격', '입찰자격', '자격요건', '면허', '실적', '공동수급']):
        return 'eligibility'
    if any(k in q for k in ['마감일', '마감', '기한', '입찰마감', '제출기한']):
        return 'deadline'
    if any(k in q for k in ['사업기간', '수행기간', '계약기간', '유지보수']):
        return 'duration'
    if has_purpose:
        return 'purpose'
    if has_comparison:
        return 'comparison'

    return 'general'



def metadata_priority(meta: dict[str, Any], question_type: str) -> int:
    fact_type = nfc(meta.get('fact_type'))
    answer_policy = nfc(meta.get('answer_policy'))
    chunk_type = nfc(meta.get('chunk_type'))
    score = 0

    if question_type == 'budget':
        if fact_type in {'project_budget', 'total_allocation'}:
            score += 60
        if to_bool(meta.get('budget_answer_enabled')):
            score += 50
        if answer_policy == 'allow_as_project_budget':
            score += 40
        if fact_type in {'threshold_budget', 'reference_amount', 'estimated_price', 'base_amount', 'payment_terms'}:
            score -= 35
        if answer_policy in {'route_only_not_final_answer', 'missing_project_budget'}:
            score -= 60

    elif question_type == 'submission_documents':
        if fact_type == 'submission_documents':
            score += 70
        if answer_policy == 'allow_as_submission_documents':
            score += 40

    elif question_type == 'eligibility':
        if fact_type == 'eligibility':
            score += 70
        if to_bool(meta.get('eligibility_answer_enabled')):
            score += 35

    elif question_type == 'deadline':
        if fact_type in {'bid_deadline', 'deadline_term'}:
            score += 70
        if answer_policy in {'allow_as_bid_deadline', 'allow_for_deadline_questions_only'}:
            score += 35

    elif question_type == 'duration':
        if fact_type in {'project_duration', 'maintenance_period', 'warranty_period'}:
            score += 60

    elif question_type == 'purpose':
        if fact_type in {'project_purpose_effect', 'project_background', 'project_scope', 'document_summary'}:
            score += 60

    elif question_type == 'comparison':
        if fact_type == 'document_summary':
            score += 40
        if fact_type in {'project_budget', 'project_duration', 'submission_documents', 'eligibility', 'project_purpose_effect', 'project_scope'}:
             score += 35
        if fact_type == 'document_identity':
             score += 25

    if chunk_type == 'fact_candidates':
        score += 10
    return score


def apply_metadata_rerank(question, candidates):
    qtype = infer_question_type(question)
    out = []
    for row in candidates:
        item = dict(row)
        meta = item.get('metadata') or {}
        base = item.get('rrf_score', item.get('similarity', item.get('sparse_score', 0))) or 0
        item['metadata_priority'] = metadata_priority(meta, qtype)
        item['final_score'] = float(base) + item['metadata_priority'] * 0.001
        out.append(item)
    return sorted(out, key=lambda r: r.get('final_score', 0), reverse=True)


def normalize_candidate_list(candidates):
    """
    candidates가 list[dict], tuple, dict 형태로 들어와도
    apply_metadata_rerank가 처리할 수 있는 list[dict]로 정리합니다.
    """
    if isinstance(candidates, tuple):
        candidates = candidates[0]

    if isinstance(candidates, dict):
        for key in ['selected', 'candidates', 'contexts', 'results']:
            if key in candidates:
                candidates = candidates[key]
                break
        else:
            candidates = [candidates]

    if candidates is None:
        return []

    if not isinstance(candidates, list):
        candidates = list(candidates)

    normalized = []
    for item in candidates:
        if isinstance(item, dict):
            normalized.append(item)

    return normalized


def select_contexts_for_llm(
    question: str,
    candidates,
    max_contexts: int = MAX_CONTEXTS,
) -> tuple[list[dict[str, Any]], str]:
    question_type = infer_question_type(question)

    candidates = normalize_candidate_list(candidates)
    reranked = apply_metadata_rerank(question, candidates)

    if question_type == 'budget':
        # Budget questions never fall back to duration/summary/identity/threshold evidence.
        # Keep one safe budget fact per document first so multi-doc budget questions do not collapse to one document.
        return select_budget_docwise(reranked, max_contexts), question_type

    if question_type == 'general':
        detail, summary = [], []
        for c in reranked:
            fact_type = nfc((c.get('metadata') or {}).get('fact_type'))
            if fact_type in GENERAL_LOW_VALUE_FACT_TYPES:
                summary.append(c)
            else:
                detail.append(c)

        selected = detail[:max(0, max_contexts - 1)] + summary[:1]
        return selected[:max_contexts], question_type

    blocked = ANSWER_BLOCKED_FACT_TYPES.get(question_type, set())
    filtered = [
        c for c in reranked
        if nfc((c.get('metadata') or {}).get('fact_type')) not in blocked
    ]

    return filtered[:max_contexts], question_type


# %% [code] cell 22
QUESTION_FACT_TYPES = {
    'budget': {
        'project_budget',
        'total_allocation',
        'estimated_price',
        'base_amount',
        'threshold_budget',
        'payment_terms',
        'reference_amount',
        'document_summary',
        'document_identity',
    },
    'submission_documents': {
        'submission_documents',
        'submission_logistics',
        'table',
        'document_summary',
    },
    'eligibility': {
        'eligibility',
        'business_type',
        'threshold_budget',
        'document_summary',
    },
    'deadline': {
        'bid_deadline',
        'deadline_term',
        'submission_logistics',
        'document_summary',
    },
    'duration': {
        'project_duration',
        'maintenance_period',
        'warranty_period',
        'deadline_term',
        'document_summary',
    },
    'purpose': {
        'project_purpose_effect',
        'project_background',
        'project_scope',
        'document_summary',
        'requirements',
    },
    'comparison': {
        'document_identity',
        'document_summary',
        'project_budget',
        'total_allocation',
        'project_duration',
        'submission_documents',
        'eligibility',
        'project_purpose_effect',
        'project_scope',
        'business_type',
    },
    'general': {
        'document_summary',
        'document_identity',
        'project_purpose_effect',
        'project_background',
        'project_scope',
        'requirements',
        'business_type',
        'project_budget',
        'total_allocation',
        'project_duration',
        'submission_documents',
        'submission_logistics',
        'eligibility',
        'deadline_term',
        'bid_deadline',
        'maintenance_period',
        'warranty_period',
    },
}

# Retrieval candidates are broad; final answer contexts block risky fact types by question type.
ANSWER_BLOCKED_FACT_TYPES = {
    'budget': {
        'threshold_budget',
        'payment_terms',
        'reference_amount',
        'base_amount',
        'estimated_price',
        'document_summary',
        'document_identity',
        'project_duration',
        'deadline_term',
        'maintenance_period',
        'warranty_period',
    },
    'eligibility': {
        'project_budget',
        'total_allocation',
    },
    'general': set(),
}

BUDGET_FINAL_FACT_TYPES = {'project_budget', 'total_allocation'}

def _candidate_doc_key(cand):
    meta = cand.get('metadata') or {}
    return meta.get('canonical_doc_id') or meta.get('doc_id') or meta.get('source_file') or cand.get('chunk_id')


def is_safe_budget_candidate(cand):
    meta = cand.get('metadata') or {}
    return (
        nfc(meta.get('fact_type')) in BUDGET_FINAL_FACT_TYPES
        and to_bool(meta.get('budget_answer_enabled'))
        and nfc(meta.get('answer_policy')) == 'allow_as_project_budget'
    )


def select_budget_docwise(candidates, max_contexts=MAX_CONTEXTS):
    selected, seen_docs = [], set()

    # First pass: one safe budget fact per document, preserving reranked order.
    for cand in candidates:
        if not is_safe_budget_candidate(cand):
            continue
        doc_key = _candidate_doc_key(cand)
        if doc_key in seen_docs:
            continue
        seen_docs.add(doc_key)
        selected.append(cand)
        if len(selected) >= max_contexts:
            return selected

    # Second pass: allow additional safe budget facts only after document coverage is maximized.
    seen_chunks = {c.get('chunk_id') for c in selected}
    for cand in candidates:
        if not is_safe_budget_candidate(cand):
            continue
        cid = cand.get('chunk_id')
        if cid in seen_chunks:
            continue
        seen_chunks.add(cid)
        selected.append(cand)
        if len(selected) >= max_contexts:
            break

    return selected


def rrf_merge(result_lists, k=60):
    scores, items, sources = {}, {}, defaultdict(set)
    for results in result_lists:
        for rank, item in enumerate(results, 1):
            cid = item.get('chunk_id')
            if not cid: continue
            scores[cid] = scores.get(cid, 0) + 1/(k+rank)
            items.setdefault(cid, dict(item))
            sources[cid].add(item.get('retriever', 'unknown'))
    merged = []
    for cid, item in items.items():
        item = dict(item)
        item['rrf_score'] = scores[cid]
        item['retrievers'] = ','.join(sorted(sources[cid]))
        merged.append(item)
    return sorted(merged, key=lambda r: r['rrf_score'], reverse=True)


def dense_confident(ranked):
    if not ranked: return False
    top = ranked[:10]
    docs = [(r.get('metadata') or {}).get('canonical_doc_id') or (r.get('metadata') or {}).get('doc_id') for r in top]
    return len({d for d in docs if d}) <= 5 and ranked[0].get('final_score', 0) > 0.20


def needs_ngram_rescue(question, dense_ranked, issuer):
    hits = ngram_alias_lookup(question, 3, issuer=issuer)

    if hits and hits[0].get('ngram_score', 0) >= 0.10:
        return True

    docs = [(r.get('metadata') or {}).get('canonical_doc_id') or (r.get('metadata') or {}).get('doc_id')
        for r in dense_ranked[:10]]
    return len({d for d in docs if d}) >= 7


def infer_needed_fact_types(question):
    facts = set(QUESTION_FACT_TYPES.get(infer_question_type(question), QUESTION_FACT_TYPES['general']))
    if any(k in question for k in ['목적', '배경', '효과', '필요', '왜']):
        facts.update({'project_purpose_effect', 'project_background', 'project_scope', 'document_summary'})
    facts.add('document_identity')
    return facts


def backfill_doc_facts(doc_ids, question, per_doc=2, where=None):
    needed = infer_needed_fact_types(question)
    out = []

    for doc_id in doc_ids:
        doc_out, seen = [], set()

        for record in records:
            meta = clean_metadata(record)

            if not metadata_matches_filter(meta, where):
                continue

            if doc_id not in {meta.get('canonical_doc_id'), meta.get('doc_id')}:
                continue

            if meta.get('fact_type') not in needed:
                continue

            cid = record.get('chunk_id')
            if not cid or cid in seen:
                continue

            seen.add(cid)
            doc_out.append({
                'rank': len(doc_out) + 1,
                'chunk_id': cid,
                'text': record.get('content', ''),
                'metadata': meta,
                'retriever': 'ngram_doc_backfill',
            })

        out.extend(apply_metadata_rerank(question, doc_out)[:per_doc])

    return apply_metadata_rerank(question, out)

GENERAL_DETAIL_FACT_TYPES = {
    'requirements',
    'project_scope',
    'project_purpose_effect',
    'project_background',
    'submission_documents',
    'submission_logistics',
    'eligibility',
    'business_type',
    'project_duration',
    'maintenance_period',
    'warranty_period',
    'bid_deadline',
    'deadline_term',
}

GENERAL_LOW_VALUE_FACT_TYPES = {
    'document_identity',
    'document_summary',
}


def _doc_id_from_candidate(cand):
    meta = cand.get('metadata') or {}
    return meta.get('canonical_doc_id') or meta.get('doc_id')


def top_doc_ids_from_candidates(candidates, limit=3):
    seen, doc_ids = set(), []
    for cand in candidates:
        doc_id = _doc_id_from_candidate(cand)
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        doc_ids.append(doc_id)
        if len(doc_ids) >= limit:
            break
    return doc_ids


def expand_general_detail_chunks(question, candidates, where=None, doc_limit=3, per_doc=4):
    if infer_question_type(question) != 'general':
        return candidates, []

    ranked = apply_metadata_rerank(question, normalize_candidate_list(candidates))
    doc_ids = top_doc_ids_from_candidates(ranked, limit=doc_limit)
    if not doc_ids:
        return candidates, []

    doc_set = set(doc_ids)
    existing = {c.get('chunk_id') for c in ranked if c.get('chunk_id')}
    expanded = []

    for doc_id in doc_ids:
        doc_out, seen = [], set()
        for record in records:
            meta = clean_metadata(record)
            if not metadata_matches_filter(meta, where):
                continue
            if doc_id not in {meta.get('canonical_doc_id'), meta.get('doc_id')}:
                continue

            fact_type = nfc(meta.get('fact_type'))
            if fact_type in GENERAL_LOW_VALUE_FACT_TYPES:
                continue

            cid = record.get('chunk_id')
            if not cid or cid in existing or cid in seen:
                continue

            seen.add(cid)
            item = {
                'rank': len(doc_out) + 1,
                'chunk_id': cid,
                'text': record.get('content', ''),
                'metadata': meta,
                'retriever': 'general_doc_detail_expand',
            }
            if fact_type in GENERAL_DETAIL_FACT_TYPES:
                item['general_detail_boost'] = 0.08
            else:
                item['general_detail_boost'] = 0.03
            doc_out.append(item)

        doc_ranked = apply_metadata_rerank(question, doc_out)
        for item in doc_ranked:
            item['final_score'] = float(item.get('final_score', 0) or 0) + float(item.get('general_detail_boost', 0) or 0)
        doc_ranked.sort(key=lambda r: r.get('final_score', 0), reverse=True)
        expanded.extend(doc_ranked[:per_doc])

    return candidates + expanded, expanded


# %% [code] cell 23
def select_contexts(question, candidates, max_contexts=MAX_CONTEXTS):
    qtype = infer_question_type(question)
    seen_chunks, seen_doc_fact, scored = set(), set(), []

    for cand in candidates:
        meta = cand.get('metadata') or {}
        cid = cand.get('chunk_id')
        if not cid or cid in seen_chunks:
            continue
        seen_chunks.add(cid)
        key = (meta.get('canonical_doc_id') or meta.get('doc_id'), meta.get('fact_type'), meta.get('section_path'))
        scored.append((metadata_priority(meta, qtype), cand.get('final_score', cand.get('rrf_score', 0)), key, cand))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    ordered = [cand for _, _, _, cand in scored]

    if qtype == 'budget':
        return select_budget_docwise(ordered, max_contexts)

    if qtype == 'general':
        detail = [c for c in ordered if nfc((c.get('metadata') or {}).get('fact_type')) not in GENERAL_LOW_VALUE_FACT_TYPES]
        summary = [c for c in ordered if nfc((c.get('metadata') or {}).get('fact_type')) in GENERAL_LOW_VALUE_FACT_TYPES]
        return (detail[:max(0, max_contexts - 1)] + summary[:1])[:max_contexts]

    blocked = ANSWER_BLOCKED_FACT_TYPES.get(qtype, set())
    selected = []
    for cand in ordered:
        meta = cand.get('metadata') or {}
        key = (meta.get('canonical_doc_id') or meta.get('doc_id'), meta.get('fact_type'), meta.get('section_path'))
        if nfc(meta.get('fact_type')) in blocked:
            continue
        if key in seen_doc_fact and len(selected) >= 2:
            continue
        seen_doc_fact.add(key)
        selected.append(cand)
        if len(selected) >= max_contexts:
            break
    return selected


def money_block(meta: dict[str, Any], question_type: str = 'general') -> str:
    fact_type = nfc(meta.get('fact_type'))
    answer_policy = nfc(meta.get('answer_policy'))

    # 예산 질문에서는 예산으로 답하면 안 되는 금액을 아예 context 금액 블록에서 제외
    if question_type == 'budget':
        is_budget_safe = (
            fact_type in BUDGET_FINAL_FACT_TYPES
            and to_bool(meta.get('budget_answer_enabled'))
            and answer_policy == 'allow_as_project_budget'
        )
        if not is_budget_safe:
            return ''

    amount_raw = first_nonempty(
        meta.get('money_raw'),
        meta.get('amount_raw'),
        meta.get('final_budget'),
    )
    amount_krw = first_nonempty(
        meta.get('money_krw'),
        meta.get('amount_krw'),
        meta.get('final_budget_krw'),
    )
    role = first_nonempty(
        meta.get('money_role'),
        meta.get('budget_value_role'),
        meta.get('amount_type'),
        meta.get('fact_type'),
    )

    if not amount_raw and not amount_krw:
        return ''

    return '\n'.join([
        '금액 정보:',
        f'- 원문 금액: {amount_raw}',
        f'- 정규화 금액: {format_krw(amount_krw) if amount_krw else ""}',
        f'- 금액 역할: {role}',
        f'- 예산 답변 사용 가능: {meta.get("budget_answer_enabled", "")}',
    ])


def build_llm_context(
    selected: list[dict[str, Any]],
    question_type: str = 'general',
    max_chars_per_context: int = 2200,
) -> str:
    blocks = []

    for i, cand in enumerate(selected, start=1):
        meta = cand.get('metadata') or {}
        text = nfc(cand.get('text', ''))[:max_chars_per_context]
        mblock = money_block(meta, question_type=question_type)

        block = f"""
[근거 {i}]
문서: {meta.get('source_file', '')}
발주기관: {meta.get('issuer', '')}
사업명: {meta.get('project_name', '')}
섹션: {meta.get('section_path', meta.get('section_type', ''))}
유형: {meta.get('chunk_type', '')} / {meta.get('fact_type', '')}
답변정책: {meta.get('answer_policy', '')}
검색점수: {cand.get('similarity', cand.get('final_score', ''))}
{mblock}

본문:
{text}
""".strip()

        blocks.append(block)

    return '\n\n'.join(blocks)


def require_issuer_filter(chroma_where):
    if not chroma_where or 'issuer' not in chroma_where:
        raise ValueError('agency/issuer filter is required for retrieval')

    issuer = chroma_where.get('issuer')
    if isinstance(issuer, dict) and '$in' in issuer:
        issuers = [x for x in issuer.get('$in', []) if str(x).strip()]
        if not issuers:
            raise ValueError('agency/issuer filter is empty')
        return issuers

    if not str(issuer).strip():
        raise ValueError('agency/issuer filter is empty')

    return issuer


def adaptive_retrieve(question, history=None, max_contexts=MAX_CONTEXTS, chroma_where=None):
    issuer_filter = require_issuer_filter(chroma_where)
    route, search_query = [], question
    if needs_history_rewrite(question, history):
        search_query = simple_history_rewrite(question, history)
        route.append('history_rewrite')

    # Production default: agency/issuer hard filter + dense/sparse hybrid RRF.
    dense = dense_retrieve(search_query, DENSE_K, where=chroma_where)
    sparse = sparse_retrieve(search_query, SPARSE_K, where=chroma_where)
    result_lists = [dense, sparse]
    route.append('hybrid')

    alias_hits = []
    doc_ids = []
    dense_ranked = apply_metadata_rerank(search_query, dense)
    if needs_ngram_rescue(search_query, dense_ranked, issuer=issuer_filter):
        alias_hits = ngram_alias_lookup(search_query, 10, issuer=issuer_filter)
        doc_ids = list(dict.fromkeys(
            h.get('canonical_doc_id') or h.get('doc_id')
            for h in alias_hits
            if h.get('ngram_score', 0) >= 0.10 and (h.get('canonical_doc_id') or h.get('doc_id'))
        ))[:3]
        if doc_ids:
            backfilled = backfill_doc_facts(doc_ids, search_query, per_doc=2, where=chroma_where)
            result_lists.append(backfilled)
            route.append('ngram_backfill')

    merged = rrf_merge(result_lists)
    detail_expanded = []
    if infer_question_type(search_query) == 'general':
        merged, detail_expanded = expand_general_detail_chunks(
            search_query,
            merged,
            where=chroma_where,
            doc_limit=3,
            per_doc=4,
        )
        if detail_expanded:
            route.append('general_detail_expand')

    ranked = apply_metadata_rerank(search_query, merged)
    selected = select_contexts(search_query, ranked, max_contexts)
    return selected, build_llm_context(selected), {
        'route': route,
        'search_query': search_query,
        'alias_hits': alias_hits[:5],
        'backfill_doc_ids': doc_ids,
        'general_detail_expanded': len(detail_expanded),
        'chroma_where': chroma_where,
        'issuer_filter': issuer_filter,
    }

# %% [code] cell 24
# Retrieval stage debugger
# Usage examples:
#   debug_retrieval_flow(eval_gold_df.iloc[14])
#   debug_retrieval_flow("??", chroma_where={"issuer": "???"})

def _candidate_doc_id(cand):
    meta = cand.get('metadata') or {}
    return meta.get('canonical_doc_id') or meta.get('doc_id')


def _summarize_candidates(candidates, limit=10):
    rows = []
    for i, cand in enumerate((candidates or [])[:limit], 1):
        meta = cand.get('metadata') or {}
        rows.append({
            'rank': cand.get('rank', i),
            'doc_id': meta.get('canonical_doc_id') or meta.get('doc_id'),
            'source_file': meta.get('source_file'),
            'issuer': meta.get('issuer'),
            'fact_type': meta.get('fact_type'),
            'section_path': meta.get('section_path'),
            'retriever': cand.get('retrievers') or cand.get('retriever'),
            'distance': cand.get('distance'),
            'similarity': cand.get('similarity'),
            'rrf_score': cand.get('rrf_score'),
            'final_score': cand.get('final_score'),
            'metadata_priority': cand.get('metadata_priority'),
        })
    return pd.DataFrame(rows)


def _summarize_alias_hits(hits, limit=10):
    rows = []
    for i, hit in enumerate((hits or [])[:limit], 1):
        rows.append({
            'rank': i,
            'doc_id': hit.get('canonical_doc_id') or hit.get('doc_id'),
            'source_file': hit.get('source_file'),
            'issuer': hit.get('issuer'),
            'project_name': hit.get('project_name'),
            'alias': hit.get('alias'),
            'ngram_score': hit.get('ngram_score'),
        })
    return pd.DataFrame(rows)


def _get_question_from_debug_input(row_or_question):
    if isinstance(row_or_question, str):
        return row_or_question
    if isinstance(row_or_question, dict):
        return row_or_question.get(QUESTION_COL) or row_or_question.get('question') or row_or_question.get('??')
    return row_or_question.get(QUESTION_COL) if hasattr(row_or_question, 'get') else str(row_or_question)


def _get_history_from_debug_input(row_or_question, history=None):
    if history is not None:
        return history
    if isinstance(row_or_question, str):
        return None
    return row_or_question.get('history', None) if hasattr(row_or_question, 'get') else None


def _get_where_from_debug_input(row_or_question, chroma_where=None):
    if chroma_where is not None:
        return chroma_where
    if isinstance(row_or_question, str):
        return None
    if hasattr(row_or_question, 'get'):
        return eval_filter_to_chroma_filter(row_or_question)
    return None


def debug_retrieval_flow(row_or_question, history=None, chroma_where=None, max_contexts=MAX_CONTEXTS, show_context=False):
    question = _get_question_from_debug_input(row_or_question)
    history = _get_history_from_debug_input(row_or_question, history=history)
    chroma_where = _get_where_from_debug_input(row_or_question, chroma_where=chroma_where)
    issuer_filter = require_issuer_filter(chroma_where)

    route, search_query = [], question
    if needs_history_rewrite(question, history):
        search_query = simple_history_rewrite(question, history)
        route.append('history_rewrite')

    dense = dense_retrieve(search_query, DENSE_K, where=chroma_where)
    dense_ranked = apply_metadata_rerank(search_query, dense)
    dense_ok = dense_confident(dense_ranked)

    alias_hits = ngram_alias_lookup(search_query, 10, issuer=issuer_filter)
    ngram_needed = needs_ngram_rescue(search_query, dense_ranked, issuer=issuer_filter)
    doc_ids = list(dict.fromkeys(
        h.get('canonical_doc_id') or h.get('doc_id')
        for h in alias_hits
        if h.get('ngram_score', 0) >= 0.10 and (h.get('canonical_doc_id') or h.get('doc_id'))
    ))[:3]
    backfilled = backfill_doc_facts(doc_ids, search_query, per_doc=2, where=chroma_where) if doc_ids else []

    sparse = sparse_retrieve(search_query, SPARSE_K, where=chroma_where)
    hybrid_ranked = apply_metadata_rerank(search_query, rrf_merge([dense, sparse]))
    ngram_ranked = apply_metadata_rerank(search_query, rrf_merge([dense, backfilled])) if backfilled else dense_ranked

    selected, context_text, debug = adaptive_retrieve(
        question,
        history,
        max_contexts,
        chroma_where=chroma_where,
    )

    retrieved_docs = retrieved_docs_from_selected(selected, max_contexts) if 'retrieved_docs_from_selected' in globals() else []
    gold_docs = row_or_question.get('ground_truth_doc_list') if hasattr(row_or_question, 'get') else None
    metrics = compute_retrieval_metrics(gold_docs, retrieved_docs) if gold_docs and 'compute_retrieval_metrics' in globals() else None

    print('QUESTION:', question)
    print('QUESTION_TYPE:', infer_question_type(question))
    print('CHROMA_WHERE:', chroma_where)
    print('ISSUER_FILTER:', issuer_filter)
    print('HISTORY_REWRITE:', bool(route))
    print('SEARCH_QUERY:', search_query[:1000])
    print('DENSE_CONFIDENT:', dense_ok)
    print('NGRAM_NEEDED:', ngram_needed)
    print('BACKFILL_DOC_IDS:', doc_ids)
    print('FINAL_ROUTE:', '>'.join(debug.get('route', [])))
    if gold_docs is not None:
        print('GOLD_DOCS:', gold_docs)
        print('RETRIEVED_DOCS:', retrieved_docs)
        print('METRICS:', metrics)

    print('\n[DENSE TOP]')
    display(_summarize_candidates(dense_ranked, 10))

    print('\n[ALIAS HITS WITH ISSUER FILTER]')
    display(_summarize_alias_hits(alias_hits, 10))

    print('\n[BACKFILLED]')
    display(_summarize_candidates(backfilled, 10))

    print('\n[HYBRID FALLBACK TOP]')
    display(_summarize_candidates(hybrid_ranked, 10))

    print('\n[NGRAM MERGED TOP]')
    display(_summarize_candidates(ngram_ranked, 10))

    print('\n[FINAL SELECTED]')
    display(_summarize_candidates(selected, max_contexts))

    if show_context:
        print('\n[CONTEXT PREVIEW]')
        print(context_text[:5000])

    return {
        'question': question,
        'search_query': search_query,
        'chroma_where': chroma_where,
        'issuer_filter': issuer_filter,
        'dense_confident': dense_ok,
        'ngram_needed': ngram_needed,
        'alias_hits': alias_hits,
        'backfill_doc_ids': doc_ids,
        'dense': dense_ranked,
        'backfilled': backfilled,
        'hybrid_ranked': hybrid_ranked,
        'ngram_ranked': ngram_ranked,
        'selected': selected,
        'debug': debug,
        'metrics': metrics,
    }

# %% [markdown] cell 25
# ## 9. Retrieval 지표

# %% [code] cell 26
def retrieved_docs_from_selected(selected, top_k=EVAL_METRIC_K):
    docs, seen = [], set()
    for row in selected:
        meta = row.get('metadata') or {}
        doc = normalize_doc_for_metric(meta.get('source_file') or meta.get('source_file_nfc') or meta.get('canonical_doc_key') or meta.get('doc_key') or meta.get('doc_id'))
        if not doc or doc in seen: continue
        seen.add(doc); docs.append(doc)
        if len(docs) >= top_k: break
    return docs


def compute_retrieval_metrics(gt_docs, retrieved_docs, top_k=EVAL_METRIC_K):
    gt = {normalize_doc_for_metric(d) for d in gt_docs if normalize_doc_for_metric(d)}
    pred = [normalize_doc_for_metric(d) for d in retrieved_docs[:top_k] if normalize_doc_for_metric(d)]
    if not gt:
        return {'hit_rate': math.nan, 'mrr': math.nan, 'ndcg': math.nan, 'recall': math.nan}
    rel = [1 if d in gt else 0 for d in pred]
    hit = 1.0 if any(rel) else 0.0
    first = next((i+1 for i, x in enumerate(rel) if x), None)
    mrr = 1/first if first else 0.0
    dcg = sum(x/math.log2(i+2) for i, x in enumerate(rel))
    idcg = sum(1/math.log2(i+2) for i in range(min(len(gt), top_k)))
    return {'hit_rate': hit, 'mrr': mrr, 'ndcg': dcg/idcg if idcg else math.nan, 'recall': len(set(pred)&gt)/len(gt)}


def evaluate_adaptive_retrieval(df, limit=20):
    work = df.head(limit).copy() if limit else df.copy()
    rows = []
    for _, row in tqdm(work.iterrows(), total=len(work), desc='adaptive_retrieval'):
        chroma_where = eval_filter_to_chroma_filter(row)
        selected, _, debug = adaptive_retrieve(row[QUESTION_COL], row.get('history', None), EVAL_METRIC_K, chroma_where=chroma_where)
        retrieved = retrieved_docs_from_selected(selected, EVAL_METRIC_K)
        metrics = compute_retrieval_metrics(row['ground_truth_doc_list'], retrieved)
        rows.append({'id': row.get('id',''), 'type': row.get('type',''), 'difficulty': row.get('difficulty',''), 'question': row[QUESTION_COL], 'ground_truth_docs': json.dumps(row['ground_truth_doc_list'], ensure_ascii=False), 'retrieved_docs': json.dumps(retrieved, ensure_ascii=False), **metrics, 'route': '>'.join(debug.get('route', [])), 'chroma_where': json.dumps(chroma_where, ensure_ascii=False) if chroma_where else '', 'source_eval_file': row.get('source_eval_file','')})
    detail = pd.DataFrame(rows)
    summary = pd.DataFrame([{'strategy': 'adaptive_dense_first', 'questions': len(detail), 'hit_rate': detail.hit_rate.mean(), 'mrr': detail.mrr.mean(), 'ndcg': detail.ndcg.mean(), 'recall': detail.recall.mean()}])
    return summary, detail


adaptive_summary_df, adaptive_detail_df = evaluate_adaptive_retrieval(eval_gold_df, limit=30)
display(adaptive_summary_df)
display(adaptive_detail_df.head())

# %% [markdown] cell 27
# ## 10. LLM 로드

# %% [code] cell 28
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, pipeline

LOAD_LLM = True
USE_4BIT = True

if LOAD_LLM:
    tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL_NAME, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    kwargs = {'device_map': 'auto', 'trust_remote_code': True}
    if USE_4BIT:
        kwargs['quantization_config'] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16, bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True)
    else:
        kwargs['torch_dtype'] = torch.float16 if torch.cuda.is_available() else torch.float32
    llm_model = AutoModelForCausalLM.from_pretrained(LLM_MODEL_NAME, **kwargs)
    text_gen = pipeline('text-generation', model=llm_model, tokenizer=tokenizer, max_new_tokens=512, temperature=0.0, do_sample=False, return_full_text=False)
    print('LLM loaded:', LLM_MODEL_NAME)
else:
    text_gen = None

# %% [markdown] cell 29
# ## 11. 답변 생성

# %% [code] cell 30
def generate_answer(question: str, context: str, max_new_tokens: int = 512) -> str:

    system_prompt = """
      당신은 RFP 문서 검색 QA 어시스턴트입니다.
      제공된 근거(context)에 있는 정보만 사용하세요.
      내부 필드명, 정책명, fact_type, budget_answer_enabled, answer_policy, G2B manual lookup 같은 시스템 용어를 답변에 절대 노출하지 마세요.
      context에 없는 URL, 기관명, 공고번호, 금액을 만들지 마세요.

      사업 예산 금액은 근거에 명시된 경우에만 답하세요.
      기초금액, 추정가격, 참가자격 기준금액, 입찰마감일, 사업기간은 사업 예산으로 말하지 마세요.

      예산 금액이 없고 context에 나라장터 공고번호가 있으면:
      - 예산 금액은 현재 근거에서 확인되지 않는다고 말하세요.
      - 확인된 공고번호를 그대로 제시하세요.
      - 나라장터 웹사이트에서 해당 공고번호로 확인하라고 안내하세요.
      - 단, context에 없는 URL은 만들지 말고 https://www.g2b.go.kr/index.jsp 만 제시하세요.

      예산 금액도 없고 공고번호도 없으면:
      "문서 근거가 부족합니다."라고 간단히 답하세요.

      답변은 3문장 이내로 작성하세요.
      마지막 줄에 "출처: ..." 형식으로 context의 문서명 또는 확인 경로만 표시하세요.
""".strip()

    user_prompt = f"""
[질문]
{question}

[근거]
{context}

[답변]
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=7000,
    ).to(llm_model.device)

    outputs = llm_model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        repetition_penalty=1.15, #0.08에서 수정.
        pad_token_id=tokenizer.eos_token_id,
        eos_token_id=tokenizer.eos_token_id,
    )

    # 핵심: 입력 prompt 부분을 잘라내고 새로 생성된 답변 토큰만 decode
    generated_ids = outputs[0][inputs["input_ids"].shape[-1]:]

    answer = tokenizer.decode(
        generated_ids,
        skip_special_tokens=True,
    ).strip()

    return answer

# %% [code] cell 31
row = eval_gold_df.iloc[0]
question = row[QUESTION_COL]

chroma_where = eval_filter_to_chroma_filter(row)
raw_result = adaptive_retrieve(question, chroma_where=chroma_where)

selected, question_type = select_contexts_for_llm(
    question,
    raw_result,
    max_contexts=MAX_CONTEXTS,
)

context = build_llm_context(
    selected,
    question_type=question_type,
)

answer = generate_answer(
    question=question,
    context=context,
)

print("QUESTION:", question)
print("QUESTION_TYPE:", question_type)
print("CHROMA_WHERE:", chroma_where)
print("ANSWER:")
print(answer)
print("\nCONTEXT PREVIEW:")
print(context[:3000])

# %% [markdown] cell 32
# ## 12. Eval subset 답변 생성 + 저장

# %% [code] cell 33
def selected_to_ragas_contexts(selected):
    contexts = []

    for cand in selected:
        if isinstance(cand, dict):
            text = cand.get("text") or cand.get("context") or cand.get("page_content") or ""
            meta = cand.get("metadata") or {}
            source = cand.get("filename") or meta.get("source_file") or meta.get("doc_key") or ""
        else:
            text = str(cand)
            source = ""

        text = nfc(text).strip()
        source = nfc(source).strip()
        if not text:
            continue

        if source:
            contexts.append(f"[source: {source}]\n{text}")
        else:
            contexts.append(text)

    return contexts


def get_reference_from_eval_row(row):
    """Return the reference answer text for RAGAS if the eval row has one.

    ground_truth_docs is a list of gold document names, not an answer reference.
    If none of the answer-like columns exists, this returns an empty string.
    """
    for col in [
        "ground_truth_answer",
        "reference",
        "ground_truth",
        "gold_answer",
        "expected_answer",
        "answer",
    ]:
        value = row.get(col, "")
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        text = nfc(value).strip()
        if text and text.lower() not in {"nan", "none", "null"}:
            return text
    return ""

# %% [code] cell 34
def to_eval_retrieved_contexts(selected):
    output = []

    for rank, cand in enumerate(selected, 1):
        meta = cand.get("metadata") or {}

        output.append({
            "rank": rank,
            "filename": (
                meta.get("source_file")
                or meta.get("doc_key")
                or meta.get("doc_id")
                or cand.get("filename")
            ),
            "doc_id": meta.get("doc_id") or cand.get("doc_id"),
            "chunk_id": cand.get("chunk_id") or meta.get("chunk_id"),
            "score": (
                cand.get("final_score")
                or cand.get("similarity")
                or cand.get("rrf_score")
                or cand.get("sparse_score")
            ),
            "text": cand.get("text") or cand.get("context") or cand.get("page_content") or "",
            "metadata": meta,
        })

    return output

# %% [code] cell 35

G2B_SERVICE_KEY = "여기에 key를 입력하세요"
G2B_BID_PUBLIC_BASE = 'https://apis.data.go.kr/1230000/ad/BidPublicInfoService'

# Search endpoints by bid domain. These are broad discovery calls.
G2B_SERVICE_SEARCH_ENDPOINTS = [
    'getBidPblancListInfoServcPPSSrch',
    'getBidPblancListInfoThngPPSSrch',
    'getBidPblancListInfoCnstwkPPSSrch',
    'getBidPblancListInfoFrgcptPPSSrch',
    'getBidPblancListInfoEtcPPSSrch',
]

# Detail/list endpoints sometimes expose amount fields that the PPSSrch endpoints omit.
G2B_SERVICE_DETAIL_ENDPOINTS = [
    'getBidPblancListInfoServc',
    'getBidPblancListInfoThng',
    'getBidPblancListInfoCnstwk',
    'getBidPblancListInfoFrgcpt',
    'getBidPblancListInfoEtc',
]

# Basis amount endpoints are useful evidence, but they are not project budgets.
G2B_BASIS_AMOUNT_ENDPOINTS = [
    'getBidPblancListInfoServcBsisAmount',
    'getBidPblancListInfoThngBsisAmount',
    'getBidPblancListInfoCnstwkBsisAmount',
]

G2B_AMOUNT_FIELDS = [
    # Final-answer-safe project budget candidates.
    ('asignBdgtAmt', 'allocated_budget'),
    ('asignBdgtAmount', 'allocated_budget'),
    ('bdgtAmt', 'allocated_budget'),
    ('budgetAmt', 'allocated_budget'),
    ('totBdgtAmt', 'allocated_budget'),
    ('totalBdgtAmt', 'allocated_budget'),
    ('allocationBudgetAmt', 'allocated_budget'),
    ('assignedBudgetAmt', 'allocated_budget'),

    # Secondary evidence only. These should not become final project_budget by themselves.
    ('presmptPrce', 'estimated_price'),
    ('presmptPrice', 'estimated_price'),
    ('presmptPrceAmt', 'estimated_price'),
    ('presumptPrce', 'estimated_price'),
    ('rsrvtnPrce', 'estimated_price'),
    ('estmtPrce', 'estimated_price'),
    ('estimatedPrice', 'estimated_price'),

    ('bsisAmt', 'base_amount'),
    ('bssamt', 'base_amount'),
    ('bssAmt', 'base_amount'),
    ('baseAmt', 'base_amount'),
    ('basisAmount', 'base_amount'),

    ('evlBssAmt', 'reference_amount'),
    ('evlBssAmount', 'reference_amount'),
    ('refAmt', 'reference_amount'),
    ('referenceAmt', 'reference_amount'),
]

G2B_ROLE_TO_FACT_POLICY = {
    'allocated_budget': ('project_budget', 'allow_as_project_budget', True),
    'estimated_price': ('estimated_price', 'allow_as_secondary_budget_only', False),
    'base_amount': ('base_amount', 'allow_as_secondary_budget_only', False),
    'reference_amount': ('reference_amount', 'allow_as_secondary_budget_only', False),
}


def get_g2b_service_key():
    key = os.environ.get('G2B_SERVICE_KEY') or os.environ.get('NARA_API_KEY')
    if key:
        return key
    try:
        from google.colab import userdata
        return userdata.get('G2B_SERVICE_KEY') or userdata.get('NARA_API_KEY')
    except Exception:
        return None


def compact_for_match(value):
    return re.sub(r'[^\uAC00-\uD7A3a-zA-Z0-9]', '', nfc(value)).lower()


def clean_project_query(value, max_len=80):
    text = nfc(value)
    text = re.sub(r'\.(hwp|hwpx|pdf|docx?|xlsx?)$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[_\[\]\(\){}<>"\'`]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_len]


def iter_g2b_items(payload):
    try:
        body = payload.get('response', {}).get('body', {})
        items = body.get('items', [])
    except Exception:
        return []
    if items is None:
        return []
    if isinstance(items, dict):
        items = items.get('item', [items])
    if isinstance(items, dict):
        items = [items]
    return items if isinstance(items, list) else []


def g2b_api_get(endpoint, params, timeout=12, num_rows=20):
    key = get_g2b_service_key()
    if not key:
        return {'ok': False, 'endpoint': endpoint, 'error': 'missing G2B_SERVICE_KEY', 'items': []}
    url = f'{G2B_BID_PUBLIC_BASE}/{endpoint}'
    req_params = {'serviceKey': key, 'type': 'json', 'pageNo': '1', 'numOfRows': str(num_rows)}
    req_params.update({k: v for k, v in params.items() if v not in (None, '')})
    try:
        resp = requests.get(url, params=req_params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
        return {
            'ok': True,
            'endpoint': endpoint,
            'url': url,
            'params': {k: v for k, v in req_params.items() if k != 'serviceKey'},
            'items': iter_g2b_items(payload),
            'raw': payload,
        }
    except Exception as exc:
        return {
            'ok': False,
            'endpoint': endpoint,
            'url': url,
            'params': {k: v for k, v in req_params.items() if k != 'serviceKey'},
            'error': str(exc),
            'items': [],
        }


def g2b_title_score(question, issuer, project_name, source_file, item):
    title = nfc(item.get('bidNtceNm') or item.get('ntceNm') or item.get('bidNm') or item.get('prdctClsfcNoNm'))
    inst = nfc(item.get('ntceInsttNm') or item.get('dminsttNm') or item.get('orderInsttNm'))
    query = ' '.join(x for x in [project_name, source_file, question] if x)
    title_score = difflib.SequenceMatcher(None, compact_for_match(query), compact_for_match(title)).ratio()
    issuer_score = max(
        difflib.SequenceMatcher(None, compact_for_match(issuer), compact_for_match(inst)).ratio() if inst else 0,
        1.0 if issuer and issuer in inst else 0,
    )
    return title_score * 0.7 + issuer_score * 0.3


def g2b_notice_key(item):
    bid_no = nfc(item.get('bidNtceNo') or item.get('ntceNo') or item.get('bidNo') or '')
    bid_ord = nfc(item.get('bidNtceOrd') or item.get('ntceOrd') or '')
    return bid_no, bid_ord


def split_g2b_notice_no(value):
    value = nfc(value).strip()
    value = re.sub(r'[^A-Za-z0-9\-]', '', value)
    if '-' in value:
        bid_no, bid_ord = value.split('-', 1)
        return bid_no.strip(), bid_ord.strip()
    return value, ''


def normalize_g2b_notice_value(value):
    bid_no, bid_ord = split_g2b_notice_no(value)
    if not bid_no:
        return ''
    return f'{bid_no}-{bid_ord}' if bid_ord else bid_no


def extract_g2b_notice_candidates_from_text(text):
    text = nfc(text)
    patterns = [
        r'G2B[^A-Za-z0-9]{0,20}([A-Za-z0-9][A-Za-z0-9\-]{7,29})',
        r'\uC785\uCC30\s*\uACF5\uACE0\s*\uBC88\uD638\s*[:?]?\s*([A-Za-z0-9\-]{8,30})',
        r'\uACF5\uACE0\s*\uBC88\uD638\s*[:?]?\s*([A-Za-z0-9\-]{8,30})',
        r'\b(20\d{8,12}-\d{1,3})\b',
        r'\b(20\d{8,12})\b',
        r'\b(R\d{2}[A-Z]{2}\d{8,12}(?:-\d{1,3})?)\b',
    ]
    out = []
    for pat in patterns:
        for match in re.finditer(pat, text):
            value = normalize_g2b_notice_value(match.group(1))
            if value and value not in out:
                out.append(value)
    return out


def extract_g2b_notice_candidates_from_rows(rows, limit=20):
    out = []
    for row in rows or []:
        meta = row.get('metadata') or {}
        text_parts = [
            row.get('text', ''),
            meta.get('g2b_notice_id', ''),
            meta.get('final_notice_id', ''),
            meta.get('notice_id', ''),
            meta.get('bidNtceNo', ''),
            meta.get('source_file', ''),
            meta.get('project_name', ''),
        ]
        for text in text_parts:
            for value in extract_g2b_notice_candidates_from_text(text):
                if value not in out:
                    out.append(value)
                    if len(out) >= limit:
                        return out
    return out


def g2b_direct_lookup_items(notice_values, calls, max_notices=6):
    items = []
    seen_params = set()
    for notice in notice_values[:max_notices]:
        bid_no, bid_ord = split_g2b_notice_no(notice)
        if not bid_no:
            continue
        base_params = {'inqryDiv': '2', 'bidNtceNo': bid_no}
        if bid_ord:
            base_params['bidNtceOrd'] = bid_ord

        for endpoint in G2B_SERVICE_DETAIL_ENDPOINTS + G2B_BASIS_AMOUNT_ENDPOINTS:
            key = (endpoint, tuple(sorted(base_params.items())))
            if key in seen_params:
                continue
            seen_params.add(key)
            result = g2b_api_get(endpoint, base_params, num_rows=10)
            call_info = {
                k: result.get(k)
                for k in ['ok', 'endpoint', 'url', 'params', 'error']
                if result.get(k) is not None
            }
            call_info['item_count'] = len(result.get('items', []))
            calls.append(call_info)
            for item in result.get('items', []):
                item = dict(item)
                item['_direct_notice_query'] = notice
                items.append(item)
    return items


def parse_g2b_amount(raw):
    if raw in (None, ''):
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        krw = int(float(re.sub(r'[^0-9.]', '', text)))
    except Exception:
        return None
    return krw if krw > 0 else None


def g2b_amounts_from_item(item):
    amounts, seen = [], set()
    for key, role in G2B_AMOUNT_FIELDS:
        raw = item.get(key)
        krw = parse_g2b_amount(raw)
        if krw is None:
            continue
        dedup_key = (role, krw, key)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        fact_type, answer_policy, budget_enabled = G2B_ROLE_TO_FACT_POLICY[role]
        amounts.append({
            'raw': raw,
            'krw': krw,
            'role': role,
            'fact_type': fact_type,
            'answer_policy': answer_policy,
            'budget_answer_enabled': budget_enabled,
            'field': key,
        })
    return amounts


# Backward-compatible helper name used in earlier experiments.
def g2b_budget_amount_from_item(item):
    amounts = g2b_amounts_from_item(item)
    return amounts[0] if amounts else None


def g2b_expand_notice_items(seed_items, calls, max_seed_items=5):
    expanded = []
    seen_notice = set()
    for seed in seed_items[:max_seed_items]:
        bid_no, bid_ord = g2b_notice_key(seed)
        if not bid_no or bid_no in seen_notice:
            continue
        seen_notice.add(bid_no)
        params = {'bidNtceNo': bid_no}
        if bid_ord:
            params['bidNtceOrd'] = bid_ord

        for endpoint in G2B_SERVICE_DETAIL_ENDPOINTS + G2B_BASIS_AMOUNT_ENDPOINTS:
            result = g2b_api_get(endpoint, params, num_rows=10)
            call_info = {
                k: result.get(k)
                for k in ['ok', 'endpoint', 'url', 'params', 'error']
                if result.get(k) is not None
            }
            call_info['item_count'] = len(result.get('items', []))
            calls.append(call_info)
            expanded.extend(result.get('items', []))
    return expanded


def g2b_search_budget_candidates(question, raw_candidates, chroma_where=None, max_items=5):
    issuer_value = (chroma_where or {}).get('issuer')
    if isinstance(issuer_value, dict):
        issuer = next(iter(issuer_value.get('$in', []) or []), '')
    else:
        issuer = issuer_value or ''
    issuer = nfc(issuer)

    metas = [(c.get('metadata') or {}) for c in raw_candidates or []]
    project_name = next((nfc(m.get('project_name')) for m in metas if m.get('project_name')), '')
    source_file = next((nfc(m.get('source_file')) for m in metas if m.get('source_file')), '')
    query_name = clean_project_query(project_name or source_file or question)

    calls, seed_items = [], []

    # 1) Strongest path: if retrieved contexts contain a G2B notice number,
    # query by bidNtceNo/bidNtceOrd before fuzzy title search.
    notice_values = extract_g2b_notice_candidates_from_rows(raw_candidates, limit=12)
    if notice_values:
        calls.append({
            'ok': True,
            'endpoint': 'local_notice_extractor',
            'notice_candidates': notice_values,
        })
        seed_items.extend(g2b_direct_lookup_items(notice_values, calls, max_notices=6))

    # 2) Fallback path: title/issuer discovery search. This is weaker and may miss
    # spacing, private-institution, or self-issued RFP documents.
    if not seed_items:
        params = {
            'inqryDiv': '1',
            'inqryBgnDt': '199501010000',
            'inqryEndDt': '202612312359',
            'bidNtceNm': query_name,
        }
        if issuer:
            params['dminsttNm'] = issuer

        for endpoint in G2B_SERVICE_SEARCH_ENDPOINTS:
            result = g2b_api_get(endpoint, params)
            call_info = {
                k: result.get(k)
                for k in ['ok', 'endpoint', 'url', 'params', 'error']
                if result.get(k) is not None
            }
            call_info['item_count'] = len(result.get('items', []))
            calls.append(call_info)
            seed_items.extend(result.get('items', []))

    # Re-query top matched notices through detail and basis-amount endpoints.
    scored_seeds = sorted(
        seed_items,
        key=lambda item: 1.25 if item.get('_direct_notice_query') else g2b_title_score(question, issuer, project_name, source_file, item),
        reverse=True,
    )
    all_items = list(seed_items)
    all_items.extend(g2b_expand_notice_items(scored_seeds, calls, max_seed_items=5))

    candidates, seen = [], set()
    for item in all_items:
        score = 1.25 if item.get('_direct_notice_query') else g2b_title_score(question, issuer, project_name, source_file, item)
        bid_no, bid_ord = g2b_notice_key(item)
        if not bid_no and item.get('_direct_notice_query'):
            bid_no, bid_ord = split_g2b_notice_no(item.get('_direct_notice_query'))
        for amount in g2b_amounts_from_item(item):
            dedup_key = (bid_no, bid_ord, amount['role'], amount['krw'], amount['field'])
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            candidates.append((score, item, amount))

    # Final-answer-safe amounts first, direct notice hits second, then title score.
    candidates.sort(
        key=lambda x: (
            1 if x[2]['role'] == 'allocated_budget' else 0,
            1 if x[1].get('_direct_notice_query') else 0,
            x[0],
            x[2]['krw'],
        ),
        reverse=True,
    )
    calls.append({
        'ok': True,
        'endpoint': 'local_g2b_candidate_summary',
        'seed_item_count': len(seed_items),
        'all_item_count': len(all_items),
        'amount_candidate_count': len(candidates),
        'allocated_budget_count': sum(1 for _, _, amount in candidates if amount.get('role') == 'allocated_budget'),
    })
    return candidates[:max_items], calls


def build_g2b_budget_contexts(question, raw_candidates, chroma_where=None, max_contexts=MAX_CONTEXTS):
    # Ask for more API candidates than final contexts so secondary values are visible in debug.
    candidates, calls = g2b_search_budget_candidates(
        question,
        raw_candidates,
        chroma_where=chroma_where,
        max_items=max(max_contexts * 4, 12),
    )

    contexts, secondary_amounts = [], []
    for rank, (score, item, amount) in enumerate(candidates, start=1):
        source_file = nfc(item.get('bidNtceNm') or item.get('ntceNm') or item.get('bidNm'))
        issuer = nfc(item.get('ntceInsttNm') or item.get('dminsttNm') or item.get('orderInsttNm') or (chroma_where or {}).get('issuer'))
        bid_no, bid_ord = g2b_notice_key(item)

        amount_debug = {
            'rank': rank,
            'role': amount['role'],
            'fact_type': amount['fact_type'],
            'amount_krw': amount['krw'],
            'amount_raw': str(amount['raw']),
            'amount_field': amount['field'],
            'source_file': source_file,
            'issuer': issuer,
            'g2b_notice_id': bid_no,
            'g2b_match_score': float(score),
            'final_answer_safe': bool(amount['budget_answer_enabled']),
        }

        # Keep non-allocated values in debug only. They are useful for diagnosis,
        # but should not be allowed as final project budgets.
        if amount['role'] != 'allocated_budget' or not amount['budget_answer_enabled']:
            secondary_amounts.append(amount_debug)
            continue

        text = (
            f'G2B API lookup result: project budget candidate {format_krw(amount["krw"])}. '
            f'bid title: {source_file}. '
            f'bid notice no: {bid_no}. '
            f'amount field: {amount["field"]}. '
            f'amount role: {amount["role"]}.'
        )
        contexts.append({
            'rank': len(contexts) + 1,
            'chunk_id': f'g2b_budget::{bid_no or rank}::{bid_ord}::{amount["field"]}',
            'text': text,
            'metadata': {
                'source_file': source_file,
                'issuer': issuer,
                'project_name': source_file,
                'section_path': 'G2B API > BidPublicInfoService',
                'chunk_type': 'external_api',
                'fact_type': 'project_budget',
                'amount_raw': format_krw(amount['krw']),
                'amount_krw': amount['krw'],
                'amount_type': 'project_budget',
                'budget_value_role': amount['role'],
                'budget_answer_enabled': True,
                'answer_policy': 'allow_as_project_budget',
                'retrieval_role': 'g2b_budget_fallback',
                'g2b_match_score': float(score),
                'g2b_notice_id': bid_no,
                'g2b_notice_ord': bid_ord,
                'g2b_amount_field': amount['field'],
            },
            'retriever': 'g2b_budget_tool',
            'final_score': 1.0 + float(score),
        })
        if len(contexts) >= max_contexts:
            break

    if secondary_amounts:
        calls.append({
            'ok': True,
            'endpoint': 'local_amount_role_classifier',
            'secondary_amounts': secondary_amounts[:20],
        })

    return contexts[:max_contexts], calls

def build_g2b_manual_lookup_contexts(question, raw_candidates, chroma_where=None, max_contexts=MAX_CONTEXTS):
    """Create a user-facing fallback context when G2B OpenAPI returns no structured item.

    This does not fabricate a budget. It preserves the notice number found in the
    retrieved RFP context and guides the user to verify it on the G2B website.
    """
    notice_values = extract_g2b_notice_candidates_from_rows(raw_candidates, limit=max_contexts)
    contexts = []

    issuer_value = (chroma_where or {}).get('issuer', '')
    if isinstance(issuer_value, dict):
        issuer_value = ', '.join(str(x) for x in issuer_value.get('$in', []) or [])
    issuer_value = nfc(issuer_value)

    for notice in notice_values:
        bid_no, bid_ord = split_g2b_notice_no(notice)
        text = (
            f'G2B notice number found in retrieved RFP context: {notice}.\n'
            f'The G2B OpenAPI returned no structured budget item for this notice number.\n'
            f'Please verify the original notice manually on the G2B website.\n'
            f'G2B website: https://www.g2b.go.kr/index.jsp\n'
            f'Search keyword: {notice}\n'
            f'Parsed bidNtceNo: {bid_no}\n'
            f'Parsed bidNtceOrd: {bid_ord}'
        )
        contexts.append({
            'rank': len(contexts) + 1,
            'chunk_id': f'g2b_manual_lookup::{notice}',
            'text': text,
            'metadata': {
                'source_file': 'G2B manual lookup',
                'issuer': issuer_value,
                'project_name': '',
                'section_path': 'G2B manual lookup',
                'chunk_type': 'external_manual_lookup',
                'fact_type': 'document_identity',
                'answer_policy': 'route_only_not_final_answer',
                'budget_answer_enabled': False,
                'answer_allowed_question_types': 'routing,document_lookup,general_reference',
                'answer_blocked_question_types': 'budget',
                'retrieval_role': 'g2b_manual_lookup',
                'g2b_notice_id': notice,
                'bidNtceNo': bid_no,
                'bidNtceOrd': bid_ord,
                'g2b_url': 'https://www.g2b.go.kr/index.jsp',
            },
            'retriever': 'g2b_manual_lookup',
            'final_score': 0.25,
        })
        if len(contexts) >= max_contexts:
            break

    return contexts, {
        'manual_lookup_notice_candidates': notice_values,
        'manual_lookup_context_count': len(contexts),
        'manual_lookup_url': 'https://www.g2b.go.kr/index.jsp',
    }



# %% [code] cell 36
class RagGraphState(TypedDict, total=False):
    row: Any
    question: str
    history: Any
    reference: str
    chroma_where: dict
    issuer_filter: Any
    question_type: str
    route: list
    search_query: str
    dense: list
    sparse: list
    dense_ranked: list
    result_lists: list
    merged: list
    ranked: list
    alias_hits: list
    backfill_doc_ids: list
    backfilled: list
    general_detail_expanded: list
    comparison_expanded: list
    g2b_contexts: list
    g2b_calls: list
    manual_lookup_contexts: list
    manual_lookup_debug: dict
    selected_raw: list
    selected: list
    context_text: str
    answer: str
    latency_sec: float
    pipeline_latency_sec: float
    raw_retrieved: list
    raw_retrieval_metrics: dict
    retrieved: list
    metrics: dict
    debug: dict


def _append_node(state: RagGraphState, name: str, **updates) -> RagGraphState:
    debug = dict(state.get('debug') or {})
    debug['graph_nodes'] = debug.get('graph_nodes', []) + [name]
    debug.update(updates.pop('debug_updates', {}))
    return {**state, **updates, 'debug': debug}


def _candidate_doc_ids(candidates, limit=5):
    seen, out = set(), []
    for cand in candidates or []:
        meta = cand.get('metadata') or {}
        doc_id = meta.get('canonical_doc_id') or meta.get('doc_id')
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            out.append(doc_id)
        if len(out) >= limit:
            break
    return out


def graph_prepare_node(state: RagGraphState) -> RagGraphState:
    row = state['row']
    q = row[QUESTION_COL]
    chroma_where = eval_filter_to_chroma_filter(row)
    issuer_filter = require_issuer_filter(chroma_where)
    return _append_node(
        state,
        'prepare',
        question=q,
        history=row.get('history', None),
        reference=get_reference_from_eval_row(row),
        chroma_where=chroma_where,
        issuer_filter=issuer_filter,
        route=[],
        debug_updates={
            'chroma_where': chroma_where,
            'issuer_filter': issuer_filter,
        },
    )


def graph_history_rewrite_node(state: RagGraphState) -> RagGraphState:
    question = state['question']
    history = state.get('history', None)
    route = list(state.get('route') or [])
    if needs_history_rewrite(question, history):
        search_query = simple_history_rewrite(question, history)
        route.append('history_rewrite')
        rewritten = True
    else:
        search_query = question
        rewritten = False
    return _append_node(
        state,
        'history_rewrite',
        search_query=search_query,
        route=route,
        debug_updates={'history_rewritten': rewritten, 'search_query': search_query},
    )


def graph_classify_node(state: RagGraphState) -> RagGraphState:
    qtype = infer_question_type(state.get('search_query') or state['question'])
    return _append_node(
        state,
        'classify_question',
        question_type=qtype,
        debug_updates={'question_type': qtype},
    )


def graph_dense_node(state: RagGraphState) -> RagGraphState:
    dense = dense_retrieve(state['search_query'], DENSE_K, where=state['chroma_where'])
    dense_ranked = apply_metadata_rerank(state['search_query'], dense)
    return _append_node(
        state,
        'dense_retrieve',
        dense=dense,
        dense_ranked=dense_ranked,
        debug_updates={'dense_count': len(dense)},
    )


def graph_sparse_node(state: RagGraphState) -> RagGraphState:
    sparse = sparse_retrieve(state['search_query'], SPARSE_K, where=state['chroma_where'])
    return _append_node(
        state,
        'sparse_retrieve',
        sparse=sparse,
        debug_updates={'sparse_count': len(sparse)},
    )


def graph_merge_hybrid_node(state: RagGraphState) -> RagGraphState:
    route = list(state.get('route') or [])
    route.append('hybrid')
    result_lists = [state.get('dense', []), state.get('sparse', [])]
    merged = rrf_merge(result_lists)
    return _append_node(
        state,
        'rrf_merge_hybrid',
        route=route,
        result_lists=result_lists,
        merged=merged,
        debug_updates={'merged_count': len(merged), 'route': route},
    )


def graph_assess_ngram_node(state: RagGraphState) -> RagGraphState:
    need = needs_ngram_rescue(
        state['search_query'],
        state.get('dense_ranked', []),
        issuer=state.get('issuer_filter'),
    )
    return _append_node(state, 'assess_ngram', debug_updates={'ngram_needed': need}, ngram_needed=need)


def route_ngram(state: RagGraphState) -> str:
    return 'ngram_backfill' if state.get('ngram_needed') else 'maybe_general_detail'


def graph_ngram_backfill_node(state: RagGraphState) -> RagGraphState:
    alias_hits = ngram_alias_lookup(state['search_query'], 10, issuer=state.get('issuer_filter'))
    doc_ids = list(dict.fromkeys(
        h.get('canonical_doc_id') or h.get('doc_id')
        for h in alias_hits
        if h.get('ngram_score', 0) >= 0.10 and (h.get('canonical_doc_id') or h.get('doc_id'))
    ))[:3]
    backfilled = backfill_doc_facts(doc_ids, state['search_query'], per_doc=2, where=state['chroma_where']) if doc_ids else []
    route = list(state.get('route') or [])
    result_lists = list(state.get('result_lists') or [])
    if backfilled:
        result_lists.append(backfilled)
        route.append('ngram_backfill')
    return _append_node(
        state,
        'ngram_backfill',
        alias_hits=alias_hits,
        backfill_doc_ids=doc_ids,
        backfilled=backfilled,
        result_lists=result_lists,
        route=route,
        debug_updates={
            'alias_hits': alias_hits[:5],
            'backfill_doc_ids': doc_ids,
            'backfilled_count': len(backfilled),
            'route': route,
        },
    )


def graph_merge_after_ngram_node(state: RagGraphState) -> RagGraphState:
    merged = rrf_merge(state.get('result_lists') or [])
    return _append_node(
        state,
        'rrf_merge_after_ngram',
        merged=merged,
        debug_updates={'merged_count_after_ngram': len(merged)},
    )


def route_general_detail(state: RagGraphState) -> str:
    return 'general_detail_expand' if state.get('question_type') == 'general' else 'maybe_comparison_expand'


def graph_general_detail_node(state: RagGraphState) -> RagGraphState:
    merged, detail_expanded = expand_general_detail_chunks(
        state['search_query'],
        state.get('merged', []),
        where=state['chroma_where'],
        doc_limit=3,
        per_doc=4,
    )
    route = list(state.get('route') or [])
    if detail_expanded:
        route.append('general_detail_expand')
    return _append_node(
        state,
        'general_detail_expand',
        merged=merged,
        general_detail_expanded=detail_expanded,
        route=route,
        debug_updates={'general_detail_expanded': len(detail_expanded), 'route': route},
    )


def route_comparison_expand(state: RagGraphState) -> str:
    return 'comparison_expand' if state.get('question_type') == 'comparison' else 'rank_candidates'


def graph_comparison_expand_node(state: RagGraphState) -> RagGraphState:
    doc_ids = _candidate_doc_ids(state.get('merged', []), limit=5)
    expanded = backfill_doc_facts(doc_ids, state['search_query'], per_doc=2, where=state['chroma_where']) if doc_ids else []
    merged = rrf_merge([state.get('merged', []), expanded]) if expanded else state.get('merged', [])
    route = list(state.get('route') or [])
    if expanded:
        route.append('comparison_expand')
    return _append_node(
        state,
        'comparison_expand',
        comparison_expanded=expanded,
        merged=merged,
        route=route,
        debug_updates={'comparison_expanded': len(expanded), 'route': route},
    )


def graph_rank_candidates_node(state: RagGraphState) -> RagGraphState:
    ranked = apply_metadata_rerank(state['search_query'], state.get('merged', []))
    selected_raw = select_contexts(state['search_query'], ranked, MAX_CONTEXTS)
    raw_retrieved = retrieved_docs_from_selected(ranked, EVAL_METRIC_K)
    raw_metrics = compute_retrieval_metrics(state['row']['ground_truth_doc_list'], raw_retrieved)
    return _append_node(
        state,
        'rank_candidates',
        ranked=ranked,
        selected_raw=selected_raw,
        raw_retrieved=raw_retrieved,
        raw_retrieval_metrics=raw_metrics,
        debug_updates={
            'ranked_count': len(ranked),
            'selected_raw_count': len(selected_raw),
            'raw_retrieved_docs': raw_retrieved,
            'raw_retrieval_metrics': raw_metrics,
        },
    )


def graph_final_select_node(state: RagGraphState) -> RagGraphState:
    selected, question_type = select_contexts_for_llm(
        state['question'],
        state.get('selected_raw', []),
        max_contexts=MAX_CONTEXTS,
    )
    return _append_node(
        state,
        'select_qna_contexts',
        selected=selected,
        question_type=question_type,
        debug_updates={
            'selected_context_count': len(selected),
            'selected_fact_types': [(c.get('metadata') or {}).get('fact_type') for c in selected],
        },
    )


def graph_budget_fallback_check_node(state: RagGraphState) -> RagGraphState:
    missing_safe_budget = state.get('question_type') == 'budget' and not state.get('selected')
    return _append_node(
        state,
        'budget_fallback_check',
        debug_updates={'missing_safe_budget_context': missing_safe_budget},
    )


def route_budget_tool(state: RagGraphState) -> str:
    if state.get('question_type') == 'budget' and not state.get('selected'):
        return 'g2b_budget_lookup'
    return 'build_context'


def graph_g2b_budget_lookup_node(state: RagGraphState) -> RagGraphState:
    g2b_contexts, calls = build_g2b_budget_contexts(
        state['question'],
        state.get('ranked', []) or state.get('selected_raw', []),
        chroma_where=state.get('chroma_where'),
        max_contexts=MAX_CONTEXTS,
    )
    selected = select_budget_docwise(g2b_contexts, MAX_CONTEXTS) if g2b_contexts else []
    return _append_node(
        state,
        'g2b_budget_lookup',
        g2b_contexts=g2b_contexts,
        g2b_calls=calls,
        selected=selected,
        debug_updates={
            'g2b_budget_lookup_called': True,
            'g2b_context_count': len(g2b_contexts),
            'g2b_calls': calls,
            'selected_context_count': len(selected),
            'selected_fact_types': [(c.get('metadata') or {}).get('fact_type') for c in selected],
        },
    )


def route_after_g2b_budget(state: RagGraphState) -> str:
    if state.get('question_type') == 'budget' and not state.get('selected'):
        return 'g2b_manual_lookup'
    return 'build_context'


def graph_g2b_manual_lookup_node(state: RagGraphState) -> RagGraphState:
    manual_contexts, manual_debug = build_g2b_manual_lookup_contexts(
        state['question'],
        state.get('ranked', []) or state.get('selected_raw', []),
        chroma_where=state.get('chroma_where'),
        max_contexts=min(MAX_CONTEXTS, 3),
    )

    # This context is intentionally not a project_budget fact. It guides manual
    # verification when the API and local budget extraction cannot provide a safe amount.
    selected = manual_contexts if manual_contexts else []

    return _append_node(
        state,
        'g2b_manual_lookup',
        manual_lookup_contexts=manual_contexts,
        manual_lookup_debug=manual_debug,
        selected=selected,
        debug_updates={
            'g2b_manual_lookup_called': True,
            'manual_lookup_context_count': len(manual_contexts),
            'manual_lookup_debug': manual_debug,
            'selected_context_count': len(selected),
            'selected_fact_types': [(c.get('metadata') or {}).get('fact_type') for c in selected],
        },
    )


def graph_build_context_node(state: RagGraphState) -> RagGraphState:
    context_text = build_llm_context(
        state.get('selected', []),
        question_type=state.get('question_type', 'general'),
    )
    return _append_node(
        state,
        'build_context',
        context_text=context_text,
        debug_updates={'context_chars': len(context_text)},
    )


def graph_generate_node(state: RagGraphState) -> RagGraphState:
    start = time.perf_counter()
    answer = generate_answer(question=state['question'], context=state.get('context_text', ''))
    latency_sec = time.perf_counter() - start
    return _append_node(
        state,
        'generate_answer',
        answer=answer,
        latency_sec=latency_sec,
        debug_updates={'latency_sec': latency_sec},
    )


def graph_evaluate_node(state: RagGraphState) -> RagGraphState:
    retrieved = retrieved_docs_from_selected(state.get('selected', []), EVAL_METRIC_K)
    metrics = compute_retrieval_metrics(state['row']['ground_truth_doc_list'], retrieved)
    return _append_node(
        state,
        'evaluate',
        retrieved=retrieved,
        metrics=metrics,
        debug_updates={
            'final_retrieved_docs': retrieved,
            'final_retrieval_metrics': metrics,
        },
    )


def build_rag_langgraph():
    graph = StateGraph(RagGraphState)
    graph.add_node('prepare', graph_prepare_node)
    graph.add_node('history_rewrite', graph_history_rewrite_node)
    graph.add_node('classify_question', graph_classify_node)
    graph.add_node('dense_retrieve', graph_dense_node)
    graph.add_node('sparse_retrieve', graph_sparse_node)
    graph.add_node('rrf_merge_hybrid', graph_merge_hybrid_node)
    graph.add_node('assess_ngram', graph_assess_ngram_node)
    graph.add_node('ngram_backfill', graph_ngram_backfill_node)
    graph.add_node('rrf_merge_after_ngram', graph_merge_after_ngram_node)
    graph.add_node('general_detail_expand', graph_general_detail_node)
    graph.add_node('general_detail_router', lambda state: _append_node(state, 'general_detail_router'))
    graph.add_node('comparison_expand', graph_comparison_expand_node)
    graph.add_node('comparison_router', lambda state: _append_node(state, 'comparison_router'))
    graph.add_node('rank_candidates', graph_rank_candidates_node)
    graph.add_node('select_qna_contexts', graph_final_select_node)
    graph.add_node('budget_fallback_check', graph_budget_fallback_check_node)
    graph.add_node('g2b_budget_lookup', graph_g2b_budget_lookup_node)
    graph.add_node('g2b_manual_lookup', graph_g2b_manual_lookup_node)
    graph.add_node('build_context', graph_build_context_node)
    graph.add_node('generate_answer', graph_generate_node)
    graph.add_node('evaluate', graph_evaluate_node)

    graph.set_entry_point('prepare')
    graph.add_edge('prepare', 'history_rewrite')
    graph.add_edge('history_rewrite', 'classify_question')
    graph.add_edge('classify_question', 'dense_retrieve')
    graph.add_edge('dense_retrieve', 'sparse_retrieve')
    graph.add_edge('sparse_retrieve', 'rrf_merge_hybrid')
    graph.add_edge('rrf_merge_hybrid', 'assess_ngram')
    graph.add_conditional_edges(
        'assess_ngram',
        route_ngram,
        {
            'ngram_backfill': 'ngram_backfill',
            'maybe_general_detail': 'general_detail_router',
        },
    )
    graph.add_edge('ngram_backfill', 'rrf_merge_after_ngram')
    graph.add_edge('rrf_merge_after_ngram', 'general_detail_router')
    graph.add_conditional_edges(
        'general_detail_router',
        route_general_detail,
        {
            'general_detail_expand': 'general_detail_expand',
            'maybe_comparison_expand': 'comparison_router',
        },
    )
    graph.add_edge('general_detail_expand', 'comparison_router')
    graph.add_conditional_edges(
        'comparison_router',
        route_comparison_expand,
        {
            'comparison_expand': 'comparison_expand',
            'rank_candidates': 'rank_candidates',
        },
    )
    graph.add_edge('comparison_expand', 'rank_candidates')
    graph.add_edge('rank_candidates', 'select_qna_contexts')
    graph.add_edge('select_qna_contexts', 'budget_fallback_check')
    graph.add_conditional_edges(
        'budget_fallback_check',
        route_budget_tool,
        {
            'g2b_budget_lookup': 'g2b_budget_lookup',
            'build_context': 'build_context',
        },
    )
    graph.add_conditional_edges(
        'g2b_budget_lookup',
        route_after_g2b_budget,
        {
            'g2b_manual_lookup': 'g2b_manual_lookup',
            'build_context': 'build_context',
        },
    )
    graph.add_edge('g2b_manual_lookup', 'build_context')
    graph.add_edge('build_context', 'generate_answer')
    graph.add_edge('generate_answer', 'evaluate')
    graph.add_edge('evaluate', END)
    return graph.compile()


RAG_LANGGRAPH = build_rag_langgraph()


def run_langgraph_rag_on_row(row):
    start = time.perf_counter()
    state = RAG_LANGGRAPH.invoke({'row': row})
    pipeline_latency_sec = time.perf_counter() - start
    debug = dict(state.get('debug') or {})
    debug['pipeline_latency_sec'] = pipeline_latency_sec
    debug['route'] = state.get('route', [])
    state['pipeline_latency_sec'] = pipeline_latency_sec
    state['debug'] = debug
    return state


def run_adaptive_llm_on_eval(df, output_jsonl_path, limit=5):
    work = df.head(limit).copy() if limit else df.copy()
    output_jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    ragas_rows = []

    with output_jsonl_path.open('w', encoding='utf-8') as f:
        for _, row in tqdm(work.iterrows(), total=len(work), desc='detailed_langgraph_rag'):
            state = run_langgraph_rag_on_row(row)

            q = state['question']
            reference = state.get('reference', '')
            chroma_where = state.get('chroma_where')
            selected = state.get('selected', [])
            question_type = state.get('question_type', infer_question_type(q))
            answer = state.get('answer', '')
            debug = state.get('debug', {})
            metrics = state.get('metrics', {})
            raw_metrics = state.get('raw_retrieval_metrics', {})
            latency_sec = state.get('latency_sec')
            pipeline_latency_sec = state.get('pipeline_latency_sec')

            payload = {
                'id': row.get('id', ''),
                'type': row.get('type', ''),
                'difficulty': row.get('difficulty', ''),
                'question': q,
                'question_type': question_type,
                'answer': answer,
                'reference': reference,
                'latency_sec': latency_sec,
                'pipeline_latency_sec': pipeline_latency_sec,
                'retrieved_contexts': to_eval_retrieved_contexts(selected),
                'retriever_strategy': 'detailed_langgraph_hybrid_first_newQnA_agency_filter',
                'chroma_where': chroma_where,
                'retriever_debug': debug,
                'g2b_contexts': state.get('g2b_contexts', []),
                'g2b_calls': state.get('g2b_calls', []),
                'ground_truth_docs': row['ground_truth_doc_list'],
                'raw_retrieved_docs': state.get('raw_retrieved', []),
                'raw_retrieval_metrics': raw_metrics,
                'retrieval_metrics': metrics,
            }

            ragas_rows.append({
                'id': row.get('id', ''),
                'user_input': q,
                'response': answer,
                'retrieved_contexts': selected_to_ragas_contexts(selected),
                'reference': reference,
                'latency_sec': latency_sec,
                'pipeline_latency_sec': pipeline_latency_sec,
                'ground_truth_docs': row.get('ground_truth_doc_list', []),
                'raw_retrieved_docs': state.get('raw_retrieved', []),
                'raw_retrieval_metrics': raw_metrics,
                'final_retrieval_metrics': metrics,
                'type': row.get('type', ''),
                'difficulty': row.get('difficulty', ''),
                'chroma_where': chroma_where,
                'g2b_contexts': state.get('g2b_contexts', []),
                'g2b_calls': state.get('g2b_calls', []),
            })

            f.write(json.dumps(payload, ensure_ascii=False) + '\n')

            rows.append({
                'id': row.get('id', ''),
                'type': row.get('type', ''),
                'difficulty': row.get('difficulty', ''),
                'question_type': question_type,
                'question': q,
                'answer': answer,
                'reference': reference,
                'latency_sec': latency_sec,
                'pipeline_latency_sec': pipeline_latency_sec,
                'raw_hit_rate': raw_metrics.get('hit_rate'),
                'raw_mrr': raw_metrics.get('mrr'),
                'raw_ndcg': raw_metrics.get('ndcg'),
                'raw_recall': raw_metrics.get('recall'),
                **metrics,
                'route': '>'.join(debug.get('route', [])) if isinstance(debug, dict) else '',
                'graph_nodes': '>'.join(debug.get('graph_nodes', [])) if isinstance(debug, dict) else '',
            })

    ragas_df = pd.DataFrame(ragas_rows)

    ragas_jsonl_path = output_jsonl_path.with_name(output_jsonl_path.stem + '_ragas_input.jsonl')
    ragas_csv_path = output_jsonl_path.with_name(output_jsonl_path.stem + '_ragas_input.csv')

    ragas_df.to_json(ragas_jsonl_path, orient='records', lines=True, force_ascii=False)
    ragas_df.to_csv(ragas_csv_path, index=False, encoding='utf-8-sig')

    reference_count = ragas_df['reference'].astype(str).str.strip().ne('').sum() if len(ragas_df) else 0
    print('RAGAS JSONL saved:', ragas_jsonl_path)
    print('RAGAS CSV saved:', ragas_csv_path)
    print(f'RAGAS reference rows: {reference_count}/{len(ragas_df)}')
    if reference_count == 0:
        print('WARNING: all reference values are empty. Do not run RAGAS reference-based metrics unless the eval data has answer reference columns.')

    return pd.DataFrame(rows)


# %% [code] cell 37
OUT_JSONL = DATA_DIR / 'outputs' / '0531_langgrpah_toolcalling_sample100.jsonl'

answer_df = run_adaptive_llm_on_eval(eval_gold_df, OUT_JSONL, limit=100,)

print('saved:', OUT_JSONL)
display(answer_df)

# %% [code] cell 38
answer_df[
    answer_df["id"].astype(str).isin(["Q001", "Q002", "Q007"])
]

# %% [code] cell 39
import json
from pathlib import Path

rows = [
    json.loads(line)
    for line in Path(OUT_JSONL).read_text(encoding="utf-8").splitlines()
    if line.strip()
]

for r in rows:
    dbg = r.get("retriever_debug", {})

    print("\n====", r["id"], "====")
    print("question_type:", r.get("question_type"))
    print("answer:", r.get("answer"))
    print("metrics:", r.get("retrieval_metrics"))
    print("raw_metrics:", r.get("raw_retrieval_metrics"))
    print("raw_docs:", r.get("raw_retrieved_docs"))
    print("graph_nodes:", " > ".join(dbg.get("graph_nodes", [])))
    print("selected_count:", dbg.get("selected_context_count"))
    print("g2b_context_count:", dbg.get("g2b_context_count"))
    print("manual_lookup_context_count:", dbg.get("manual_lookup_context_count"))
    print("manual_lookup_debug:", dbg.get("manual_lookup_debug"))

    print("\nG2B summary:")
    for c in r.get("g2b_calls", []):
        if c.get("endpoint") in ["local_notice_extractor", "local_g2b_candidate_summary"]:
            print(c)

    print("\nretrieved_contexts:")
    for c in r.get("retrieved_contexts", []):
        print("-", c.get("filename"), "|", c.get("chunk_id"))
        print((c.get("text") or "")[:500])

# %% [markdown] cell 40
# ==========================RAGAS DATA===============================

# %% [code] cell 41
OUT_JSONL = DATA_DIR / 'outputs' / '0531_langgrpah_toolcalling_100.jsonl'

answer_df = run_adaptive_llm_on_eval(eval_gold_df,OUT_JSONL, limit=100,)

print('saved:', OUT_JSONL)
display(answer_df)

# %% [code] cell 42
METRIC_COLS = ["hit_rate", "mrr", "ndcg", "recall"]

zero_metric_df = answer_df[
    answer_df[METRIC_COLS].eq(0).any(axis=1)
].copy()

zero_metric_df["zero_metrics"] = zero_metric_df[METRIC_COLS].eq(0).apply(
    lambda row: ", ".join(row.index[row].tolist()),
    axis=1,
)

wanted_cols = [
    "id", "type", "difficulty", "question_type", "question",
    "hit_rate", "mrr", "ndcg", "recall",
    "zero_metrics", "route", "chroma_where",
]

display_cols = [col for col in wanted_cols if col in zero_metric_df.columns]

print("zero metric rows:", len(zero_metric_df))
display(zero_metric_df[display_cols])

# %% [code] cell 43
hit0_df = answer_df[answer_df["hit_rate"].eq(0)].copy()

print("hit_rate 0 rows:", len(hit0_df))

wanted_cols = [
    "id", "type", "difficulty", "question_type", "question",
    "hit_rate", "mrr", "ndcg", "recall",
    "route", "chroma_where",
]

display_cols = [col for col in wanted_cols if col in hit0_df.columns]

display(hit0_df[display_cols])

# %% [code] cell 44
hit0_df = answer_df[answer_df["hit_rate"].eq(0)].copy()

HIT0_CSV = DATA_DIR / "outputs" / "ragas_kure+meta_llama_100_hit_rate_0.csv"

hit0_df.to_csv(
    HIT0_CSV,
    index=False,
    encoding="utf-8-sig",
)

print("hit_rate 0 rows:", len(hit0_df))
print("saved:", HIT0_CSV)
