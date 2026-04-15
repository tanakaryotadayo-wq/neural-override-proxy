"""
Controller Ledger Implementation - Core functionality for workspace session tracking.

Provides thread-safe, file-locked persistence of workspace session data with
JSON serialization and validation against schema.
"""

import fcntl
import json
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from contextlib import contextmanager


# Custom Exceptions
class LedgerError(Exception):
    """Base exception for ledger operations."""
    pass


class LedgerNotFoundError(LedgerError):
    """Raised when ledger file is not found."""
    pass


class LedgerValidationError(LedgerError):
    """Raised when ledger data fails validation."""
    pass


# Helper Functions
def unique_append(target_list: List[str], item: str) -> List[str]:
    """
    Append item to list only if it's not already present.
    
    Args:
        target_list: List to append to
        item: Item to append if unique
        
    Returns:
        Updated list with unique items only
    """
    result = deepcopy(target_list)
    if item not in result:
        result.append(item)
    return result


def _serialize_datetime(dt: datetime) -> str:
    """Serialize datetime to ISO format string."""
    return dt.isoformat()


def _deserialize_datetime(dt_str: str) -> datetime:
    """Deserialize ISO format string to datetime."""
    return datetime.fromisoformat(dt_str)


@dataclass
class LedgerEntry:
    """
    Represents a workspace session entry in the controller ledger.
    
    Tracks the state and metadata of a workspace session including
    runtime choice, session IDs, and associated files.
    """
    workspace_name: str
    workspace_path: str
    session_status: str = "unknown"  # running/stopped/unknown
    chosen_runtime: str = "unknown"  # gemini-acp/jules/qwen/unknown  
    acp_session_id: Optional[str] = None
    report_paths: List[str] = field(default_factory=list)
    jules_job_ids: List[str] = field(default_factory=list)
    last_active_file: Optional[str] = None
    updated_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Validate field values after initialization."""
        valid_statuses = {"running", "stopped", "unknown"}
        valid_runtimes = {"gemini-acp", "jules", "qwen", "unknown"}
        
        if self.session_status not in valid_statuses:
            raise LedgerValidationError(f"Invalid session_status: {self.session_status}")
            
        if self.chosen_runtime not in valid_runtimes:
            raise LedgerValidationError(f"Invalid chosen_runtime: {self.chosen_runtime}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert entry to dictionary for JSON serialization."""
        data = asdict(self)
        data['updated_at'] = _serialize_datetime(self.updated_at)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LedgerEntry':
        """Create entry from dictionary (JSON deserialization)."""
        data = deepcopy(data)
        data['updated_at'] = _deserialize_datetime(data['updated_at'])
        return cls(**data)
    
    def add_report_path(self, path: str) -> None:
        """Add a report path if not already present."""
        self.report_paths = unique_append(self.report_paths, path)
        self.updated_at = datetime.now()
    
    def add_jules_job_id(self, job_id: str) -> None:
        """Add a Jules job ID if not already present."""
        self.jules_job_ids = unique_append(self.jules_job_ids, job_id)
        self.updated_at = datetime.now()


