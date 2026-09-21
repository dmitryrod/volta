__all__ = ["TelegramApiError", "TelegramBot"]

import json

import aiohttp
from aiohttp import ClientTimeout


class TelegramApiError(RuntimeError):
    """Ответ Bot API с HTTP 200, но ``ok: false`` (или неожиданное тело)."""

    def __init__(
        self,
        message: str,
        *,
        error_code: int | None = None,
        description: str | None = None,
        raw: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.description = description
        self.raw = raw


class TelegramBot:
    """Утилита для отправки сообщений в телеграм."""

    def __init__(self):
        """Инициализирует экземпляр класса TelegramBot."""
        self._session = aiohttp.ClientSession(timeout=ClientTimeout(total=30))

    async def send_message(self, bot_token: str, chat_id: int, text: str) -> dict:
        """Отправляет сообщение в телеграм.

        Telegram нередко отдаёт **HTTP 200** и JSON с ``"ok": false`` (неверный chat_id,
        невалидный HTML, flood и т.д.). Без проверки ``ok`` это выглядит как «успех», хотя
        сообщение не доставлено.
        """
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with self._session.post(url, json=data) as response:
            response.raise_for_status()
            raw_text = await response.text()
        try:
            body = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise TelegramApiError(
                f"Telegram API: не JSON в ответе: {raw_text[:500]!r}",
                raw=None,
            ) from e

        if not isinstance(body, dict):
            raise TelegramApiError(f"Telegram API: ожидали dict, получили {type(body).__name__}", raw=None)

        if not body.get("ok"):
            desc = body.get("description") or "unknown"
            code = body.get("error_code")
            raise TelegramApiError(
                f"Telegram API ok=false: {desc}" + (f" (error_code={code})" if code is not None else ""),
                error_code=code if isinstance(code, int) else None,
                description=str(desc) if desc is not None else None,
                raw=body,
            )

        return body

    async def close(self) -> None:
        """Закрывает сессию."""
        await self._session.close()