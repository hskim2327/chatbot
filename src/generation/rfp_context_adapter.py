from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import rfp_advanced


DEFAULT_SOURCE_STORE = "data/processed/source_store_v2_125.jsonl"

RFP_FULL_CONFIG = dict(rfp_advanced.DEFAULT_GENERATION_CONFIG)

RFP_RECOMMENDED_CONFIG = {
    **rfp_advanced.DEFAULT_GENERATION_CONFIG,
    "max_context_chars_fact": 2200,
    "max_context_chars_synthesis": 3600,
    "max_blocks_fact": 4,
    "max_blocks_synthesis": 6,
    "evidence_text_chars": 520,
    "source_store_text_chars": 900,
}

RFP_TARGET_EVIDENCE_CONFIG = {
    **RFP_RECOMMENDED_CONFIG,
    "max_context_chars_fact": 3200,
    "max_context_chars_synthesis": 5200,
    "max_blocks_fact": 6,
    "max_blocks_synthesis": 8,
    "relaxed_target_fallback": True,
    "target_fallback_min_score": 0.22,
    "force_budget_fact_per_target": True,
    "direct_evidence_hierarchy": True,
    "dedupe_equivalent_evidence": True,
    "typed_answer_template": True,
}

RFP_TARGET_EVIDENCE_GUARDED_SOURCE_CONFIG = {
    **RFP_TARGET_EVIDENCE_CONFIG,
    "guard_source_store_budget": True,
    "source_store_budget_require_context_confirmation": True,
}

RFP_REQUIRED_FIELDS_CONTEXT_CONFIG = {
    **RFP_TARGET_EVIDENCE_CONFIG,
    "max_context_chars_fact": 4200,
    "max_context_chars_synthesis": 5600,
    "max_blocks_fact": 8,
    "max_blocks_synthesis": 10,
    "evidence_text_chars": 780,
    "source_store_text_chars": 500,
    "required_fields_profile": True,
    "prefer_required_field_evidence": True,
    "disable_source_store_full_text": True,
    "guard_source_store_budget": True,
    "source_store_budget_require_context_confirmation": True,
    "strict_source_store_temporal": True,
    "typed_answer_template": True,
}

RFP_AUTO_ROUTE_104_114_CONFIG = {
    **RFP_TARGET_EVIDENCE_GUARDED_SOURCE_CONFIG,
    "auto_route_104_114": True,
    "strict_source_store_temporal": True,
    "typed_answer_template": True,
}

RFP_BUDGET_TARGET_EVIDENCE_CONFIG = {
    **RFP_RECOMMENDED_CONFIG,
    "max_context_chars_fact": 2800,
    "max_context_chars_synthesis": 4200,
    "max_blocks_fact": 5,
    "max_blocks_synthesis": 7,
    "relaxed_target_fallback": True,
    "target_fallback_min_score": 0.22,
    "force_budget_fact_per_target": True,
    "direct_evidence_hierarchy": True,
    "dedupe_equivalent_evidence": True,
    "target_evidence_budget_only": True,
}

RFP_PRESERVE_TOP_EVIDENCE_CONFIG = {
    **RFP_TARGET_EVIDENCE_CONFIG,
    "max_context_chars_fact": 4200,
    "max_context_chars_synthesis": 6400,
    "max_blocks_fact": 8,
    "max_blocks_synthesis": 10,
    "evidence_text_chars": 650,
    "source_store_text_chars": 850,
    "preserve_raw_top_docs": True,
    "raw_top_doc_limit": 5,
    "raw_top_min_per_doc": 1,
    "require_fact_per_raw_doc": True,
    "raw_top_preserve_before_strict": True,
    "typed_answer_template": True,
}

