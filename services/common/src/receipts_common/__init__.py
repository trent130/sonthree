"""Shared, local-first primitives for Receipts services."""

from .config import Settings, load_settings
from .ids import IdAllocator
from .io import ContractViolation, ValidatingReader, ValidatingWriter, validate_document

__all__ = [
    "ContractViolation",
    "IdAllocator",
    "Settings",
    "ValidatingReader",
    "ValidatingWriter",
    "load_settings",
    "validate_document",
]