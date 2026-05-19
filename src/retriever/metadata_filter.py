from typing import Any


ALIASES = {
    "agency": "issuer",
    "issuer": "issuer",
    "project": "project_name",
    "project_name": "project_name",
    "source": "source_file",
    "source_file": "source_file",
    "doc": "doc_id",
    "doc_id": "doc_id",
    "chunk": "chunk_id",
    "chunk_id": "chunk_id",
}

MULTI_VALUE_MARKERS = {"다중", "multi", "multiple"}


def normalize_filter(metadata_filter: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata_filter:
        return {}

    normalized: dict[str, Any] = {}
    for key, value in metadata_filter.items():
        if _is_empty_filter_value(value):
            continue
        normalized[ALIASES.get(key, key)] = value
    return normalized


def matches_metadata(item: dict[str, Any], metadata_filter: dict[str, Any] | None) -> bool:
    filters = normalize_filter(metadata_filter)
    if not filters:
        return True

    metadata = item.get("metadata") or {}
    for key, expected in filters.items():
        actual = item.get(key) if key in item else metadata.get(key)
        if not _matches_value(actual, expected):
            return False
    return True


def filter_items(items: list[dict[str, Any]], metadata_filter: dict[str, Any] | None) -> list[dict[str, Any]]:
    filters = normalize_filter(metadata_filter)
    if not filters:
        return items
    return [item for item in items if matches_metadata(item, filters)]


def _is_empty_filter_value(value: Any) -> bool:
    if value in (None, "", []):
        return True
    if isinstance(value, str) and value.strip().casefold() in MULTI_VALUE_MARKERS:
        return True
    return False


def _matches_value(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set)):
        return any(_matches_value(actual, value) for value in expected)

    if actual in (None, ""):
        return False

    if isinstance(actual, (list, tuple, set)):
        return any(_matches_value(value, expected) for value in actual)

    actual_text = str(actual).casefold()
    expected_text = str(expected).casefold()
    return expected_text in actual_text