RFP_SELECTIVE_TOP_EVIDENCE_CONFIG = {
    **RFP_TARGET_EVIDENCE_CONFIG,
    "max_context_chars_fact": 3600,
    "max_context_chars_synthesis": 5600,
    "max_blocks_fact": 7,
    "max_blocks_synthesis": 9,
    "evidence_text_chars": 620,
    "source_store_text_chars": 850,
    "selective_preserve_raw_top_docs": True,
    "raw_top_doc_limit": 5,
    "raw_top_min_per_doc": 1,
    "require_fact_per_raw_doc": True,
    "raw_top_preserve_before_strict": True,
    "selective_preserve_max_docs": 3,
    "selective_preserve_min_target_score": 0.22,
    "typed_answer_template": True,
}

RFP_PHASE3_BALANCED_EVIDENCE_CONFIG = {
    **RFP_TARGET_EVIDENCE_GUARDED_SOURCE_CONFIG,
    "max_context_chars_fact": 3800,
    "max_context_chars_synthesis": 6200,
    "max_blocks_fact": 8,
    "max_blocks_synthesis": 12,
    "evidence_text_chars": 620,
    "source_store_text_chars": 900,
    "task_family_guidance": True,
    "balance_required_fact_per_target": True,
    "balanced_max_target_docs": 5,
    "balanced_min_fact_blocks_per_doc": 1,
    "task_aware_source_store": True,
    "typed_answer_template": True,
}

RFP_SERVICE_ROUTE_V3_CONFIG = {
    **RFP_AUTO_ROUTE_104_114_CONFIG,
    "max_context_chars_fact": 4200,
    "max_context_chars_synthesis": 6800,
    "max_blocks_fact": 8,
    "max_blocks_synthesis": 12,
    "evidence_text_chars": 720,
    "source_store_text_chars": 1000,
    "auto_route_104_114": True,
    "budget_reference_value_postprocess": True,
    "multi_doc_structured_postprocess": True,
    "eligibility_structured_postprocess": True,
    "task_aware_source_store": True,
    "typed_answer_template": True,
    "selective_preserve_raw_top_docs": True,
    "raw_top_doc_limit": 5,
    "raw_top_min_per_doc": 1,
    "require_fact_per_raw_doc": True,
    "raw_top_preserve_before_strict": True,
    "selective_preserve_max_docs": 4,
    "selective_preserve_min_target_score": 0.22,
    "balance_required_fact_per_target": True,
    "balanced_max_target_docs": 4,
    "balanced_min_fact_blocks_per_doc": 1,
}


@dataclass
class RFPGenerationResources:
    chunk_index: dict[str, dict[str, Any]]
    source_store_index: dict[str, dict[str, Any]]


@dataclass
class RFPGenerationInput:
    question: str
    question_type: str
    prompt: str
    context_text: str
    context_records: list[dict[str, Any]]
    field_candidates: dict[str, list[str]]
    evidence_sentences: list[dict[str, Any]]
    system_prompt: str
    context_package: dict[str, Any]
    context_mode: str
    extra_payload: dict[str, Any]


def config_for_mode(context_mode: str) -> dict[str, Any]:
    if context_mode == "rfp_full":
        return dict(RFP_FULL_CONFIG)
    if context_mode == "rfp_recommended":
        return dict(RFP_RECOMMENDED_CONFIG)
    if context_mode == "rfp_target_evidence":
        return dict(RFP_TARGET_EVIDENCE_CONFIG)
    if context_mode == "rfp_target_evidence_guarded_source":
        return dict(RFP_TARGET_EVIDENCE_GUARDED_SOURCE_CONFIG)
    if context_mode == "rfp_required_fields":
        return dict(RFP_REQUIRED_FIELDS_CONTEXT_CONFIG)
    if context_mode == "rfp_auto_route_104_114":
        return dict(RFP_AUTO_ROUTE_104_114_CONFIG)
    if context_mode == "rfp_budget_target_evidence":
        return dict(RFP_BUDGET_TARGET_EVIDENCE_CONFIG)
    if context_mode == "rfp_preserve_top_evidence":
        return dict(RFP_PRESERVE_TOP_EVIDENCE_CONFIG)
    if context_mode == "rfp_selective_top_evidence":
        return dict(RFP_SELECTIVE_TOP_EVIDENCE_CONFIG)
    if context_mode == "rfp_phase3_balanced_evidence":
        return dict(RFP_PHASE3_BALANCED_EVIDENCE_CONFIG)
    if context_mode == "rfp_service_route_v3":
        return dict(RFP_SERVICE_ROUTE_V3_CONFIG)
    raise ValueError(f"Unsupported RFP context mode: {context_mode}")


def load_rfp_generation_resources(
    rows: list[dict[str, Any]],
    *,
    chunks_path: str | Path,
    source_store_path: str | Path = DEFAULT_SOURCE_STORE,
    use_source_store: bool = False,
) -> RFPGenerationResources:
    chunk_ids: set[str] = set()
    source_files: set[str] = set()
    source_store_ids: set[str] = set()

    for row in rows:
        for context in row.get("retrieved_contexts") or []:
            normalized = normalize_retrieved_context(context)
            if normalized.get("chunk_id"):
                chunk_ids.add(str(normalized["chunk_id"]))
            if normalized.get("source_file"):
                source_files.add(str(normalized["source_file"]))
            if normalized.get("source_store_id"):
                source_store_ids.add(str(normalized["source_store_id"]))

    fact_types = _advanced_fact_types()
    chunk_index = _load_chunk_index_flexible(
        chunks_path,
        chunk_ids=chunk_ids or None,
        source_files=source_files or None,
        fact_types=fact_types,
    )

    if use_source_store:
        target_source_files, target_source_store_ids = _collect_target_source_store_matches(
            rows,
            source_store_path=source_store_path,
        )
        source_files.update(target_source_files)
        source_store_ids.update(target_source_store_ids)
        if target_source_files:
            chunk_index = _load_chunk_index_flexible(
                chunks_path,
                chunk_ids=chunk_ids or None,
                source_files=source_files or None,
                fact_types=fact_types,
            )

    for chunk in chunk_index.values():
        source_store_id = _source_store_id_from_chunk(chunk)
        if source_store_id:
            source_store_ids.add(source_store_id)

    source_store_index = rfp_advanced.load_source_store_index(
        source_store_path,
        source_store_ids=source_store_ids or None,
        enabled=use_source_store,
    )
    return RFPGenerationResources(
        chunk_index=chunk_index,
        source_store_index=source_store_index,
    )


def build_rfp_generation_input(
    *,
    question: str,
    retrieved_contexts: list[dict[str, Any]],
    resources: RFPGenerationResources,
    context_mode: str,
    use_source_store: bool = False,
    task_metadata: dict[str, Any] | None = None,
) -> RFPGenerationInput:
    config = config_for_mode(context_mode)
    normalized_contexts = [normalize_retrieved_context(context) for context in retrieved_contexts]
    for rank, context in enumerate(normalized_contexts, start=1):
        context.setdefault("rank", rank)
    if use_source_store:
        normalized_contexts = _augment_contexts_with_target_fallback_chunks(
            question,
            normalized_contexts,
            resources,
        )
    context_package = rfp_advanced.build_context_package(
        question,
        normalized_contexts,
        chunk_index=resources.chunk_index,
        source_store_index=resources.source_store_index,
        use_source_store=use_source_store,
        config=config,
        task_metadata=task_metadata,
    )
    messages = rfp_advanced.build_prompt(context_package)
    system_prompt, user_prompt = _split_prompt_messages(messages)
    analysis = context_package.get("question_analysis", {}) or {}
    evidence_blocks = context_package.get("evidence_blocks", []) or []
    question_type = analysis.get("answer_type") or _first(analysis.get("question_types")) or "general"

    return RFPGenerationInput(
        question=question,
        question_type=str(question_type),
        prompt=user_prompt,
        system_prompt=system_prompt,
        context_text=str(context_package.get("context_text") or ""),
        context_records=[_context_record_from_block(block) for block in evidence_blocks],
        field_candidates=_field_candidates_from_package(context_package),
        evidence_sentences=[_evidence_sentence_from_block(block) for block in evidence_blocks[:10]],
        context_package=context_package,
        context_mode=context_mode,
        extra_payload={
            "context_mode": context_mode,
            "question_analysis": analysis,
            "core_summary": context_package.get("core_summary", {}),
            "evidence_blocks": evidence_blocks,
            "used_evidence_ids": _used_evidence_ids_from_blocks(evidence_blocks),
            "used_evidence_refs": _used_evidence_refs_from_blocks(evidence_blocks),
            "used_source_store_ids": [
                block.get("source_store_id")
                for block in evidence_blocks
                if block.get("source_store_id") and block.get("source_full_text")
            ],
            "context_char_count": len(str(context_package.get("context_text") or "")),
            "use_source_store": bool(context_package.get("use_source_store")),
            "advanced_config": config,
        },
    )


