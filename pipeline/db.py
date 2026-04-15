"""
Database operations for the KI Pipeline using SQLite.
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any


def init_db(db_path: str) -> None:
    """Initialize the SQLite database with the files table."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    with sqlite3.connect(db_path) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'normalized', 'ki', 'archived')),
                stage TEXT,
                source_conversation TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create indexes for performance
        conn.execute('CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_files_status ON files(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_files_path ON files(path)')
        
        # Create trigger to update updated_at
        conn.execute('''
            CREATE TRIGGER IF NOT EXISTS update_files_timestamp 
            AFTER UPDATE ON files
            BEGIN
                UPDATE files SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
        ''')
        
        conn.commit()


def get_file_by_hash(db_path: str, file_hash: str) -> Optional[Dict[str, Any]]:
    """Retrieve a file record by its hash."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM files WHERE hash = ?', (file_hash,))
        row = cursor.fetchone()
        return dict(row) if row else None


def insert_file(db_path: str, path: str, file_hash: str, status: str = 'pending', 
                stage: Optional[str] = None, source_conversation: Optional[str] = None) -> int:
    """Insert a new file record. Returns the file ID."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO files (path, hash, status, stage, source_conversation)
            VALUES (?, ?, ?, ?, ?)
        ''', (path, file_hash, status, stage, source_conversation))
        conn.commit()
        return cursor.lastrowid


def update_status(db_path: str, file_id: int, new_status: str, stage: Optional[str] = None) -> bool:
    """Update the status (and optionally stage) of a file record."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        if stage is not None:
            cursor.execute('UPDATE files SET status = ?, stage = ? WHERE id = ?', 
                         (new_status, stage, file_id))
        else:
            cursor.execute('UPDATE files SET status = ? WHERE id = ?', (new_status, file_id))
        conn.commit()
        return cursor.rowcount > 0


def list_files_by_status(db_path: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List files, optionally filtered by status."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if status:
            cursor.execute('SELECT * FROM files WHERE status = ? ORDER BY created_at DESC', (status,))
        else:
            cursor.execute('SELECT * FROM files ORDER BY created_at DESC')
        
        return [dict(row) for row in cursor.fetchall()]


def get_file_by_id(db_path: str, file_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve a file record by its ID."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM files WHERE id = ?', (file_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_file_by_path(db_path: str, path: str) -> Optional[Dict[str, Any]]:
    """Retrieve a file record by its path."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM files WHERE path = ?', (path,))
        row = cursor.fetchone()
        return dict(row) if row else None
