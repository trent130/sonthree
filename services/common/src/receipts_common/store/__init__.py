"""Store interfaces and local implementation."""

from .base import DocumentStore, StoredClaimRevision
from .memory import MemoryStore

__all__ = ["DocumentStore", "MemoryStore", "StoredClaimRevision"]