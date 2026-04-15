"""
File ingestion logic for the KI Pipeline.
"""

import os
import hashlib
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path

from .db import init_db, get_file_by_hash, get_file_by_path, insert_file


@dataclass
class IngestResult:
    """Result of file ingestion operation."""
    status: str  # 'success', 'skipped', 'error'
    file_id: Optional[int] = None
    skipped_reason: Optional[str] = None


def ensure_directories(base_path: str) -> None:
    """Create the required pipeline directories if they don't exist."""
    directories = ['raw', 'normalized', 'ki', 'archive']
    
    for directory in directories:
        dir_path = os.path.join(base_path, directory)
        os.makedirs(dir_path, exist_ok=True)


def compute_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    
    try:
        with open(file_path, "rb") as f:
            # Read the file in chunks to handle large files efficiently
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
    except (IOError, OSError) as e:
        raise ValueError(f"Cannot read file {file_path}: {e}")
    
    return sha256_hash.hexdigest()


def ingest_file(file_path: str, db_path: str, source_conversation: Optional[str] = None) -> IngestResult:
    """
    Ingest a file into the pipeline. This operation is idempotent.
    
    Args:
        file_path: Path to the file to ingest
        db_path: Path to the SQLite database
        source_conversation: Optional identifier for the source conversation
        
    Returns:
        IngestResult indicating success, skip, or error
    """
    # Ensure database exists
    init_db(db_path)
    
    # Validate file exists and is readable
    if not os.path.exists(file_path):
        return IngestResult(
            status='error',
            skipped_reason=f"File does not exist: {file_path}"
        )
    
    if not os.path.isfile(file_path):
        return IngestResult(
            status='error', 
            skipped_reason=f"Path is not a file: {file_path}"
        )
    
    try:
        # Compute file hash
        file_hash = compute_hash(file_path)
        
        # Check if file already exists by hash (content-based deduplication)
        existing_by_hash = get_file_by_hash(db_path, file_hash)
        if existing_by_hash:
            return IngestResult(
                status='skipped',
                file_id=existing_by_hash['id'],
                skipped_reason=f"File with same content already exists (ID: {existing_by_hash['id']})"
            )
        
        # Check if file already exists by path
        absolute_path = os.path.abspath(file_path)
        existing_by_path = get_file_by_path(db_path, absolute_path)
        if existing_by_path:
            # Path exists but hash is different - this is an update
            # For now, we'll skip it, but could implement update logic here
            return IngestResult(
                status='skipped',
                file_id=existing_by_path['id'],
                skipped_reason=f"File path already tracked (ID: {existing_by_path['id']})"
            )
        
        # Insert new file record
        file_id = insert_file(
            db_path=db_path,
            path=absolute_path,
            file_hash=file_hash,
            status='pending',
            source_conversation=source_conversation
        )
        
        return IngestResult(
            status='success',
            file_id=file_id
        )
        
    except Exception as e:
        return IngestResult(
            status='error',
            skipped_reason=f"Error processing file: {str(e)}"
        )


def ingest_directory(directory_path: str, db_path: str, recursive: bool = False,
                    source_conversation: Optional[str] = None) -> List[IngestResult]:
    """
    Ingest all files in a directory.
    
    Args:
        directory_path: Path to directory to scan
        db_path: Path to the SQLite database  
        recursive: Whether to scan subdirectories
        source_conversation: Optional identifier for the source conversation
        
    Returns:
        List of IngestResult for each file processed
    """
    results = []
    
    if not os.path.exists(directory_path):
        return [IngestResult(
            status='error',
            skipped_reason=f"Directory does not exist: {directory_path}"
        )]
    
    if not os.path.isdir(directory_path):
        return [IngestResult(
            status='error',
            skipped_reason=f"Path is not a directory: {directory_path}"
        )]
    
    try:
        if recursive:
            # Use Path.rglob for recursive scanning
            for file_path in Path(directory_path).rglob('*'):
                if file_path.is_file():
                    result = ingest_file(str(file_path), db_path, source_conversation)
                    results.append(result)
        else:
            # Scan only direct children
            for entry in os.listdir(directory_path):
                entry_path = os.path.join(directory_path, entry)
                if os.path.isfile(entry_path):
                    result = ingest_file(entry_path, db_path, source_conversation)
                    results.append(result)
    except Exception as e:
        results.append(IngestResult(
            status='error',
            skipped_reason=f"Error scanning directory: {str(e)}"
        ))
    
    return results