@dataclass
class Ledger:
    """
    Main ledger container holding all workspace entries.
    
    Provides versioned storage and validation of workspace session data.
    """
    version: int = 1
    workspaces: Dict[str, LedgerEntry] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert ledger to dictionary for JSON serialization."""
        return {
            "version": self.version,
            "workspaces": {
                name: entry.to_dict() 
                for name, entry in self.workspaces.items()
            }
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Ledger':
        """Create ledger from dictionary (JSON deserialization)."""
        data = deepcopy(data)
        workspaces = {
            name: LedgerEntry.from_dict(entry_data)
            for name, entry_data in data.get("workspaces", {}).items()
        }
        return cls(
            version=data.get("version", 1),
            workspaces=workspaces
        )
    
    def add_or_update_entry(self, entry: LedgerEntry) -> None:
        """Add or update a workspace entry."""
        entry_copy = deepcopy(entry)
        entry_copy.updated_at = datetime.now()
        self.workspaces[entry.workspace_name] = entry_copy
    
    def get_entry(self, workspace_name: str) -> Optional[LedgerEntry]:
        """Get workspace entry by name."""
        entry = self.workspaces.get(workspace_name)
        return deepcopy(entry) if entry else None
    
    def remove_entry(self, workspace_name: str) -> bool:
        """Remove workspace entry. Returns True if removed, False if not found."""
        return self.workspaces.pop(workspace_name, None) is not None


# File I/O with Locking
LEDGER_FILE = Path.home() / ".neural-override" / "controller-ledger.json"


@contextmanager
def _file_lock(file_path: Path, mode: str = 'r'):
    """Context manager for file locking using fcntl.flock."""
    # Ensure parent directory exists
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Open file with appropriate mode
    if 'w' in mode or 'a' in mode:
        f = open(file_path, mode)
        lock_type = fcntl.LOCK_EX  # Exclusive lock for writing
    else:
        if not file_path.exists():
            # Create empty file if it doesn't exist for reading
            file_path.touch()
        f = open(file_path, mode)
        lock_type = fcntl.LOCK_SH  # Shared lock for reading
    
    try:
        # Acquire lock with timeout
        fcntl.flock(f.fileno(), lock_type | fcntl.LOCK_NB)
        yield f
    except (IOError, OSError) as e:
        raise LedgerError(f"Could not acquire file lock: {e}")
    finally:
        # Release lock and close file
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except:
            pass  # Best effort unlock
        f.close()


def _read_ledger_file() -> Dict[str, Any]:
    """Read and parse the ledger file."""
    try:
        with _file_lock(LEDGER_FILE, 'r') as f:
            content = f.read().strip()
            if not content:
                return {"version": 1, "workspaces": {}}
            return json.loads(content)
    except json.JSONDecodeError as e:
        raise LedgerValidationError(f"Invalid JSON in ledger file: {e}")
    except FileNotFoundError:
        return {"version": 1, "workspaces": {}}


def _write_ledger_file(data: Dict[str, Any]) -> None:
    """Write ledger data to file."""
    with _file_lock(LEDGER_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())  # Force write to disk


# Public API
def read_ledger() -> Ledger:
    """
    Read the controller ledger from disk.
    
    Returns:
        Ledger object containing all workspace entries
        
    Raises:
        LedgerError: If file cannot be read or parsed
    """
    try:
        data = _read_ledger_file()
        return Ledger.from_dict(data)
    except Exception as e:
        if isinstance(e, (LedgerError, LedgerValidationError)):
            raise
        raise LedgerError(f"Failed to read ledger: {e}")


def update_entry(entry: LedgerEntry) -> None:
    """
    Update or create a workspace entry in the ledger.
    
    Args:
        entry: LedgerEntry to update
        
    Raises:
        LedgerError: If update fails
        LedgerValidationError: If entry data is invalid
    """
    try:
        # Read current ledger
        ledger = read_ledger()
        
        # Add/update entry (this creates a deep copy)
        ledger.add_or_update_entry(entry)
        
        # Write back to disk
        _write_ledger_file(ledger.to_dict())
        
    except Exception as e:
        if isinstance(e, (LedgerError, LedgerValidationError)):
            raise
        raise LedgerError(f"Failed to update entry: {e}")


def get_active_sessions() -> List[LedgerEntry]:
    """
    Get all workspace entries with 'running' session status.
    
    Returns:
        List of LedgerEntry objects with running sessions
        
    Raises:
        LedgerError: If ledger cannot be read
    """
    try:
        ledger = read_ledger()
        active = [
            entry for entry in ledger.workspaces.values()
            if entry.session_status == "running"
        ]
        # Return deep copies to prevent accidental mutation
        return [deepcopy(entry) for entry in active]
    except Exception as e:
        if isinstance(e, LedgerError):
            raise
        raise LedgerError(f"Failed to get active sessions: {e}")


def delete_entry(workspace_name: str) -> bool:
    """
    Delete a workspace entry from the ledger.
    
    Args:
        workspace_name: Name of workspace to delete
        
    Returns:
        True if entry was deleted, False if not found
        
    Raises:
        LedgerError: If delete operation fails
    """
    try:
        ledger = read_ledger()
        was_removed = ledger.remove_entry(workspace_name)
        
        if was_removed:
            _write_ledger_file(ledger.to_dict())
        
        return was_removed
        
    except Exception as e:
        if isinstance(e, LedgerError):
            raise
        raise LedgerError(f"Failed to delete entry: {e}")


def get_entry(workspace_name: str) -> Optional[LedgerEntry]:
    """
    Get a specific workspace entry.
    
    Args:
        workspace_name: Name of workspace to retrieve
        
    Returns:
        LedgerEntry if found, None otherwise
        
    Raises:
        LedgerError: If read operation fails
    """
    try:
        ledger = read_ledger()
        return ledger.get_entry(workspace_name)
    except Exception as e:
        if isinstance(e, LedgerError):
            raise
        raise LedgerError(f"Failed to get entry: {e}")
