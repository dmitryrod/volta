"""Ingestor package."""

from volta.ingestor.operator import IngestorOperator
from volta.ingestor.writer import SnapshotWriter

__all__ = ["IngestorOperator", "SnapshotWriter"]