def _augment_contexts_with_target_fallback_chunks(
    question: str,
    normalized_contexts: list[dict[str, Any]],
    resources: RFPGenerationResources,
    *,
    max_added: int = 4,
) -> list[dict[str, Any]]:
    analysis = rfp_advanced.classify_question(question)
    intents = set(analysis.get("intent_slots", []) or [])
    if not ({"budget_difference", "budget_sum", "budget_ratio", "multi_doc_comparison"} & intents):
        return normalized_contexts

    slots = [
        slot
        for slot in (analysis.get("target_slots", []) or [])
        if slot.get("target_label") and not rfp_advanced._is_auxiliary_non_doc_target_slot(slot)
    ]
    if not slots:
        return normalized_contexts

    existing_chunk_ids = {str(ctx.get("chunk_id") or "") for ctx in normalized_contexts if ctx.get("chunk_id")}
    existing_source_keys = {
        rfp_advanced._normalize_doc_key(ctx.get("source_file") or ctx.get("filename") or "")
        for ctx in normalized_contexts
        if ctx.get("source_file") or ctx.get("filename")
    }

    slots_to_fill: list[dict[str, Any]] = []
    for slot in slots:
        covered = False
        for ctx in normalized_contexts:
            match_text = " ".join(str(ctx.get(key) or "") for key in ("source_file", "filename", "doc_key", "project_name", "issuer"))
            if rfp_advanced._best_target_match_score(match_text, [slot]) >= rfp_advanced.TARGET_MATCH_THRESHOLD:
                covered = True
                break
        if not covered:
            slots_to_fill.append(slot)
    if not slots_to_fill:
        return normalized_contexts

    best_by_source: dict[str, tuple[float, dict[str, Any]]] = {}
    for chunk_id, chunk in resources.chunk_index.items():
        if chunk_id in existing_chunk_ids:
            continue
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        source_file = str(chunk.get("source_file") or metadata.get("source_file") or "")
        source_key = rfp_advanced._normalize_doc_key(source_file)
        if not source_key or source_key in existing_source_keys:
            continue
        match_text = " ".join(
            str(value or "")
            for value in (
                source_file,
                metadata.get("source_file_nfc"),
                chunk.get("doc_key"),
                metadata.get("doc_key"),
                metadata.get("project_name"),
                metadata.get("issuer"),
            )
        )
        target_score = rfp_advanced._best_target_match_score(match_text, slots_to_fill)
        if target_score < 0.48:
            continue
        text = str(chunk.get("evidence_text_short") or chunk.get("content") or chunk.get("text") or "")
        fact_type = rfp_advanced._infer_fact_type_from_context(chunk_id, text, metadata)
        final_budget_krw = str(metadata.get("final_budget_krw") or chunk.get("final_budget_krw") or "")
        is_budget_like = fact_type in {"project_budget", "budget", "estimated_price", "base_amount"} or bool(final_budget_krw)
        if {"budget_difference", "budget_sum", "budget_ratio"} & intents and not is_budget_like:
            continue
        priority = target_score * 10
        if fact_type == "project_budget":
            priority += 4
        if final_budget_krw:
            priority += 3
        if str(chunk.get("chunk_type") or metadata.get("chunk_type") or "") == "fact_candidates":
            priority += 1
        current = best_by_source.get(source_key)
        if current is None or priority > current[0]:
            best_by_source[source_key] = (priority, chunk)

    if not best_by_source:
        return normalized_contexts

    augmented = list(normalized_contexts)
    next_rank = max([int(ctx.get("rank") or 0) for ctx in augmented] or [0]) + 1
    for _score, chunk in sorted(best_by_source.values(), key=lambda item: item[0], reverse=True)[:max_added]:
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        source_ref = chunk.get("source_ref") if isinstance(chunk.get("source_ref"), dict) else {}
        augmented.append(
            {
                "chunk_id": str(chunk.get("chunk_id") or ""),
                "source_file": str(chunk.get("source_file") or metadata.get("source_file") or ""),
                "source_store_id": str(source_ref.get("source_store_id") or metadata.get("source_store_id") or ""),
                "rank": next_rank,
                "score": _score,
                "selection_stage": "target_source_store_fallback",
                "retrieval_role": "target_source_store_fallback",
                "chunk_type": str(chunk.get("chunk_type") or metadata.get("chunk_type") or ""),
                "fact_type": str(chunk.get("fact_type") or metadata.get("fact_type") or ""),
            }
        )
        next_rank += 1
    return augmented


