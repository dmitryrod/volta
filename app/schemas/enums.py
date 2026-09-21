"""Перечисления, используемые в приложении."""

from enum import StrEnum

__all__ = ["EnvironmentType", "TextTemplateType"]


class EnvironmentType(StrEnum):
    """Перечисление типов окружения."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"


class TextTemplateType(StrEnum):
    """Перечисление шаблонов текста."""

    DEFAULT = "default"
    TREE = "tree"