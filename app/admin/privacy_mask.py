"""Маскирование чувствительных полей в read-only выдаче админки (список / детали / API).

Полные ``chat_id`` и ``bot_token`` остаются только в формах CREATE/EDIT (см. ``RequestAction``).
"""

from __future__ import annotations

__all__ = ["mask_credential_display"]


def mask_credential_display(
    raw: str | int | None,
    *,
    head: int = 4,
    tail: int = 4,
    middle: str = "****",
) -> str | None:
    """Возвращает укороченное представление с скрытой серединой или ``None`` / пустую строку.

    Args:
        raw: Значение из ORM (``int`` для chat_id, ``str`` для токена).
        head: Символов с начала, остающихся видимыми.
        tail: Символов с конца, остающихся видимыми.
        middle: Замена для середины (без подстановки реального секрета).

    Returns:
        Маскированная строка; ``None`` если на входе ``None``; ``""`` если после strip пусто.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return ""
    n = len(s)
    if n <= head + tail:
        if n <= 2:
            return middle
        return s[0] + middle + s[-1]
    return s[:head] + middle + s[-tail:]
