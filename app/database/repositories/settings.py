__all__ = ["SettingsRepository"]

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.settings import SettingsORM

from .abstract import Repository


class SettingsRepository(Repository[SettingsORM]):
    """Репозиторий для управления настройками."""
    
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(type_model=SettingsORM, session=session)