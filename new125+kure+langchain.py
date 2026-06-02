#!/usr/bin/env python
# coding: utf-8
# Converted from new125+kure+langchain.ipynb


# %% [markdown] cell 1
# # new125 KURE + Adaptive Retrieval + LLM
#
# 1. Chroma DB를 불러옵니다.
# 2. `data/125_new/eval/eval_gold_agency_from_gt_docs`의 모든 CSV를 eval data로 읽습니다.
# 3. `adaptive_dense_first` retrieval을 실행합니다.
# 4. `sh2orc/Llama-3.1-Korean-8B-Instruct`로 답변을 생성합니다.
# 5. hit_rate, mrr, ndcg, recall과 샘플 답변을 출력합니다.

# %% [code] cell 2
!pip install -qU chromadb sentence-transformers transformers accelerate bitsandbytes pandas tqdm

# %% [code] cell 3
# 0. Install packages
# If transformers/huggingface_hub import errors occur after install, restart runtime once.
!pip install -qU   "langchain" "langchain-community" "langchain-chroma" "langchain-huggingface"   "rank-bm25" "sentence-transformers"   "transformers>=4.56.0,<5" "huggingface_hub>=0.34.0,<1.0"   "tokenizers>=0.22.0,<0.23.1" "accelerate" "bitsandbytes"

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
MAX_CONTEXTS = 2

DENSE_K = 50
SPARSE_K = 50

print('CHUNKS_PATH:', CHUNKS_PATH)
print('EVAL_GOLD_DIR:', EVAL_GOLD_DIR)
print('DRIVE_CHROMA_PATH:', DRIVE_CHROMA_PATH)

# %% [markdown] cell 7
# ## 2. Imports / 유틸

# %% [code] cell 8
import ast, json, math, re, shutil, unicodedata
from collections import Counter, defaultdict
from typing import Any

import chromadb
import numpy as np
import pandas as pd
import torch
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from tqdm.auto import tqdm


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
    if not text or text in {"[]", "{}", "nan", "None"}:
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
        parse_metadata_filter_dict(row.get("metadata_filter"))
        or parse_metadata_filter_dict(row.get("metadata_filter_dict"))
    )

    agency = raw.get("agency") or raw.get("issuer")

    if not agency or agency == "??":
        return None

    if isinstance(agency, (list, tuple, set)):
        agencies = [
            str(a).strip()
            for a in agency
            if str(a).strip() and str(a).strip() != "??"
        ]

        if len(agencies) == 1:
            return {"issuer": agencies[0]}

        if len(agencies) > 1:
            return {"issuer": {"$in": agencies}}

        return None

    agency = str(agency).strip()
    return {"issuer": agency} if agency and agency != "??" else None


eval_gold_df = load_eval_gold_csvs(EVAL_GOLD_DIR)
QUESTION_COL = infer_question_column(eval_gold_df)
GT_DOC_COL = infer_ground_truth_doc_column(eval_gold_df)
eval_gold_df['ground_truth_doc_list'] = eval_gold_df[GT_DOC_COL].apply(parse_doc_list_cell)
eval_gold_df = eval_gold_df[eval_gold_df['ground_truth_doc_list'].apply(bool)].reset_index(drop=True)
print('rows:', len(eval_gold_df), '| question:', QUESTION_COL, '| gt:', GT_DOC_COL)
display(eval_gold_df.head(3))

# %% [markdown] cell 20
# ## 8. Adaptive hybrid retrieval

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
    if any(k in q for k in ['예산', '사업비', '사업금액', '금액', '얼마', '추정가격', '기초금액']):
        return 'budget'
    if any(k in q for k in ['제출서류', '제안서', '서류', '구비서류']):
        return 'submission_documents'
    if any(k in q for k in ['참가자격', '입찰자격', '자격요건', '면허', '실적', '공동수급']):
        return 'eligibility'
    if any(k in q for k in ['마감일', '마감', '기한', '입찰마감', '제출기한']):
        return 'deadline'
    if any(k in q for k in ['사업기간', '수행기간', '계약기간', '유지보수']):
        return 'duration'
    if any(k in q for k in ['목적', '배경', '효과', '필요성', '왜']):
        return 'purpose'
    if any(k in q for k in ['비교', '차이', '더 큰', '더 작은', '둘 중', '중 어느']):
        return 'comparison'
    if any(k in q for k in ['목적', '배경', '효과', '필요성', '왜', '무엇을 위해']):
        return 'purpose'
    if any(k in q for k in ['비교', '차이', '더 큰', '더 작은', '둘 중', '중 어느', '공통점', '차이점']):
        return 'comparison'

    return 'general'

