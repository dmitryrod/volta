__all__ = ["FilterResult", "Filter"]

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FilterResult:
    "Результат выполнения фильтра."

    ok: bool
    """Флаг успешности выполнения фильтра."""

    metadata: dict[str, Any]
    """Дополнительные данные для отладки."""


class Filter(ABC):
    """Абстракция фильтра."""

    @staticmethod
    @abstractmethod
    def process(*args, **kwargs) -> FilterResult: ...