def postprocess_rfp_generation_answer(
    raw_text: str,
    generation_input: RFPGenerationInput,
) -> dict[str, Any]:
    return rfp_advanced.postprocess_answer(raw_text, generation_input.context_package)


def advanced_guardrails(answer: dict[str, Any]) -> dict[str, Any]:
    warnings = []
    warnings.extend(answer.get("warnings") or [])
    warnings.extend(answer.get("_failure_tags") or [])
    warnings.extend(answer.get("_answer_policy_violations") or [])
    if answer.get("_ungrounded_values"):
        warnings.append("ungrounded_values")

    confidence = str(answer.get("confidence") or "medium")
    if answer.get("_failure_tags"):
        confidence = str(answer.get("confidence") or "low")

    return {
        "confidence": confidence,
        "warnings": _unique(warnings),
        "answer_status": answer.get("answer_status"),
        "is_answerable": answer.get("is_answerable"),
        "valid_json": answer.get("_valid_json"),
        "llm_valid_json": answer.get("_llm_valid_json"),
        "json_repaired": answer.get("_json_repaired"),
        "parse_error_type": answer.get("_parse_error_type"),
        "citation_valid": answer.get("_citation_valid"),
        "numeric_grounded": answer.get("_numeric_grounded"),
        "source_numeric_grounded": answer.get("_source_numeric_grounded"),
        "derived_numeric_valid": answer.get("_derived_numeric_valid"),
        "ungrounded_values": answer.get("_ungrounded_values") or [],
        "failure_tags": answer.get("_failure_tags") or [],
        "missing_info": answer.get("missing_info") or [],
    }


def normalize_retrieved_context(context: dict[str, Any]) -> dict[str, Any]:
    metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    normalized = dict(context)
    source_file = (
        context.get("source_file")
        or context.get("filename")
        or metadata.get("source_file")
        or metadata.get("source_file_nfc")
        or ""
    )
    normalized["source_file"] = source_file
    normalized["filename"] = context.get("filename") or source_file
    normalized["chunk_id"] = context.get("chunk_id") or metadata.get("chunk_id") or ""
    normalized["doc_id"] = context.get("doc_id") or metadata.get("doc_id") or ""
    normalized["source_store_id"] = (
        context.get("source_store_id")
        or metadata.get("source_store_id")
        or _source_store_id_from_chunk(context)
        or ""
    )
    normalized["chunk_type"] = context.get("chunk_type") or metadata.get("chunk_type") or ""
    normalized["fact_type"] = context.get("fact_type") or metadata.get("fact_type") or ""
    normalized["section_path"] = context.get("section_path") or metadata.get("section_path") or ""
    return normalized


