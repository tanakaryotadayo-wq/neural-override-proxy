"""
File system watcher for the KI Pipeline using watchdog.
"""

import os
import time
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

from .ingestion import ingest_file


@dataclass
class WatcherConfig:
    """Configuration for file system watcher."""
    watch_dir: str
    db_path: str
    recursive: bool = False
    source_conversation: Optional[str] = None
    debounce_seconds: float = 1.0  # Wait before processing to avoid partial writes


class KIPipelineHandler(FileSystemEventHandler):
    """Handler for file system events in the KI Pipeline."""
    
    def __init__(self, config: WatcherConfig):
        super().__init__()
        self.config = config
        self._last_processed = {}  # Track last processing time for debouncing
    
    def _should_process_file(self, file_path: str) -> bool:
        """Check if file should be processed (exists, is file, debounce check)."""
        if not os.path.exists(file_path):
            return False
            
        if not os.path.isfile(file_path):
            return False
        
        # Debouncing: avoid processing files that were just modified
        now = time.time()
        last_processed = self._last_processed.get(file_path, 0)
        if now - last_processed < self.config.debounce_seconds:
            return False
            
        return True
    
    def _process_file(self, file_path: str):
        """Process a single file through the ingestion pipeline."""
        if not self._should_process_file(file_path):
            return
            
        # Update last processed time
        self._last_processed[file_path] = time.time()
        
        try:
            result = ingest_file(
                file_path=file_path,
                db_path=self.config.db_path,
                source_conversation=self.config.source_conversation
            )
            
            if result.status == 'success':
                print(f"✓ Ingested: {file_path} (ID: {result.file_id})")
            elif result.status == 'skipped':
                print(f"→ Skipped: {file_path} ({result.skipped_reason})")
            else:
                print(f"✗ Error: {file_path} ({result.skipped_reason})")
                
        except Exception as e:
            print(f"✗ Exception processing {file_path}: {e}")
    
    def on_created(self, event):
        """Handle file creation events."""
        if isinstance(event, FileCreatedEvent):
            self._process_file(event.src_path)
    
    def on_modified(self, event):
        """Handle file modification events."""
        if isinstance(event, FileModifiedEvent) and not event.is_directory:
            self._process_file(event.src_path)


def start_watching(config: WatcherConfig) -> Observer:
    """
    Start watching a directory for file changes.
    
    Args:
        config: WatcherConfig with directory and database settings
        
    Returns:
        Observer instance (call .stop() and .join() to clean up)
    """
    if not os.path.exists(config.watch_dir):
        raise ValueError(f"Watch directory does not exist: {config.watch_dir}")
        
    if not os.path.isdir(config.watch_dir):
        raise ValueError(f"Watch path is not a directory: {config.watch_dir}")
    
    # Create event handler
    event_handler = KIPipelineHandler(config)
    
    # Create and configure observer
    observer = Observer()
    observer.schedule(
        event_handler,
        config.watch_dir,
        recursive=config.recursive
    )
    
    # Start watching
    observer.start()
    print(f"🔍 Watching: {config.watch_dir} (recursive={config.recursive})")
    
    return observer


def watch_directory(config: WatcherConfig, duration: Optional[float] = None) -> None:
    """
    Watch a directory for the specified duration (or indefinitely).
    
    Args:
        config: WatcherConfig with directory and database settings
        duration: How long to watch in seconds (None = indefinite)
    """
    observer = start_watching(config)
    
    try:
        if duration:
            time.sleep(duration)
        else:
            # Watch indefinitely until KeyboardInterrupt
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\n⏹ Stopping watcher...")
    finally:
        observer.stop()
        observer.join()
        print("✓ Watcher stopped")
