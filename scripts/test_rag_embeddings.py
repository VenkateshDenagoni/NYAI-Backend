#!/usr/bin/env python3
"""
Test script for evaluating the improved RAG embeddings.

This script tests the enhanced embedding strategies for different types of legal queries
and compares them with baseline embeddings.
"""

import os
import sys
import time
import argparse
from typing import List, Dict, Any, Optional
import json
from pathlib import Path

# Ensure parent directory is in path for imports
sys.path.append(str(Path(__file__).parent.parent))

from src.services.rag_document_service_improved import rag_document_service
from src.utils.rag_utils_improved import enhance_text_for_embedding, normalize_legal_text
from src.utils.logger import logger

# Set of test queries covering different legal domains
TEST_QUERIES = [
    # IPC Sections
    "What is the punishment for theft under Section 378 of IPC?",
    "Explain Section 302 of IPC related to murder",
    "What constitutes criminal conspiracy under IPC?",
    
    # Constitutional articles
    "Explain fundamental rights in Article 21",
    "What does Article 14 of Indian Constitution state about equality?",
    "How does Article 32 protect fundamental rights?",
    
    # Legal concepts
    "What is habeas corpus in Indian law?",
    "Explain the concept of double jeopardy",
    "What are the elements of a valid contract?",
    
    # Complex questions
    "Can a minor enter into a contract?",
    "What is the difference between IPC Section 299 and 300?",
    "What are the limitations on freedom of speech in India?"
]

def print_header(text: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(f" {text} ".center(80, "="))
    print("=" * 80 + "\n")

def test_enhanced_embeddings() -> None:
    """Test the enhanced embedding strategies."""
    print_header("TESTING ENHANCED EMBEDDINGS")
    
    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"\n[{i}/{len(TEST_QUERIES)}] Query: {query}")
        
        # Original query without enhancement
        print("\nOriginal Query:")
        print(f"  {query}")
        
        # Normalized query
        normalized = normalize_legal_text(query)
        print("\nNormalized Query:")
        print(f"  {normalized}")
        
        # Enhanced query for embedding
        enhanced = enhance_text_for_embedding(query)
        print("\nEnhanced Query for Embedding:")
        print(f"  {enhanced}")
        
        # Run search with standard method
        print("\nStandard Vector Search Results:")
        try:
            start_time = time.time()
            vector_results = rag_document_service.search_with_vectors(query, limit=3)
            vector_time = time.time() - start_time
            
            if vector_results:
                for j, result in enumerate(vector_results, 1):
                    print(f"  Result {j} (Score: {result['score']:.4f}):")
                    print(f"  Source: {result['metadata'].get('source', 'Unknown')}")
                    content_preview = result['content'][:100] + "..." if len(result['content']) > 100 else result['content']
                    print(f"  Preview: {content_preview}")
                print(f"\n  Retrieved in {vector_time:.4f} seconds")
            else:
                print("  No results found")
        except Exception as e:
            print(f"  Error in vector search: {e}")
        
        # Run search with hybrid method
        print("\nHybrid Search Results:")
        try:
            start_time = time.time()
            hybrid_results = rag_document_service.hybrid_search(query, limit=3)
            hybrid_time = time.time() - start_time
            
            if hybrid_results:
                for j, result in enumerate(hybrid_results, 1):
                    print(f"  Result {j} (Score: {result['score']:.4f}, Method: {result.get('method', 'unknown')}):")
                    print(f"  Source: {result['metadata'].get('source', 'Unknown')}")
                    content_preview = result['content'][:100] + "..." if len(result['content']) > 100 else result['content']
                    print(f"  Preview: {content_preview}")
                print(f"\n  Retrieved in {hybrid_time:.4f} seconds")
            else:
                print("  No results found")
        except Exception as e:
            print(f"  Error in hybrid search: {e}")
        
        print("\n" + "-" * 80)
        
        # Wait a moment to not overload the system
        time.sleep(0.5)

def evaluate_context_generation(query: str, methods: List[str] = ["vector", "keyword", "hybrid"]) -> None:
    """Evaluate context generation for a single query using different methods."""
    print_header(f"EVALUATING CONTEXT FOR: {query}")
    
    for method in methods:
        print(f"\nMethod: {method.upper()}")
        
        try:
            start_time = time.time()
            context = rag_document_service.get_relevant_context(query, limit=4, search_method=method)
            elapsed = time.time() - start_time
            
            print(f"\nGenerated context ({len(context)} chars, {elapsed:.4f} seconds):\n")
            print(context)
            
        except Exception as e:
            print(f"Error generating context: {e}")
        
        print("\n" + "-" * 80)

def main() -> None:
    """Main function to run the tests."""
    parser = argparse.ArgumentParser(description="Test RAG embedding improvements")
    parser.add_argument("--query", type=str, help="Single query to test")
    parser.add_argument("--context", action="store_true", help="Test context generation")
    parser.add_argument("--method", type=str, choices=["vector", "keyword", "hybrid"], 
                       default="hybrid", help="Search method to use")
    
    args = parser.parse_args()
    
    if args.query and args.context:
        # Test context generation for a single query
        evaluate_context_generation(args.query, [args.method])
    elif args.query:
        # Add the query to our test set temporarily
        TEST_QUERIES.insert(0, args.query)
        test_enhanced_embeddings()
    else:
        # Run all tests
        test_enhanced_embeddings()

if __name__ == "__main__":
    main() 