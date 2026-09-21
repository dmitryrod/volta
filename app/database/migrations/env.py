"""Точка входа Alembic для выполнения миграций."""

from logging.config import fileConfig
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# Добавляем корень проекта в sys.path, чтобы импортировать пакет app
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.config import config as _config
from app.database.models import *

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Set sqlalchemy.url (используем непосредственно экземпляр конфигурации)
config.set_main_option(
    "sqlalchemy.url", _config.db.build_connection_str() + "?async_fallback=true"
)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata  # noqa: F405

# other values from the config, defined by the needs of env.py,
# can be acquired: