"""
Tests for the ingestion module.
"""

import os
import tempfile
import sqlite3
import pytest
from pathlib import Path

from pipeline.ingestion import (
    IngestResult, ensure_directories, compute_hash, ingest_file, ingest_directory
)
from pipeline.db import init_db, get_file_by_hash, list_files_by_status


class TestComputeHash:
    """Test hash computation."""
    
    def test_compute_hash_basic(self):
        """Test basic hash computation."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("Hello, World!")
            temp_path = f.name
        
        try:
            hash_value = compute_hash(temp_path)
            # SHA-256 of "Hello, World!" 
            expected = "dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f"
            assert hash_value == expected
        finally:
            os.unlink(temp_path)
    
    def test_compute_hash_empty_file(self):
        """Test hash of empty file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
        
        try:
            hash_value = compute_hash(temp_path)
            # SHA-256 of empty file
            expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            assert hash_value == expected
        finally:
            os.unlink(temp_path)
    
    def test_compute_hash_large_file(self):
        """Test hash computation for larger files."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            # Write 10KB of data
            content = "A" * 10240
            f.write(content)
            temp_path = f.name
        
        try:
            hash_value = compute_hash(temp_path)
            assert len(hash_value) == 64  # SHA-256 is 256 bits = 64 hex chars
            assert hash_value.isalnum()
        finally:
            os.unlink(temp_path)
    
    def test_compute_hash_nonexistent_file(self):
        """Test error handling for nonexistent files."""
        with pytest.raises(ValueError, match="Cannot read file"):
            compute_hash("/nonexistent/file/path")


class TestEnsureDirectories:
    """Test directory creation."""
    
    def test_ensure_directories_creates_all(self):
        """Test that all required directories are created."""
        with tempfile.TemporaryDirectory() as temp_dir:
            ensure_directories(temp_dir)
            
            expected_dirs = ['raw', 'normalized', 'ki', 'archive']
            for dir_name in expected_dirs:
                dir_path = os.path.join(temp_dir, dir_name)
                assert os.path.exists(dir_path)
                assert os.path.isdir(dir_path)
    
    def test_ensure_directories_idempotent(self):
        """Test that calling ensure_directories multiple times is safe."""
        with tempfile.TemporaryDirectory() as temp_dir:
            ensure_directories(temp_dir)
            ensure_directories(temp_dir)  # Should not raise
            
            # Directories should still exist
            expected_dirs = ['raw', 'normalized', 'ki', 'archive']
            for dir_name in expected_dirs:
                dir_path = os.path.join(temp_dir, dir_name)
                assert os.path.exists(dir_path)
                assert os.path.isdir(dir_path)


class TestIngestFile:
    """Test file ingestion."""
    
    def test_ingest_file_success(self):
        """Test successful file ingestion."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test file
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, 'w') as f:
                f.write("Test content")
            
            # Create database
            db_path = os.path.join(temp_dir, "test.db")
            
            # Ingest file
            result = ingest_file(test_file, db_path)
            
            assert result.status == 'success'
            assert result.file_id is not None
            assert result.skipped_reason is None
    
    def test_ingest_file_idempotent_by_hash(self):
        """Test that ingesting the same content twice skips the second time."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create two files with same content
            test_file1 = os.path.join(temp_dir, "test1.txt")
            test_file2 = os.path.join(temp_dir, "test2.txt")
            content = "Identical content"
            
            with open(test_file1, 'w') as f:
                f.write(content)
            with open(test_file2, 'w') as f:
                f.write(content)
            
            db_path = os.path.join(temp_dir, "test.db")
            
            # Ingest first file
            result1 = ingest_file(test_file1, db_path)
            assert result1.status == 'success'
            
            # Ingest second file with same content
            result2 = ingest_file(test_file2, db_path)
            assert result2.status == 'skipped'
            assert 'same content already exists' in result2.skipped_reason
    
    def test_ingest_file_idempotent_by_path(self):
        """Test that ingesting the same path twice skips the second time."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, 'w') as f:
                f.write("Test content")
            
            db_path = os.path.join(temp_dir, "test.db")
            
            # Ingest same file twice
            result1 = ingest_file(test_file, db_path)
            result2 = ingest_file(test_file, db_path)
            
            assert result1.status == 'success'
            assert result2.status == 'skipped'
            assert 'path already tracked' in result2.skipped_reason
    
    def test_ingest_nonexistent_file(self):
        """Test error handling for nonexistent files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "test.db")
            nonexistent_file = "/path/that/does/not/exist"
            
            result = ingest_file(nonexistent_file, db_path)
            
            assert result.status == 'error'
            assert 'does not exist' in result.skipped_reason
    
    def test_ingest_directory_as_file(self):
        """Test error handling when trying to ingest a directory as a file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "test.db")
            
            result = ingest_file(temp_dir, db_path)
            
            assert result.status == 'error'
            assert 'not a file' in result.skipped_reason
    
    def test_ingest_file_with_source_conversation(self):
        """Test ingesting file with source conversation metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, 'w') as f:
                f.write("Test content")
            
            db_path = os.path.join(temp_dir, "test.db")
            source_conv = "conversation_123"
            
            result = ingest_file(test_file, db_path, source_conversation=source_conv)
            
            assert result.status == 'success'
            
            # Verify source conversation was stored
            file_record = get_file_by_hash(db_path, compute_hash(test_file))
            assert file_record['source_conversation'] == source_conv


class TestIngestDirectory:
    """Test directory ingestion."""
    
    def test_ingest_directory_non_recursive(self):
        """Test non-recursive directory ingestion."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create files and subdirectory
            file1 = os.path.join(temp_dir, "file1.txt")
            file2 = os.path.join(temp_dir, "file2.txt")
            subdir = os.path.join(temp_dir, "subdir")
            os.makedirs(subdir)
            file3 = os.path.join(subdir, "file3.txt")
            
            with open(file1, 'w') as f:
                f.write("Content 1")
            with open(file2, 'w') as f:
                f.write("Content 2")
            with open(file3, 'w') as f:
                f.write("Content 3")
            
            db_path = os.path.join(temp_dir, "test.db")
            
            results = ingest_directory(temp_dir, db_path, recursive=False)
            
            # Should process only files in root, not subdirectory
            success_results = [r for r in results if r.status == 'success']
            assert len(success_results) == 2
    
    def test_ingest_directory_recursive(self):
        """Test recursive directory ingestion."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create files and nested subdirectories
            file1 = os.path.join(temp_dir, "file1.txt")
            subdir1 = os.path.join(temp_dir, "subdir1")
            subdir2 = os.path.join(subdir1, "subdir2")
            os.makedirs(subdir2)
            file2 = os.path.join(subdir1, "file2.txt")
            file3 = os.path.join(subdir2, "file3.txt")
            
            with open(file1, 'w') as f:
                f.write("Content 1")
            with open(file2, 'w') as f:
                f.write("Content 2")
            with open(file3, 'w') as f:
                f.write("Content 3")
            
            db_path = os.path.join(temp_dir, "test.db")
            
            results = ingest_directory(temp_dir, db_path, recursive=True)
            
            # Should process all files recursively
            success_results = [r for r in results if r.status == 'success']
            assert len(success_results) == 3
    
    def test_ingest_nonexistent_directory(self):
        """Test error handling for nonexistent directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "test.db")
            nonexistent_dir = "/path/that/does/not/exist"
            
            results = ingest_directory(nonexistent_dir, db_path)
            
            assert len(results) == 1
            assert results[0].status == 'error'
            assert 'does not exist' in results[0].skipped_reason


