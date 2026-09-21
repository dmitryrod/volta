"""Абстрактный репозиторий для работы с моделями БД."""

from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Base

AbstractModel = TypeVar("AbstractModel", bound=Base)


class Repository[AbstractModel]:
    """Базовый абстрактный репозиторий."""

    def __init__(self, type_model: type[AbstractModel], session: AsyncSession):
        """Инициализирует абстрактный репозиторий.

        :param type_model: Модель, с которой выполняются операции.
        :param session: Сессия, в рамках которой работает репозиторий.
        """
        self.type_model = type_model
        self.session = session
    
    async def get(self, ident: int | str) -> AbstractModel | None:
        """Получает одну запись по первичному ключу.
        
        :param ident: Значение ключа, по которому ищем запись.
        :return: Найденная модель или None.
        """
        return await self.session.get(entity=self.type_model, ident=ident)

    async def get_all(self) -> Sequence[AbstractModel]:
        """Возвращает все записи для модели репозитория."""
        result = await self.session.execute(select(self.type_model))
        return result.scalars().all()