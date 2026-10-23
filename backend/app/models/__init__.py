"""ORM models.

Import every model module here so ``Base.metadata`` is complete for Alembic
autogenerate and for test fixtures that call ``create_all``.
"""

from app.db.base import Base

__all__ = ["Base"]
