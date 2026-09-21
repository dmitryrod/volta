__all__ = ["SignalCounter"]

import time
from collections import defaultdict


class SignalCounter[T]:
    """Класс, который считает количество сигналов за отведенный интервал."""

    def __init__(self, window_sec: int = 86400) -> None:
        """Инициализация класса SignalCounter.

        Args:
            window_sec (int): Интервал в секундах. По умолчанию 86400 (один день).
        """
        self._window_sec = window_sec
        self._signals: dict[T, list[float]] = defaultdict(list)

    def is_within_limit(self, item: T, limit: int) -> bool:
        """
        Проверяет, что количество сигналов НЕ превышает допустимый лимит.

        Лимит считается превышенным, если количество сигналов
        равно или больше limit.

        Args:
            item (T): Объект (сигнал) для которого проверяется количество срабатываний.
            limit (int): Максимально допустимое количество сигналов.

        Returns:
            bool: 
                True - если количество сигналов строго меньше limit
                    (лимит не превышен).
                False - если количество сигналов равно или больше limit
                    (лимит считается превышенным).
        """
        return self.get(item) < limit

    def get(self, item: T) -> int:
        """Возвращает количество сигналов  за интервал.

        Args:
            item (T): Сигнал.

        Returns:
            int: Количество сигналов за интервал.
        """
        timestamp = time.time()
        threshold = timestamp - self._window_sec
        self._signals[item] = [t for t in self._signals[item] if t > threshold]
        return len(self._signals[item])

    def add(self, item: T) -> int:
        """Добавляет сигнал и возвращает количество сигналов за интервал.

        Args:
            item (T): Сигнал.

        Returns:
            int: Количество сигналов за интервал.
        """
        timestamp = time.time()
        self._signals[item].append(timestamp)
        threshold = timestamp - self._window_sec
        self._signals[item] = [t for t in self._signals[item] if t > threshold]
        return len(self._signals[item])