class TestDatabaseOperations:
    """Test database operations through ingestion."""
    
    def test_database_initialization(self):
        """Test that database is properly initialized."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, 'w') as f:
                f.write("Test content")
            
            db_path = os.path.join(temp_dir, "test.db")
            
            # Database shouldn't exist initially
            assert not os.path.exists(db_path)
            
            # Ingest file (should create database)
            result = ingest_file(test_file, db_path)
            assert result.status == 'success'
            
            # Database should now exist
            assert os.path.exists(db_path)
            
            # Verify we can query the database
            files = list_files_by_status(db_path)
            assert len(files) == 1
            assert files[0]['status'] == 'pending'
    
    def test_file_status_tracking(self):
        """Test that file status is properly tracked."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, 'w') as f:
                f.write("Test content")
            
            db_path = os.path.join(temp_dir, "test.db")
            
            result = ingest_file(test_file, db_path)
            assert result.status == 'success'
            
            # Check status in database
            pending_files = list_files_by_status(db_path, 'pending')
            assert len(pending_files) == 1
            assert pending_files[0]['id'] == result.file_id
            
            # Check other statuses are empty
            for status in ['normalized', 'ki', 'archived']:
                status_files = list_files_by_status(db_path, status)
                assert len(status_files) == 0


class TestEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_ingest_file_with_unicode_content(self):
        """Test ingesting files with unicode content."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "unicode_test.txt")
            unicode_content = "Hello 🌍 Мир नमस्ते 世界"
            
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(unicode_content)
            
            db_path = os.path.join(temp_dir, "test.db")
            
            result = ingest_file(test_file, db_path)
            assert result.status == 'success'
    
    def test_ingest_file_with_special_characters_in_path(self):
        """Test ingesting files with special characters in file path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # File with spaces and special characters
            test_file = os.path.join(temp_dir, "file with spaces & chars!.txt")
            
            with open(test_file, 'w') as f:
                f.write("Content")
            
            db_path = os.path.join(temp_dir, "test.db")
            
            result = ingest_file(test_file, db_path)
            assert result.status == 'success'
    
    def test_concurrent_access_simulation(self):
        """Test handling of potential concurrent access issues."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, 'w') as f:
                f.write("Test content")
            
            db_path = os.path.join(temp_dir, "test.db")
            
            # Initialize database first
            init_db(db_path)
            
            # Try to ingest the same file multiple times rapidly
            results = []
            for i in range(5):
                result = ingest_file(test_file, db_path)
                results.append(result)
            
            # First should succeed, rest should be skipped
            assert results[0].status == 'success'
            for result in results[1:]:
                assert result.status == 'skipped'
