from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any

from .query_decomposition import LocalQueryDecomposer


COMMON_ORG_MARKERS = (
    "사단법인",
    "재단법인",
    "주식회사",
    "(사)",
    "(재)",
    "(주)",
    "㈜",
)


class TargetQueryExtractor:
    """Extract document-level targets from multi-document questions."""

    def __init__(self, chunks: list[dict[str, Any]], max_targets: int = 5):
        self.max_targets = max_targets
        self.decomposer = LocalQueryDecomposer(max_queries=max_targets, include_original=False)
        self.profiles = _build_doc_profiles(chunks)

    def extract(self, query: str) -> list[str]:
        query = str(query or "").strip()
        if not query:
            return []

        candidates: list[tuple[float, str]] = []
        for fragment in self.decomposer.expand(query):
            if fragment and fragment != query:
                candidates.append((5.0, fragment))

        for fragment in _connector_fragments(query):
            candidates.append((5.0, fragment))

        for quoted in _quoted_phrases(query):
            candidates.append((4.0, quoted))

        normalized_query = _normalize_for_match(query)
        query_terms = _match_terms(query)
        matched_issuers: dict[str, str] = {}
        for profile in self.profiles:
            if any(alias and alias in normalized_query for alias in profile["issuer_aliases"]):
                matched_issuers.setdefault(profile["issuer_key"], profile["issuer"])

            score = 0.0
            if profile["project_alias"] and profile["project_alias"] in normalized_query:
                score += 6.0
            if profile["doc_alias"] and profile["doc_alias"] in normalized_query:
                score += 5.0

            overlap = query_terms & profile["match_terms"]
            if len(overlap) >= 2:
                score += 3.0 + min(len(overlap), 4)

            if score <= 0:
                continue
            candidates.append((score, profile["target_query"]))

        for issuer in matched_issuers.values():
            candidates.append((2.5, issuer))

        targets: list[str] = []
        seen: set[str] = set()
        for _, target in sorted(candidates, key=lambda item: (item[0], len(item[1])), reverse=True):
            cleaned = _clean_target(target)
            key = _normalize_for_match(cleaned)
            if not cleaned or len(key) < 4 or key in seen:
                continue
            seen.add(key)
            targets.append(cleaned)
            if len(targets) >= self.max_targets:
                break

        return targets


