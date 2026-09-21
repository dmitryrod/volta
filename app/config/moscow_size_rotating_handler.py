"""logging.Handler: ротация по размеру с архивами ``stem.YYYY-MM-DD_HH-MM-SS_usecs.ext`` (Москва)."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .moscow_rotating import prune_timestamped_archives, rotate_file_to_timestamped_archive


class MoscowSizeRotatingFileHandler(logging.Handler):
    """
    Аналог RotatingFileHandler, но backup-файлы именуются как
    ``{stem}.{moscow_ts}{suffix}`` (не ``.1``, ``.2``).
    """

    def __init__(
        self,
        filename: str | Path,
        max_bytes: int,
        backup_count: int,
        *,
        encoding: str = "utf-8",
        delay: bool = False,
    ) -> None:
        super().__init__()
        self.base_path = Path(filename).resolve()
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.encoding = encoding
        self.delay = delay
        self.stream = None  # type: ignore[assignment]
        self._rotate_lock = threading.RLock()
        self._archive_stem = self.base_path.stem
        self._archive_suffix = self.base_path.suffix
        if not delay:
            self.stream = self._open()

    def close(self) -> None:  # noqa: A003
        with self._rotate_lock:
            if self.stream:
                try:
                    self.stream.flush()
                    self.stream.close()
                except OSError:
                    pass
                self.stream = None  # type: ignore[assignment]
        super().close()

    def _open(self):
        self.base_path.parent.mkdir(parents=True, exist_ok=True)
        return self.base_path.open("a", encoding=self.encoding)

    def emit(self, record: logging.LogRecord) -> None:  # noqa: A003
        try:
            msg = self.format(record)
            if not msg.endswith("\n"):
                msg += "\n"
            data = msg.encode(self.encoding, errors="replace")
            with self._rotate_lock:
                if self.stream is None:
                    self.stream = self._open()
                cur = self.base_path.stat().st_size if self.base_path.exists() else 0
                if cur + len(data) > self.max_bytes:
                    self.doRollover()
                self.stream.write(msg)
                self.stream.flush()
        except Exception:
            self.handleError(record)

    def doRollover(self) -> None:
        if self.stream:
            try:
                self.stream.flush()
                self.stream.close()
            except OSError:
                pass
            self.stream = None  # type: ignore[assignment]
        try:
            if self.base_path.is_file() and self.base_path.stat().st_size > 0:
                rotate_file_to_timestamped_archive(
                    self.base_path,
                    archive_stem=self._archive_stem,
                    archive_suffix=self._archive_suffix,
                )
            prune_timestamped_archives(
                self.base_path.parent,
                archive_stem=self._archive_stem,
                archive_suffix=self._archive_suffix,
                max_archives=self.backup_count,
            )
        except OSError:
            pass
        self.stream = self._open()
