import unittest
import sys
import os
import gc
import time
import psutil
import numpy as np
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.rag_document_service_improved import RAGDocumentService
from src.utils.rag_utils_improved import reduce_vector_dimension, setup_dim_reduction


class TestMemoryOptimizations(unittest.TestCase):

    def setUp(self):
        # Force garbage collection before each test
        gc.collect()
        self.process = psutil.Process(os.getpid())
        self.initial_memory = self.get_memory_usage()
        print(f"Initial memory usage: {self.initial_memory:.2f} MB")

    def get_memory_usage(self):
        """Get current memory usage in MB"""
        return self.process.memory_info().rss / 1024 / 1024
    
    def test_lazy_loading(self):
        """Test that lazy loading reduces initial memory usage"""
        # Create service without accessing embedding model
        service = RAGDocumentService()
        
        # Memory after initialization without accessing embedding model
        memory_before = self.get_memory_usage()
        
        # Record time before accessing the embedding model
        start_time = time.time()
        
        # Force embedding model loading by accessing the property
        _ = service.embedding_function
        
        # Calculate load time
        load_time = time.time() - start_time
        
        # Memory after accessing embedding model
        memory_after = self.get_memory_usage()
        
        memory_diff = memory_after - memory_before
        
        print(f"Memory before embedding model: {memory_before:.2f} MB")
        print(f"Memory after embedding model: {memory_after:.2f} MB")
        print(f"Memory difference: {memory_diff:.2f} MB")
        print(f"Loading time: {load_time:.2f} seconds")
        
        # We expect embedding model to take some memory when loaded
        self.assertGreater(memory_diff, 20)  # At least 20MB for the model
        
        # Verify that load time is reasonable (less than 5 seconds)
        self.assertLess(load_time, 5)
    
    def test_dimension_reduction(self):
        """Test that dimension reduction works correctly"""
        # Create some random high-dimensional vectors
        original_dim = 384  # Matches the model
        target_dim = 100    # Reduced dimension
        
        # Create 50 random vectors for testing
        test_vectors = [np.random.randn(original_dim).tolist() for _ in range(50)]
        
        # Setup the dimension reduction
        result = setup_dim_reduction(test_vectors, target_dim=target_dim)
        
        # Should return True if successful
        self.assertTrue(result)
        
        # Test reducing a single vector
        original_vector = np.random.randn(original_dim).tolist()
        reduced_vector = reduce_vector_dimension(original_vector)
        
        # Check that dimensions are reduced
        self.assertEqual(len(reduced_vector), target_dim)
        
        # Test memory savings
        original_size = sys.getsizeof(original_vector)
        reduced_size = sys.getsizeof(reduced_vector)
        
        memory_savings = 1 - (reduced_size / original_size)
        print(f"Original vector size: {original_size} bytes")
        print(f"Reduced vector size: {reduced_size} bytes")
        print(f"Memory savings: {memory_savings:.2%}")
        
        # We expect significant memory savings
        self.assertGreater(memory_savings, 0.5)  # At least 50% reduction
    
    def test_document_chunk_processing(self):
        """Test that document processing in chunks works correctly"""
        # Create a synthetic test CSV
        test_dir = Path(__file__).parent / "test_data"
        test_dir.mkdir(exist_ok=True)
        
        test_csv = test_dir / "test_document.csv"
        
        # Create a CSV file with enough rows to trigger chunking
        with open(test_csv, 'w') as f:
            f.write("content,type,section\n")
            for i in range(1000):  # 1000 rows should trigger chunking
                f.write(f"This is test content {i},legal,{i}\n")
        
        # Process the document
        service = RAGDocumentService()
        
        # Memory before processing
        memory_before = self.get_memory_usage()
        
        # Monkey patch the _load_documents method to only process our test file
        original_load_documents = service._load_documents
        service._load_documents = lambda: None
        
        # Process our test document
        service._process_document_in_chunks(test_csv)
        
        # Memory after processing
        memory_after = self.get_memory_usage()
        
        # Restore original method
        service._load_documents = original_load_documents
        
        # Clean up
        if test_csv.exists():
            test_csv.unlink()
        
        # Calculate memory usage
        memory_increase = memory_after - memory_before
        
        print(f"Memory before processing: {memory_before:.2f} MB")
        print(f"Memory after processing: {memory_after:.2f} MB")
        print(f"Memory increase: {memory_increase:.2f} MB")
        
        # We expect some memory increase but not too much due to chunking
        # For 1000 documents, memory increase should be reasonable
        self.assertLess(memory_increase, 100)  # Less than 100MB for 1000 rows


if __name__ == '__main__':
    unittest.main() 