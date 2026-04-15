"""
Controller Ledger - Track workspace sessions and runtime states.

This package provides functionality to track workspace sessions, runtime choices,
and associated metadata across different AI development environments.
"""

from .controller_ledger import (
    read_ledger,
    update_entry,
    get_active_sessions,
    LedgerEntry,
    Ledger,
    unique_append,
    LedgerError,
    LedgerNotFoundError,
    LedgerValidationError
)

__version__ = "1.0.0"
__all__ = [
    "read_ledger",
    "update_entry", 
    "get_active_sessions",
    "LedgerEntry",
    "Ledger",
    "unique_append",
    "LedgerError",
    "LedgerNotFoundError",
    "LedgerValidationError"
]
