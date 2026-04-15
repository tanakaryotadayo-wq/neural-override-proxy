"""
File-first Knowledge Intelligence Pipeline

A pipeline system for ingesting, processing, and managing files through
different stages: pending → normalized → ki → archived.
"""

__version__ = "0.1.0"
__author__ = "Neural Override Proxy"

from .ingestion import IngestResult, ensure_directories, compute_hash, ingest_file
from .db import init_db, get_file_by_hash, insert_file, update_status, list_files_by_status
from .file_watcher import WatcherConfig, start_watching

__all__ = [
    "IngestResult",
    "ensure_directories", 
    "compute_hash",
    "ingest_file",
    "init_db",
    "get_file_by_hash",
    "insert_file", 
    "update_status",
    "list_files_by_status",
    "WatcherConfig",
    "start_watching"
]