def _collect_target_source_store_matches(
    rows: list[dict[str, Any]],
    *,
    source_store_path: str | Path,
    min_score: float = 0.55,
) -> tuple[set[str], set[str]]:
    """Find high-confidence target documents missed by the raw retrieval set.

    This is intentionally lightweight: source_store is streamed once and only
    source files / source_store ids with strong target-slot matches are returned.
    It helps multi-document budget/comparison questions where one target doc is
    absent from the initial top-k chunks.
    """
    path = Path(source_store_path)
    if not path.exists():
        return set(), set()

    slots: list[dict[str, Any]] = []
    for row in rows:
        question = str(row.get("question") or row.get("eval_question") or "")
        if not question.strip():
            continue
        analysis = rfp_advanced.classify_question(question)
        intents = set(analysis.get("intent_slots", []) or [])
        if not ({"budget_difference", "budget_sum", "budget_ratio", "multi_doc_comparison"} & intents):
            continue
        for slot in analysis.get("target_slots", []) or []:
            label = str(slot.get("target_label") or "").strip()
            if not label:
                continue
            if rfp_advanced._is_auxiliary_non_doc_target_slot(slot):
                continue
            slots.append(slot)
    if not slots:
        return set(), set()

    best_by_label: dict[str, tuple[float, dict[str, Any]]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json_loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            match_text = _source_store_doc_match_text(record)
            if not match_text:
                continue
            for slot in slots:
                label = str(slot.get("target_label") or "")
                score = rfp_advanced._best_target_match_score(match_text, [slot])
                threshold = 0.48 if slot.get("issuer_hint") else min_score
                if score < threshold:
                    continue
                current = best_by_label.get(label)
                if current is None or score > current[0]:
                    best_by_label[label] = (score, record)

    source_files: set[str] = set()
    source_store_ids: set[str] = set()
    for _score, record in best_by_label.values():
        for key in ("source_file", "source_file_nfc"):
            value = str(record.get(key) or "").strip()
            if value:
                source_files.add(value)
        source_store_id = str(record.get("source_store_id") or "").strip()
        if source_store_id:
            source_store_ids.add(source_store_id)
    return source_files, source_store_ids


def _source_store_doc_match_text(record: dict[str, Any]) -> str:
    aliases = record.get("aliases")
    if isinstance(aliases, list):
        alias_text = " ".join(str(item) for item in aliases if item)
    else:
        alias_text = str(aliases or "")
    return " ".join(
        str(record.get(key) or "")
        for key in (
            "source_file",
            "source_file_nfc",
            "doc_key",
            "canonical_doc_key",
            "project_name",
            "project_name_stripped",
            "issuer",
            "g2b_title",
        )
    ) + " " + alias_text


def _load_chunk_index_flexible(
    chunks_path: str | Path,
    *,
    chunk_ids: set[str] | None = None,
    source_files: set[str] | None = None,
    fact_types: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    path = Path(chunks_path)
    if not path.exists():
        raise FileNotFoundError(f"chunks file not found: {path}")

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        data = json_loads(text)
    except ValueError:
        records = [json_loads(line) for line in text.splitlines() if line.strip()]
    else:
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict) and isinstance(data.get("chunks"), list):
            records = data["chunks"]
        else:
            records = []

    source_file_keys = {
        rfp_advanced._normalize_doc_key(value)
        for value in (source_files or set())
        if value
    }
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        chunk_id = str(record.get("chunk_id") or "")
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        source_key = rfp_advanced._normalize_doc_key(
            record.get("source_file") or metadata.get("source_file") or ""
        )
        selected_by_chunk = chunk_ids is None or chunk_id in chunk_ids
        selected_by_source = bool(source_file_keys and source_key in source_file_keys)
        if not selected_by_chunk and not selected_by_source:
            continue
        if selected_by_source and not selected_by_chunk and fact_types:
            fact_type = str(record.get("fact_type") or metadata.get("fact_type") or "")
            chunk_type = str(record.get("chunk_type") or metadata.get("chunk_type") or "")
            text_value = str(record.get("text") or record.get("content") or record.get("evidence_text_short") or "")
            inferred_fact_type = rfp_advanced._infer_fact_type_from_context(
                chunk_id,
                text_value,
                metadata,
            )
            if fact_type not in fact_types and inferred_fact_type not in fact_types and chunk_type != "fact_candidates":
                continue
        if chunk_id:
            index[chunk_id] = record
    return index


def json_loads(value: str) -> Any:
    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc


def _advanced_fact_types() -> set[str]:
    fact_types: set[str] = set(rfp_advanced.FACT_LOOKUP_TYPES)
    for values in rfp_advanced.QUESTION_TYPE_TO_FACT_TYPE.values():
        fact_types.update(values)
    for values in rfp_advanced.INTENT_REQUIRED_FACT_TYPES.values():
        fact_types.update(values)
    fact_types.update(
        {
            "project_background",
            "project_purpose_effect",
            "project_scope",
            "technical_requirements",
            "requirements",
        }
    )
    return fact_types


def _source_store_id_from_chunk(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    source_ref = chunk.get("source_ref") if isinstance(chunk.get("source_ref"), dict) else {}
    return str(source_ref.get("source_store_id") or metadata.get("source_store_id") or "")


def _split_prompt_messages(messages: list[dict[str, str]]) -> tuple[str, str]:
    system = ""
    user_parts = []
    for message in messages:
        if message.get("role") == "system":
            system = message.get("content", "")
        else:
            user_parts.append(message.get("content", ""))
    return system, "\n\n".join(part for part in user_parts if part)


def _evidence_display_id(block: dict[str, Any], idx: int) -> str:
    return str(block.get("evidence_id") or block.get("chunk_id") or f"E{idx}")


def _used_evidence_ids_from_blocks(blocks: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for idx, block in enumerate(blocks, start=1):
        evidence_id = _evidence_display_id(block, idx)
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        ids.append(evidence_id)
    return ids


def _used_evidence_refs_from_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, block in enumerate(blocks, start=1):
        evidence_id = _evidence_display_id(block, idx)
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        refs.append(
            {
                "evidence_id": evidence_id,
                "original_evidence_id": str(block.get("evidence_id") or ""),
                "chunk_id": block.get("chunk_id"),
                "source_file": block.get("source_file"),
                "fact_type": block.get("fact_type"),
                "section_path": block.get("section_path"),
                "source_store_id": block.get("source_store_id"),
            }
        )
    return refs


def _context_record_from_block(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": block.get("rank"),
        "filename": block.get("source_file"),
        "doc_id": "",
        "chunk_id": block.get("chunk_id"),
        "score": block.get("score"),
        "metadata": {
            "section_path": block.get("section_path"),
            "chunk_type": block.get("chunk_type"),
            "fact_type": block.get("fact_type"),
            "source_store_id": block.get("source_store_id"),
            "evidence_id": block.get("evidence_id"),
        },
        "text": block.get("text") or "",
    }


def _field_candidates_from_package(context_package: dict[str, Any]) -> dict[str, list[str]]:
    candidates: dict[str, list[str]] = {}
    core_summary = context_package.get("core_summary", {}) or {}
    documents = core_summary.get("documents") or []
    candidates["source_file"] = [
        doc.get("source_file") for doc in documents if doc.get("source_file")
    ]
    for doc in documents:
        for key, values in (doc.get("key_values") or {}).items():
            bucket = candidates.setdefault(str(key), [])
            for value in values or []:
                if value and value not in bucket:
                    bucket.append(value)
    computed = core_summary.get("computed_values") or {}
    if computed:
        candidates["computed_values"] = [rfp_advanced.truncate_text(computed, 400)]
    return {key: values[:20] for key, values in candidates.items() if values}


def _evidence_sentence_from_block(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": block.get("rank"),
        "filename": block.get("source_file"),
        "chunk_id": block.get("chunk_id"),
        "sentence": rfp_advanced.truncate_text(block.get("text") or "", 500),
    }


def _first(values: Any) -> Any:
    if isinstance(values, list) and values:
        return values[0]
    return None


def _unique(values: list[Any]) -> list[Any]:
    result = []
    for value in values:
        if value in (None, "", []):
            continue
        if value not in result:
            result.append(value)
    return result