def metadata_priority(meta: dict[str, Any], question_type: str) -> int:
    fact_type = nfc(meta.get('fact_type'))
    answer_policy = nfc(meta.get('answer_policy'))
    chunk_type = nfc(meta.get('chunk_type'))
    score = 0

    if question_type == 'budget':
        if fact_type == 'project_budget':
            score += 60
        if to_bool(meta.get('budget_answer_enabled')):
            score += 50
        if answer_policy == 'allow_as_project_budget':
            score += 40
        if fact_type in {'threshold_budget', 'reference_amount', 'estimated_price', 'base_amount'}:
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
        budget_safe = []
        for c in reranked:
            meta = c.get('metadata') or {}
            if (
                nfc(meta.get('fact_type')) == 'project_budget'
                and to_bool(meta.get('budget_answer_enabled'))
                and nfc(meta.get('answer_policy')) == 'allow_as_project_budget'
            ):
                budget_safe.append(c)

        if budget_safe:
            return budget_safe[:max_contexts], question_type

        return reranked[:max_contexts], question_type

    return reranked[:max_contexts], question_type

# %% [code] cell 22
QUESTION_FACT_TYPES = {
    'budget': {'project_budget', 'budget', 'document_summary'},
    'submission_documents': {'submission_documents', 'submission_logistics', 'document_summary'},
    'eligibility': {'eligibility', 'business_type', 'document_summary'},
    'deadline': {'bid_deadline', 'deadline_term', 'submission_logistics', 'document_summary'},
    'duration': {'project_duration', 'maintenance_period', 'warranty_period', 'document_summary'},
    # 추가
    'purpose': {'project_purpose_effect','project_background','project_scope','document_summary','requirements',},
    'comparison': {'document_identity', 'document_summary', 'project_budget', 'project_duration', 'submission_documents','eligibility','project_purpose_effect', 'project_scope', },
    'general': {'document_summary', 'project_purpose_effect', 'project_background', 'project_scope', 'requirements'},}


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

# %% [code] cell 23
def select_contexts(question, candidates, max_contexts=MAX_CONTEXTS):
    qtype = infer_question_type(question)
    seen_chunks, seen_doc_fact, scored = set(), set(), []
    for cand in candidates:
        meta = cand.get('metadata') or {}
        cid = cand.get('chunk_id')
        if not cid or cid in seen_chunks: continue
        seen_chunks.add(cid)
        key = (meta.get('canonical_doc_id') or meta.get('doc_id'), meta.get('fact_type'), meta.get('section_path'))
        scored.append((metadata_priority(meta, qtype), cand.get('final_score', cand.get('rrf_score', 0)), key, cand))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    selected = []
    for _, _, key, cand in scored:
        if len(selected) >= max_contexts: break
        if key in seen_doc_fact and len(selected) >= 2: continue
        seen_doc_fact.add(key)
        selected.append(cand)
    return selected


