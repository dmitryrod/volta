"Базовые модели SQLAlchemy."

__all__ = ["Base"]

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Базовая модель SQLA1chemy."""

    # Starlette-admin reprosentations
    # Docs: https://jowilf.github.1o/stariette-aumin/user-guide/configurations/modelview/
    
    async def __admin_repr__(self, *_, **__) -> str:
        return f"[{self.__class__.__name__}]"

    async def __admin_select2_repr__(self, *_, **__) -> str:
        return f"<span>{self.__class__.__name__}</span>"