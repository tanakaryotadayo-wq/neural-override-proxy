"""
Command-line interface for the KI Pipeline.
"""

import argparse
import os
import sys
from pathlib import Path

from .db import init_db, list_files_by_status
from .ingestion import ingest_file, ingest_directory, ensure_directories
from .file_watcher import WatcherConfig, watch_directory


def cmd_init(args):
    """Initialize a new KI Pipeline workspace."""
    base_path = args.base_path or os.getcwd()
    db_path = os.path.join(base_path, 'ki_pipeline.db')
    
    print(f"Initializing KI Pipeline in: {base_path}")
    
    # Create directory structure
    ensure_directories(base_path)
    print("✓ Created directories: raw/, normalized/, ki/, archive/")
    
    # Initialize database
    init_db(db_path)
    print(f"✓ Initialized database: {db_path}")
    
    print("\nKI Pipeline initialized successfully!")
    print("Next steps:")
    print(f"  1. Add files: python -m pipeline ingest <file_or_directory>")
    print(f"  2. Watch directory: python -m pipeline watch <directory>")
    print(f"  3. Check status: python -m pipeline status")


def cmd_ingest(args):
    """Ingest files or directories into the pipeline."""
    db_path = args.db_path or os.path.join(os.getcwd(), 'ki_pipeline.db')
    
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        print("Run 'python -m pipeline init' first")
        sys.exit(1)
    
    for path in args.paths:
        path = os.path.abspath(path)
        
        if not os.path.exists(path):
            print(f"✗ Path does not exist: {path}")
            continue
        
        if os.path.isfile(path):
            # Ingest single file
            result = ingest_file(path, db_path, args.source_conversation)
            if result.status == 'success':
                print(f"✓ Ingested file: {path} (ID: {result.file_id})")
            elif result.status == 'skipped':
                print(f"→ Skipped file: {path} ({result.skipped_reason})")
            else:
                print(f"✗ Error with file: {path} ({result.skipped_reason})")
                
        elif os.path.isdir(path):
            # Ingest directory
            print(f"📁 Ingesting directory: {path} (recursive={args.recursive})")
            results = ingest_directory(path, db_path, args.recursive, args.source_conversation)
            
            success_count = sum(1 for r in results if r.status == 'success')
            skip_count = sum(1 for r in results if r.status == 'skipped')
            error_count = sum(1 for r in results if r.status == 'error')
            
            print(f"  ✓ Successful: {success_count}")
            print(f"  → Skipped: {skip_count}")
            print(f"  ✗ Errors: {error_count}")
            
            if args.verbose and error_count > 0:
                print("\nErrors:")
                for result in results:
                    if result.status == 'error':
                        print(f"  ✗ {result.skipped_reason}")
        else:
            print(f"✗ Unknown path type: {path}")


def cmd_watch(args):
    """Watch a directory for new files."""
    db_path = args.db_path or os.path.join(os.getcwd(), 'ki_pipeline.db')
    
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        print("Run 'python -m pipeline init' first")
        sys.exit(1)
    
    config = WatcherConfig(
        watch_dir=args.directory,
        db_path=db_path,
        recursive=args.recursive,
        source_conversation=args.source_conversation,
        debounce_seconds=args.debounce
    )
    
    try:
        watch_directory(config, duration=args.duration)
    except ValueError as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


def cmd_status(args):
    """Show pipeline status and file counts."""
    db_path = args.db_path or os.path.join(os.getcwd(), 'ki_pipeline.db')
    
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        print("Run 'python -m pipeline init' first")
        sys.exit(1)
    
    # Get file counts by status
    all_files = list_files_by_status(db_path)
    status_counts = {}
    
    for file_record in all_files:
        status = file_record['status']
        status_counts[status] = status_counts.get(status, 0) + 1
    
    print("KI Pipeline Status")
    print("==================")
    print(f"Database: {db_path}")
    print(f"Total files: {len(all_files)}")
    print()
    
    if status_counts:
        print("Files by status:")
        for status in ['pending', 'normalized', 'ki', 'archived']:
            count = status_counts.get(status, 0)
            print(f"  {status:12}: {count:4d}")
        print()
    
    # Show recent files if requested
    if args.recent:
        recent_files = all_files[:args.recent]
        if recent_files:
            print(f"Recent files (last {min(args.recent, len(all_files))}):")
            for file_record in recent_files:
                path_display = file_record['path']
                if len(path_display) > 60:
                    path_display = "..." + path_display[-57:]
                print(f"  [{file_record['status']:10}] {path_display}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="File-first Knowledge Intelligence Pipeline",
        prog="python -m pipeline"
    )
    
    parser.add_argument(
        '--db-path',
        help="Path to SQLite database (default: ./ki_pipeline.db)"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Init command
    init_parser = subparsers.add_parser('init', help='Initialize pipeline workspace')
    init_parser.add_argument(
        'base_path',
        nargs='?',
        help="Base directory for pipeline (default: current directory)"
    )
    
    # Ingest command
    ingest_parser = subparsers.add_parser('ingest', help='Ingest files or directories')
    ingest_parser.add_argument('paths', nargs='+', help='Files or directories to ingest')
    ingest_parser.add_argument(
        '-r', '--recursive',
        action='store_true',
        help='Recursively ingest directories'
    )
    ingest_parser.add_argument(
        '-s', '--source-conversation',
        help='Source conversation identifier'
    )
    ingest_parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed error messages'
    )
    
    # Watch command
    watch_parser = subparsers.add_parser('watch', help='Watch directory for new files')
    watch_parser.add_argument('directory', help='Directory to watch')
    watch_parser.add_argument(
        '-r', '--recursive',
        action='store_true',
        help='Watch subdirectories recursively'
    )
    watch_parser.add_argument(
        '-s', '--source-conversation',
        help='Source conversation identifier for ingested files'
    )
    watch_parser.add_argument(
        '-d', '--duration',
        type=float,
        help='How long to watch in seconds (default: indefinite)'
    )
    watch_parser.add_argument(
        '--debounce',
        type=float,
        default=1.0,
        help='Debounce delay in seconds (default: 1.0)'
    )
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show pipeline status')
    status_parser.add_argument(
        '-r', '--recent',
        type=int,
        default=10,
        help='Show N most recent files (default: 10)'
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Route to appropriate command handler
    if args.command == 'init':
        cmd_init(args)
    elif args.command == 'ingest':
        cmd_ingest(args)
    elif args.command == 'watch':
        cmd_watch(args)
    elif args.command == 'status':
        cmd_status(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