def money_block(meta: dict[str, Any], question_type: str = 'general') -> str:
    fact_type = nfc(meta.get('fact_type'))
    answer_policy = nfc(meta.get('answer_policy'))

    # 예산 질문에서는 예산으로 답하면 안 되는 금액을 아예 context 금액 블록에서 제외
    if question_type == 'budget':
        is_budget_safe = (
            fact_type == 'project_budget'
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

    ranked = apply_metadata_rerank(search_query, rrf_merge(result_lists))
    selected = select_contexts(search_query, ranked, max_contexts)
    return selected, build_llm_context(selected), {
        'route': route,
        'search_query': search_query,
        'alias_hits': alias_hits[:5],
        'backfill_doc_ids': doc_ids,
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
        selected, _, debug = adaptive_retrieve(row[QUESTION_COL],row.get("history", None), EVAL_METRIC_K,chroma_where=chroma_where,)
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
반드시 제공된 근거(context) 안에서만 답변하세요.
근거가 부족하면 "문서 근거가 부족합니다"라고 답하세요.
금액 답변에서는 금액 역할이 project_budget이고 budget_answer_enabled=true인 값을 우선 사용하세요.
threshold_budget, reference_amount, estimated_price, base_amount, project_duration, bid_deadline은 사업 예산으로 단정하지 마세요.
답변은 간결하게 작성하고, 마지막에 출처 문서명을 표시하세요.
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
        repetition_penalty=1.08,
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

# %% [code] cell 32
def debug_eval_row_strategy(row_idx=0, strategy="hybrid", top_k=5):
    row = eval_gold_df.iloc[row_idx]
    question = row[QUESTION_COL]
    chroma_where = eval_filter_to_chroma_filter(row)

    print("=" * 100)
    print("ROW_IDX:", row_idx)
    print("ID:", row.get("id", ""))
    print("TYPE:", row.get("type", ""))
    print("DIFFICULTY:", row.get("difficulty", ""))
    print("QUESTION:", question)
    print("RAW metadata_filter:", row.get("metadata_filter"))
    print("RAW metadata_filter_dict:", row.get("metadata_filter_dict"))
    print("CHROMA_WHERE:", chroma_where)
    print("GROUND_TRUTH:", row.get("ground_truth_doc_list"))

    if chroma_where is None:
        print("\n[STOP] chroma_where is None. agency -> issuer 변환이 안 된 상태입니다.")
        return None

    dense = dense_retrieve(question, DENSE_K, where=chroma_where)
    sparse = sparse_retrieve(question, SPARSE_K, where=chroma_where)
    hybrid = apply_metadata_rerank(question, rrf_merge([dense, sparse]))

    print("\n[DENSE TOP]")
    display(pd.DataFrame([
        {
            "rank": x.get("rank"),
            "doc": (x.get("metadata") or {}).get("source_file"),
            "issuer": (x.get("metadata") or {}).get("issuer"),
            "fact_type": (x.get("metadata") or {}).get("fact_type"),
            "distance": x.get("distance"),
            "similarity": x.get("similarity"),
            "final_score": x.get("final_score"),
        }
        for x in dense[:top_k]
    ]))

    print("\n[SPARSE TOP]")
    display(pd.DataFrame([
        {
            "rank": x.get("rank"),
            "doc": (x.get("metadata") or {}).get("source_file"),
            "issuer": (x.get("metadata") or {}).get("issuer"),
            "fact_type": (x.get("metadata") or {}).get("fact_type"),
            "sparse_score": x.get("sparse_score"),
        }
        for x in sparse[:top_k]
    ]))

    print("\n[HYBRID RRF + METADATA RERANK TOP]")
    display(pd.DataFrame([
        {
            "rank": i + 1,
            "doc": (x.get("metadata") or {}).get("source_file"),
            "issuer": (x.get("metadata") or {}).get("issuer"),
            "fact_type": (x.get("metadata") or {}).get("fact_type"),
            "retrievers": x.get("retrievers") or x.get("retriever"),
            "rrf_score": x.get("rrf_score"),
            "metadata_priority": x.get("metadata_priority"),
            "final_score": x.get("final_score"),
        }
        for i, x in enumerate(hybrid[:top_k])
    ]))

    if "rerank_candidates" in globals():
        reranked = rerank_candidates(question, hybrid, top_n=RERANK_TOP_N)
        reranked = apply_metadata_rerank(question, reranked)

        print("\n[RERANK TOP]")
        display(pd.DataFrame([
            {
                "rank": i + 1,
                "doc": (x.get("metadata") or {}).get("source_file"),
                "issuer": (x.get("metadata") or {}).get("issuer"),
                "fact_type": (x.get("metadata") or {}).get("fact_type"),
                "retrievers": x.get("retrievers") or x.get("retriever"),
                "cross_encoder_score": x.get("cross_encoder_score"),
                "metadata_priority": x.get("metadata_priority"),
                "final_score": x.get("final_score"),
            }
            for i, x in enumerate(reranked[:top_k])
        ]))
    else:
        reranked = None
        print("\n[RERANK SKIP] rerank_candidates 함수가 없습니다.")

    selected, context_text, debug = adaptive_retrieve(
        question,
        row.get("history", None),
        max_contexts=top_k,
        chroma_where=chroma_where,
    )

    retrieved_docs = retrieved_docs_from_selected(selected, top_k=top_k)
    metrics = compute_retrieval_metrics_for_docs(
        row["ground_truth_doc_list"],
        retrieved_docs,
        top_k=top_k,
    )

    print("\n[ADAPTIVE SELECTED]")
    print("DEBUG:", debug)
    print("RETRIEVED_DOCS:", retrieved_docs)
    print("METRICS:", metrics)

    display(pd.DataFrame([
        {
            "rank": i + 1,
            "doc": (x.get("metadata") or {}).get("source_file"),
            "issuer": (x.get("metadata") or {}).get("issuer"),
            "fact_type": (x.get("metadata") or {}).get("fact_type"),
            "retrievers": x.get("retrievers") or x.get("retriever"),
            "final_score": x.get("final_score"),
        }
        for i, x in enumerate(selected)
    ]))

    return {
        "row": row,
        "chroma_where": chroma_where,
        "dense": dense,
        "sparse": sparse,
        "hybrid": hybrid,
        "reranked": reranked,
        "selected": selected,
        "debug": debug,
        "metrics": metrics,
    }

# %% [markdown] cell 33
# ## 12. Eval subset 답변 생성 + 저장

# %% [code] cell 34
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

# %% [code] cell 35
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

# %% [code] cell 36
def run_adaptive_llm_on_eval(df, output_jsonl_path, limit=5):
    work = df.head(limit).copy() if limit else df.copy()
    output_jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    ragas_rows = []

    with output_jsonl_path.open('w', encoding='utf-8') as f:
        for _, row in tqdm(work.iterrows(), total=len(work), desc='adaptive_llm'):
            q = row[QUESTION_COL]
            reference = get_reference_from_eval_row(row)
            chroma_where = eval_filter_to_chroma_filter(row)

            selected_raw, old_context_text, debug = adaptive_retrieve(
                q,
                row.get('history', None),
                MAX_CONTEXTS,
                chroma_where=chroma_where,
            )

            selected, question_type = select_contexts_for_llm(
                q,
                selected_raw,
                max_contexts=MAX_CONTEXTS,
            )

            context_text = build_llm_context(
                selected,
                question_type=question_type,
            )

            answer = generate_answer(
                question=q,
                context=context_text,
            )

            retrieved = retrieved_docs_from_selected(selected)
            metrics = compute_retrieval_metrics(
                row['ground_truth_doc_list'],
                retrieved,
            )

            payload = {
                'id': row.get('id', ''),
                'type': row.get('type', ''),
                'difficulty': row.get('difficulty', ''),
                'question': q,
                'question_type': question_type,
                'answer': answer,
                'reference': reference,
                'retrieved_contexts': to_eval_retrieved_contexts(selected),
                'retriever_strategy': 'adaptive_dense_first_budget_safe_agency_filter',
                'chroma_where': chroma_where,
                'retriever_debug': debug,
                'ground_truth_docs': row['ground_truth_doc_list'],
                'retrieval_metrics': metrics,
            }

            ragas_rows.append({
                "id": row.get("id", ""),
                "user_input": q,
                "response": answer,
                "retrieved_contexts": selected_to_ragas_contexts(selected),
                "reference": reference,
                "ground_truth_docs": row.get("ground_truth_doc_list", []),
                "type": row.get("type", ""),
                "difficulty": row.get("difficulty", ""),
                "chroma_where": chroma_where,
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
                **metrics,
                'route': '>'.join(debug.get('route', [])) if isinstance(debug, dict) else '',
            })

    ragas_df = pd.DataFrame(ragas_rows)

    ragas_jsonl_path = output_jsonl_path.with_name(output_jsonl_path.stem + "_ragas_input.jsonl")
    ragas_csv_path = output_jsonl_path.with_name(output_jsonl_path.stem + "_ragas_input.csv")

    ragas_df.to_json(
        ragas_jsonl_path,
        orient="records",
        lines=True,
        force_ascii=False,
    )

    ragas_df.to_csv(
        ragas_csv_path,
        index=False,
        encoding="utf-8-sig",
    )

    reference_count = ragas_df["reference"].astype(str).str.strip().ne("").sum() if len(ragas_df) else 0
    print("RAGAS JSONL saved:", ragas_jsonl_path)
    print("RAGAS CSV saved:", ragas_csv_path)
    print(f"RAGAS reference rows: {reference_count}/{len(ragas_df)}")
    if reference_count == 0:
        print("WARNING: all reference values are empty. Do not run RAGAS reference-based metrics unless the eval data has answer reference columns.")

    return pd.DataFrame(rows)

# %% [code] cell 37
OUT_JSONL = DATA_DIR / 'outputs' / '0530_kure_llama_sample.jsonl'

answer_df = run_adaptive_llm_on_eval(eval_gold_df, OUT_JSONL, limit=30,)

print('saved:', OUT_JSONL)
display(answer_df)

# %% [markdown] cell 38
# ==========================RAGAS DATA===============================

# %% [code] cell 39
OUT_JSONL = DATA_DIR / 'outputs' / '0530ragas_kure+meta_llama_100.jsonl'

answer_df = run_adaptive_llm_on_eval(eval_gold_df,OUT_JSONL, limit=100,)

print('saved:', OUT_JSONL)
display(answer_df)

# %% [code] cell 40
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

# %% [code] cell 41
hit0_df = answer_df[answer_df["hit_rate"].eq(0)].copy()

print("hit_rate 0 rows:", len(hit0_df))

wanted_cols = [
    "id", "type", "difficulty", "question_type", "question",
    "hit_rate", "mrr", "ndcg", "recall",
    "route", "chroma_where",
]

display_cols = [col for col in wanted_cols if col in hit0_df.columns]

display(hit0_df[display_cols])

# %% [code] cell 42
hit0_df = answer_df[answer_df["hit_rate"].eq(0)].copy()

HIT0_CSV = DATA_DIR / "outputs" / "ragas_kure+meta_llama_100_hit_rate_0.csv"

hit0_df.to_csv(
    HIT0_CSV,
    index=False,
    encoding="utf-8-sig",
)

print("hit_rate 0 rows:", len(hit0_df))
print("saved:", HIT0_CSV)
