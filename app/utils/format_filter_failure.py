from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.screener.filters import FilterResult


def format_filter_failure(reason: str, result: FilterResult | None = None) -> str:
    """Приводит результат провала фильтра к человекочитаемой строке.

    reason — краткое текстовое описание причины,
    result.metadata (если передан) — детальные числа/поля.
    """
    if result is None or not hasattr(result, "metadata"):
        return reason

    if not result.metadata:
        return reason

    # Простейший формат: reason + key=value по метаданным
    meta_parts: list[str] = []
    for key, value in result.metadata.items():
        meta_parts.append(f"{key}={value}")

    meta_str = ", ".join(meta_parts)
    return f"{reason} ({meta_str})"