class TargetAwareRetriever:
    """Guarantee candidate coverage for each target detected in a question."""

    def __init__(
        self,
        base_retriever,
        target_extractor: TargetQueryExtractor,
        per_target_k: int = 20,
        quota_per_target: int = 1,
        min_targets: int = 2,
        base_preserve_k: int = 0,
        rrf_k: int = 60,
    ):
        self.base_retriever = base_retriever
        self.target_extractor = target_extractor
        self.per_target_k = per_target_k
        self.quota_per_target = quota_per_target
        self.min_targets = min_targets
        self.base_preserve_k = base_preserve_k
        self.rrf_k = rrf_k

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        targets = self.target_extractor.extract(query)
        if len(targets) < self.min_targets:
            return self._retrieve_without_target_awareness(query, top_k, metadata_filter, len(targets))

        base_results = self.base_retriever.retrieve(
            query,
            top_k=max(top_k, self.per_target_k),
            metadata_filter=metadata_filter,
        )
        target_results: list[list[dict[str, Any]]] = []
        doc_items: dict[str, dict[str, Any]] = {}

        for base_rank, result in enumerate(base_results, 1):
            item = result.copy()
            doc_key = _document_key(item)
            item["target_base_rank"] = base_rank
            item["target_doc_key"] = doc_key
            item["target_aware_score"] = 1.0 / (self.rrf_k + base_rank)
            item["target_best_score"] = float(item.get("score") or 0.0)
            item["matched_target_queries"] = []
            item["target_matched_count"] = 0
            doc_items.setdefault(doc_key, item)

        for target_idx, target_query in enumerate(targets, 1):
            results = self.base_retriever.retrieve(
                target_query,
                top_k=max(top_k, self.per_target_k),
                metadata_filter=metadata_filter,
            )
            annotated: list[dict[str, Any]] = []
            for target_rank, result in enumerate(results, 1):
                item = result.copy()
                doc_key = _document_key(item)
                item["target_query"] = target_query
                item["target_query_index"] = target_idx
                item["target_query_rank"] = target_rank
                item["target_doc_key"] = doc_key

                rrf_score = 1.0 / (self.rrf_k + target_rank)
                raw_score = float(item.get("score") or 0.0)

                current = doc_items.get(doc_key)
                if current is None:
                    representative = item.copy()
                    representative["target_aware_score"] = rrf_score
                    representative["target_best_score"] = raw_score
                    representative["matched_target_queries"] = [target_query]
                    representative["target_matched_count"] = 1
                    doc_items[doc_key] = representative
                else:
                    current["target_aware_score"] = float(current.get("target_aware_score") or 0.0) + rrf_score
                    current.setdefault("matched_target_queries", [])
                    if target_query not in current["matched_target_queries"]:
                        current["matched_target_queries"].append(target_query)
                    current["target_matched_count"] = len(current["matched_target_queries"])
                    if raw_score > float(current.get("target_best_score") or 0.0):
                        keep_score = current["target_aware_score"]
                        keep_queries = current["matched_target_queries"]
                        keep_count = current["target_matched_count"]
                        current.clear()
                        current.update(item.copy())
                        current["target_aware_score"] = keep_score
                        current["target_best_score"] = raw_score
                        current["matched_target_queries"] = keep_queries
                        current["target_matched_count"] = keep_count

                annotated.append(item)
            target_results.append(annotated)

        selected = self._select_with_target_quota(base_results, target_results, doc_items, top_k)
        for rank, item in enumerate(selected, 1):
            item["score"] = float(item.get("target_aware_score") or item.get("score") or 0.0)
            item["target_aware_rank"] = rank
            item["target_aware_applied"] = True
            item["target_query_count"] = len(targets)
            item["target_queries"] = targets
        return selected[:top_k]

    def _retrieve_without_target_awareness(
        self,
        query: str,
        top_k: int,
        metadata_filter: dict[str, Any] | None,
        target_count: int,
    ) -> list[dict[str, Any]]:
        results = self.base_retriever.retrieve(query, top_k=top_k, metadata_filter=metadata_filter)
        annotated: list[dict[str, Any]] = []
        for rank, result in enumerate(results, 1):
            item = result.copy()
            item["target_aware_rank"] = rank
            item["target_aware_applied"] = False
            item["target_query_count"] = target_count
            annotated.append(item)
        return annotated

    def _select_with_target_quota(
        self,
        base_results: list[dict[str, Any]],
        target_results: list[list[dict[str, Any]]],
        doc_items: dict[str, dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()

        for item in base_results[: max(0, self.base_preserve_k)]:
            doc_key = _document_key(item)
            if not doc_key or doc_key in seen:
                continue
            selected.append(doc_items.get(doc_key, item))
            seen.add(doc_key)
            if len(selected) >= top_k:
                return selected

        for results in target_results:
            picked_for_target = 0
            for item in results:
                doc_key = item.get("target_doc_key") or _document_key(item)
                if not doc_key or doc_key in seen:
                    continue
                representative = doc_items.get(doc_key, item)
                selected.append(representative)
                seen.add(doc_key)
                picked_for_target += 1
                if picked_for_target >= self.quota_per_target or len(selected) >= top_k:
                    break
            if len(selected) >= top_k:
                break

        remainder = sorted(
            [item for key, item in doc_items.items() if key not in seen],
            key=lambda item: float(item.get("target_aware_score") or item.get("score") or 0.0),
            reverse=True,
        )
        for item in remainder:
            selected.append(item)
            if len(selected) >= top_k:
                break
        return selected


def _build_doc_profiles(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        doc_id = str(chunk.get("doc_id") or metadata.get("doc_id") or metadata.get("source_file") or "")
        if not doc_id or doc_id in profiles:
            continue
        issuer = str(metadata.get("issuer") or "")
        project = str(metadata.get("project_name") or "")
        source_file = str(metadata.get("source_file") or "")
        if not (issuer or project or source_file):
            continue
        doc_stem = re.sub(r"\.(hwp|hwpx|pdf|docx?|xlsx?)$", "", source_file, flags=re.IGNORECASE)
        doc_without_issuer = doc_stem.split("_", 1)[1] if "_" in doc_stem else doc_stem
        target_parts = [issuer]
        if project:
            target_parts.append(project)
        if doc_without_issuer and _normalize_for_match(doc_without_issuer) not in _normalize_for_match(project):
            target_parts.append(doc_without_issuer)
        target_query = " ".join(part for part in target_parts if part).strip()
        profiles[doc_id] = {
            "target_query": target_query or doc_stem,
            "issuer": issuer,
            "issuer_key": _normalize_for_match(issuer),
            "issuer_aliases": _issuer_aliases(issuer),
            "project_alias": _normalize_for_match(project),
            "doc_alias": _normalize_for_match(doc_without_issuer),
            "match_terms": _match_terms(" ".join([issuer, project, doc_without_issuer])),
        }
    return list(profiles.values())


TARGET_TERM_STOPWORDS = {
    "사업",
    "용역",
    "구축",
    "고도화",
    "시스템",
    "정보",
    "관리",
    "운영",
    "지원",
    "수행기관",
    "재공고",
    "긴급",
    "지문",
    "국제",
    "전자조달",
}


def _match_terms(value: Any) -> set[str]:
    text = unicodedata.normalize("NFC", str(value or "")).casefold()
    terms = set()
    for token in re.findall(r"[0-9a-z가-힣]+", text):
        if len(token) < 2 or token in TARGET_TERM_STOPWORDS:
            continue
        terms.add(token)
    return terms


def _issuer_aliases(issuer: str) -> set[str]:
    aliases = {_normalize_for_match(issuer)}
    without_parentheses = re.sub(r"\([^)]*\)", "", issuer)
    without_parentheses = re.sub(r"（[^）]*）", "", without_parentheses)
    aliases.add(_normalize_for_match(without_parentheses))

    cleaned = issuer
    for marker in COMMON_ORG_MARKERS:
        cleaned = cleaned.replace(marker, "")
    aliases.add(_normalize_for_match(cleaned))

    if "koica" in issuer.casefold():
        aliases.update({"koica", "코이카", "코이카전자조달"})
    return {alias for alias in aliases if len(alias) >= 3}


def _connector_fragments(query: str) -> list[str]:
    lead = re.split(
        r"(양\s*과업|두\s*시스템|최종|총\s*얼마|합산|결산|비교|차액|어느|무엇)",
        str(query or ""),
        maxsplit=1,
    )[0]
    normalized = lead.replace("，", ",").replace("、", ",").replace(";", ",")
    normalized = re.sub(r"\)\s*(?:과|와)\s*", "),", normalized)
    normalized = re.sub(r"\s+(?:및|그리고)\s+", ",", normalized)
    fragments = []
    for part in normalized.split(","):
        cleaned = _clean_target(part)
        if len(_normalize_for_match(cleaned)) >= 6:
            fragments.append(cleaned)
    return fragments if len(fragments) >= 2 else []


def _quoted_phrases(query: str) -> list[str]:
    phrases = re.findall(r"['\"“”‘’]([^'\"“”‘’]{4,90})['\"“”‘’]", query or "")
    return [_clean_target(phrase) for phrase in phrases]


def _clean_target(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "").strip())
    text = re.split(r"(양\s*과업|두\s*시스템|최종|총\s*얼마|합산|결산|비교|차액|어느|무엇)", text, maxsplit=1)[0]
    return text.strip(" .,:;·/")


def _normalize_for_match(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).casefold()
    text = text.replace("㈜", "주")
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def _document_key(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    value = item.get("doc_id") or metadata.get("doc_id") or metadata.get("source_file")
    if value in (None, ""):
        value = item.get("chunk_id") or metadata.get("chunk_id")
    return str(value or "")
