import os
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple, Union
from pathlib import Path
import json
import hashlib
from datetime import datetime
import re
import numpy as np
import chromadb
from chromadb.utils import embedding_functions
import uuid
from tenacity import retry, stop_after_attempt, wait_exponential
import math
import time
from collections import defaultdict
import shutil  # Add import for directory operations

from src.config import config
from src.utils.logger import logger
from src.utils.rag_utils_improved import (
    clean_text, chunk_text, expand_query, detect_document_type, 
    enhanced_chunk_text, extract_legal_metadata, create_cross_references, 
    normalize_legal_text, enhance_text_for_embedding, word_tokenize,
    NLTK_AVAILABLE, STOPWORDS, SKLEARN_AVAILABLE
)

class RAGDocumentService:
    """Service for handling document processing and retrieval for RAG."""
    
    def __init__(self):
        """Initialize the RAG Document Service."""
        # Use environment variables if available, otherwise use relative paths
        knowledge_base_env = os.getenv("KNOWLEDGE_BASE_DIR")
        self.knowledge_base_dir = Path(knowledge_base_env) if knowledge_base_env else Path(__file__).parent.parent.parent / "knowledge_base"
        
        self.documents = {}
        self.metadata = {}
        self.search_cache = {}
        self.cache_ttl = 3600  # 1 hour cache TTL
        self.last_cache_cleanup = datetime.now()
        
        # Lazy loading - don't initialize embedding function immediately
        # Create placeholders that will be initialized on first use
        self._embedding_function = None
        self._embedding_model_loaded = False
        self._chroma_client = None
        self._documents_collection = None
        
        # Use environment variables if available, otherwise use relative paths
        vector_db_env = os.getenv("VECTOR_DB_PATH")
        self.db_path = Path(vector_db_env) if vector_db_env else Path(__file__).parent.parent.parent / "db" / "chroma_rag"
        
        # Ensure the directory exists
        self.db_path.mkdir(parents=True, exist_ok=True)
        
        # Log path information
        logger.info(f"Using knowledge base directory: {self.knowledge_base_dir}")
        logger.info(f"Using vector database path: {self.db_path}")
        
        # Load documents
        self._load_documents()
    
    @property
    def embedding_function(self):
        """Lazy-loaded embedding function property."""
        if not self._embedding_model_loaded:
            self._load_embedding_function()
        return self._embedding_function
    
    @property
    def chroma_client(self):
        """Lazy-loaded ChromaDB client property."""
        if self._chroma_client is None:
            self._initialize_chromadb()
        return self._chroma_client
    
    @property
    def documents_collection(self):
        """Lazy-loaded documents collection property."""
        # Only try to access collection if we have initialized ChromaDB first
        if self._documents_collection is None and self.chroma_client is not None:
            self._documents_collection = self._get_or_create_collection("documents")
        return self._documents_collection
    
    def _load_embedding_function(self):
        """Lazy loading of the embedding function to save memory until needed."""
        try:
            start_time = time.time()
            logger.info("Initializing embedding function (lazy loading)...")
            
            # Use MiniLM model instead of mpnet for memory efficiency
            # This model has 384 dimensions vs 768 in mpnet, using ~50% less memory
            self._embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            
            self._embedding_model_loaded = True
            load_time = time.time() - start_time
            logger.info(f"RAG embedding function initialized with all-MiniLM-L6-v2 model in {load_time:.2f}s (memory-optimized)")
        except Exception as e:
            logger.error(f"Error initializing RAG embedding function: {e}")
            logger.warning("Vector search will not be available for RAG")
            self._embedding_function = None
            self._embedding_model_loaded = True  # Mark as tried to avoid repeated attempts
    
    def _initialize_chromadb(self):
        """Lazy initialization of ChromaDB client with recovery for database corruption."""
        try:
            start_time = time.time()
            logger.info("Initializing ChromaDB client (lazy loading)...")
            
            self._chroma_client = chromadb.PersistentClient(
                path=str(self.db_path)
            )
            
            init_time = time.time() - start_time
            logger.info(f"RAG ChromaDB initialized successfully in {init_time:.2f}s")
        except Exception as e:
            error_msg = str(e).lower()
            
            # Check for the specific error about table already existing
            if 'table embeddings_queue already exists' in error_msg:
                logger.warning(f"Detected ChromaDB database corruption: {e}")
                
                try:
                    # Implement recovery process - backup and remove the corrupted database
                    recovery_start = time.time()
                    logger.info("Starting ChromaDB recovery process...")
                    
                    # Create a backup directory name with timestamp
                    backup_dir = self.db_path.parent / f"chroma_rag_backup_{int(time.time())}"
                    
                    # Backup existing database if possible (not critical if it fails)
                    try:
                        if self.db_path.exists():
                            logger.info(f"Backing up existing ChromaDB to {backup_dir}")
                            shutil.copytree(self.db_path, backup_dir)
                            logger.info("Backup completed successfully")
                    except Exception as backup_err:
                        logger.warning(f"Could not backup ChromaDB (continuing anyway): {backup_err}")
                    
                    # Remove the corrupted database directory
                    if self.db_path.exists():
                        logger.info(f"Removing corrupted ChromaDB directory: {self.db_path}")
                        shutil.rmtree(self.db_path)
                    
                    # Recreate the directory
                    logger.info("Creating fresh ChromaDB directory")
                    self.db_path.mkdir(parents=True, exist_ok=True)
                    
                    # Try to initialize ChromaDB again with the clean directory
                    logger.info("Reinitializing ChromaDB after recovery")
                    self._chroma_client = chromadb.PersistentClient(
                        path=str(self.db_path)
                    )
                    
                    recovery_time = time.time() - recovery_start
                    logger.info(f"ChromaDB recovery successful in {recovery_time:.2f}s")
                    
                    # Return since we've now successfully initialized
                    return
                except Exception as recovery_err:
                    logger.error(f"ChromaDB recovery process failed: {recovery_err}")
                    # Fall through to the standard error handling below
            
            # If we get here, either it wasn't the specific error or recovery failed
            logger.error(f"Error initializing RAG ChromaDB: {e}")
            logger.warning("Falling back to in-memory storage; vector search will not be available for RAG")
            self._chroma_client = None
    
    def _get_or_create_collection(self, name: str) -> Any:
        """Get or create a ChromaDB collection."""
        if not self.chroma_client or not self.embedding_function:
            logger.warning(f"Cannot create RAG collection {name}: ChromaDB or embedding function not available")
            return None
        
        try:
            # First check if collection exists
            try:
                collection = self.chroma_client.get_collection(name=name)
                logger.info(f"Using existing RAG collection: {name}")
                return collection
            except Exception:
                # Collection doesn't exist, create it
                collection = self.chroma_client.create_collection(
                    name=name,
                    embedding_function=self.embedding_function,
                    metadata={"description": f"RAG documents collection"}
                )
                logger.info(f"Created new RAG collection: {name}")
                return collection
        except Exception as e:
            logger.error(f"Error creating RAG collection {name}: {e}")
            return None
    
    def _load_documents(self) -> None:
        """Load and process all documents from the knowledge base."""
        try:
            # Check if knowledge base directory exists
            if not self.knowledge_base_dir.exists():
                logger.warning(f"Knowledge base directory not found: {self.knowledge_base_dir}")
                return
                
            # Count CSV files
            csv_files = list(self.knowledge_base_dir.glob("*.csv"))
            if not csv_files:
                logger.warning(f"No CSV files found in knowledge base directory: {self.knowledge_base_dir}")
                return
                
            logger.info(f"Found {len(csv_files)} CSV files in knowledge base")
            
            # Load all CSV files from the knowledge base directory
            for file_path in csv_files:
                try:
                    # Special handling for different file formats
                    file_name = file_path.stem.lower()
                    
                    if 'ipc' in file_name:
                        # Special handling for IPC sections that might have inconsistent formats
                        self._process_ipc_document(file_path)
                    else:
                        # Use memory-efficient processing with chunksize
                        self._process_document_in_chunks(file_path)
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
        except Exception as e:
            logger.error(f"Error loading documents for RAG: {e}")
    
    def _process_ipc_document(self, file_path: Path) -> None:
        """Special processing for IPC sections that might have inconsistent formats.
        
        Args:
            file_path: Path to the CSV file
        """
        try:
            # First try standard CSV reading
            df = pd.read_csv(file_path)
            
            # Check if this looks like an IPC file
            source_name = file_path.stem
            logger.info(f"Processing IPC file {source_name} with {len(df)} rows")
            
            # Check if the file has the expected structure
            has_section_column = any(col for col in df.columns if 'section' in col.lower())
            
            if has_section_column:
                # Standard processing for well-structured IPC file
                document_type = 'ipc'  # Force document type
                self._process_document(df, source_name, document_type)
                logger.info(f"Processed structured IPC file {source_name}")
            else:
                # For unstructured files, we need to do special processing
                logger.info(f"Processing unstructured IPC file {source_name}")
                
                # Add fallback processing for unstructured IPC files
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Look for section patterns
                section_pattern = r'(?:Description of IPC Section (\d+)|IPC Section (\d+)|Section (\d+) of (the )?Indian Penal Code)'
                sections = re.finditer(section_pattern, content, re.IGNORECASE)
                
                # Keep track of processed sections
                processed_sections = []
                
                for match in sections:
                    # Extract section number from any of the capture groups
                    section_num = next((g for g in match.groups() if g), '')
                    section_num = re.sub(r'[^\d]', '', section_num)
                    
                    if not section_num or section_num in processed_sections:
                        continue
            
                    # Find the text related to this section
                    section_start = match.start()
                    
                    # Look for the next section start or end of file
                    next_match = re.search(section_pattern, content[section_start + 10:], re.IGNORECASE)
                    if next_match:
                        section_end = section_start + 10 + next_match.start()
                    else:
                        section_end = len(content)
                    
                    # Extract the section text
                    section_text = content[section_start:section_end].strip()
                    
                    # Create a document for this section
                    doc_id = str(uuid.uuid4())
                    metadata = {
                        "source": source_name,
                        "section_number": section_num,
                        "document_type": "ipc",
                        "category": "criminal_law"
                    }
                    
                    # Store in memory
                    self.documents[doc_id] = {
                        "content": section_text,
                        "metadata": metadata,
                        "id": doc_id
                    }
                    
                    # Add to ChromaDB if available
                    if self.documents_collection and self.embedding_function:
                        try:
                            self.documents_collection.add(
                                documents=[section_text],
                                ids=[doc_id],
                                metadatas=[metadata]
                            )
                        except Exception as e:
                            logger.error(f"Error adding section {section_num} to ChromaDB: {e}")
                    
                    # Mark as processed
                    processed_sections.append(section_num)
                    
                logger.info(f"Processed {len(processed_sections)} sections from unstructured IPC file {source_name}")
                
        except Exception as e:
            logger.error(f"Error processing IPC document {file_path}: {e}")
    
    def _process_document_in_chunks(self, file_path: Path) -> None:
        """Process a CSV file in chunks to reduce memory usage.
        
        Args:
            file_path: Path to the CSV file
        """
        try:
            # Get file size to estimate appropriate chunk size
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            
            # Calculate an appropriate chunksize based on file size
            # For very large files, use smaller chunks
            if file_size_mb > 100:
                chunksize = 500  # For huge files
            elif file_size_mb > 50:
                chunksize = 1000
            elif file_size_mb > 10:
                chunksize = 2000
            else:
                chunksize = 5000  # For small files, process larger chunks
            
            source_name = file_path.stem
            logger.info(f"Processing {file_path.name} in chunks of {chunksize} rows")
            
            # First check the file structure from a sample
            sample_df = pd.read_csv(file_path, nrows=5)
            document_type = detect_document_type(sample_df)
            
            # Process file in chunks
            chunks_processed = 0
            total_rows = 0
            
            # Use chunked reading to process large files efficiently
            for chunk_df in pd.read_csv(file_path, chunksize=chunksize):
                if chunk_df.empty:
                    continue
                
                # Process this chunk
                self._process_document(chunk_df, source_name, document_type)
                chunks_processed += 1
                total_rows += len(chunk_df)
                
                # Provide progress updates
                logger.info(f"Processed chunk {chunks_processed} with {len(chunk_df)} rows for {source_name}")
                
                # Force garbage collection after processing large chunks
                if chunks_processed % 5 == 0:
                    import gc
                    gc.collect()
            
            logger.info(f"Finished loading {source_name} with {total_rows} total rows in {chunks_processed} chunks")
            
        except Exception as e:
            logger.error(f"Error processing document in chunks {file_path}: {e}")
    
    def _process_document(self, df: pd.DataFrame, source_name: str, force_document_type: str = None) -> None:
        """Process a document dataframe and add it to the document store.
        
        Args:
            df: DataFrame containing document data
            source_name: Name of the source file
            force_document_type: Optional document type to force
        """
        try:
            # Detect document type if not forced
            document_type = force_document_type or detect_document_type(df)
            logger.debug(f"Document type for {source_name}: {document_type}")
            
            # Create vectors and documents
            vectors = []
            metadata_list = []
            ids = []
            texts = []
            sample_embeddings = []  # For dimensionality reduction setup
            
            # Find columns containing text data
            potential_text_cols = ['content', 'text', 'description', 'body', 'Content', 'Text', 'Description', 'Body']
            text_cols = [col for col in df.columns if col in potential_text_cols]
            
            # If no exact matches, find columns that contain these names
            if not text_cols:
                text_cols = [col for col in df.columns if any(tc.lower() in col.lower() for tc in potential_text_cols)]
            
            # If still no matches, look for the longest string columns
            if not text_cols:
                # Find string columns
                str_cols = [col for col in df.columns if df[col].dtype == 'object']
                
                # Check average string length
                avg_lengths = {}
                for col in str_cols:
                    avg_len = df[col].astype(str).apply(len).mean()
                    avg_lengths[col] = avg_len
                
                # Use columns with longer text if available
                if avg_lengths:
                    # Sort by average length descending
                    sorted_cols = sorted(avg_lengths.items(), key=lambda x: x[1], reverse=True)
                    # Take the top 1-2 columns
                    text_cols = [col for col, _ in sorted_cols[:2]]
            
            # Use batch processing to reduce memory usage while maintaining functionality
            batch_size = 200  # Process 200 rows at a time to maintain performance while reducing memory peaks
            total_rows = len(df)
            for batch_start in range(0, total_rows, batch_size):
                batch_end = min(batch_start + batch_size, total_rows)
                batch_df = df.iloc[batch_start:batch_end]
                
                # Process each row in the batch
                for index, row in batch_df.iterrows():
                    # Combined text from text columns
                    text_parts = []
                    for col in text_cols:
                        if col in row and pd.notna(row[col]) and row[col]:
                            text_parts.append(str(row[col]))
                    
                    if not text_parts:
                        # Skip rows with no text
                        continue
                    
                    # Combined text
                    combined_text = " ".join(text_parts)
                    
                    # For IPC sections, add extra context from other columns
                    if document_type == 'ipc':
                        context_parts = []
                        for col, val in row.items():
                            if col not in text_cols and pd.notna(val) and val:
                                # Only add substantive fields with real content
                                if len(str(val)) > 2 and col.lower() not in ['id', 'index', 'uuid']:
                                    context_parts.append(f"{col}: {val}")
                        
                        # Add context before the main text
                        if context_parts:
                            combined_text = "\n".join(context_parts) + "\n\n" + combined_text
                    
                    # Extract legal metadata
                    metadata = extract_legal_metadata(row, document_type)
                    metadata['source'] = source_name
                    metadata['document_type'] = document_type
                    
                    # Chunk text according to document type
                    chunks = enhanced_chunk_text(combined_text, document_type)
                    
                    if len(chunks) == 0:
                        # Force at least one chunk with cleaned text
                        chunks = [clean_text(combined_text)]
            
            # Process each chunk
            for i, chunk in enumerate(chunks):
                # Create unique document ID
                doc_id = f"{source_name}_{index}_{i}"
                
                # Add chunk metadata
                chunk_metadata = {
                    **metadata,
                    "chunk_index": i,
                    "total_chunks": len(chunks)
                }
                
                # Store in document dict
                self.documents[doc_id] = {
                    "content": chunk,
                    "metadata": chunk_metadata,
                    "id": doc_id
                }
                
                # Add enhanced text for vector embedding
                enhanced_text = enhance_text_for_embedding(chunk, document_type, chunk_metadata)
                
                # Prepare for vector batch insertion
                if self.documents_collection:
                    ids.append(doc_id)
                    texts.append(enhanced_text)  # Use enhanced text for embeddings
                    metadata_list.append(chunk_metadata)
                    
                    # Collect sample embeddings for dimensionality reduction (if not already set up)
                    if len(sample_embeddings) < 200:  # Collect up to 200 samples
                        # Get the vector embedding from the embedding function directly
                        try:
                            if SKLEARN_AVAILABLE and self.embedding_function:
                                embedding = self.embedding_function([enhanced_text])[0]
                                if embedding is not None and len(embedding) > 0:
                                    sample_embeddings.append(embedding)
                        except Exception as e:
                            logger.debug(f"Error getting sample embedding: {e}")
                
                # Periodically add vectors to save memory - add batch to ChromaDB
                if self.documents_collection and texts and (batch_end == total_rows or len(texts) >= 100):
                    try:
                        # Set up dimensionality reduction if we have enough samples
                        if sample_embeddings and len(sample_embeddings) >= 20:
                            from src.utils.rag_utils_improved import setup_dim_reduction
                            setup_dim_reduction(sample_embeddings, target_dim=100)
                            sample_embeddings = []  # Clear samples after setup
                        
                        self.documents_collection.add(
                            ids=ids,
                            documents=texts,
                            metadatas=metadata_list
                        )
                        logger.info(f"Added {len(texts)} vectors to RAG ChromaDB (batch {batch_start+1}-{batch_end} of {total_rows})")
                        # Clear lists to free memory
                        ids = []
                        texts = []
                        metadata_list = []
                    except Exception as e:
                        logger.error(f"Error adding vectors batch to RAG ChromaDB: {e}")
            
            # Process any remaining vectors if batch processing didn't add all
            if self.documents_collection and texts:
                try:
                    self.documents_collection.add(
                        ids=ids,
                        documents=texts,
                        metadatas=metadata_list
                    )
                    logger.info(f"Added {len(texts)} vectors to RAG ChromaDB collection for {source_name}")
                except Exception as e:
                    logger.error(f"Error adding vectors to RAG ChromaDB: {e}")
            
            # Cross-reference documents
            logger.info(f"Creating cross-references for {len(self.documents)} documents")
            self.documents = {doc_id: doc for doc_id, doc in create_cross_references(list(self.documents.values())).items()}
            
        except Exception as e:
            logger.error(f"Error processing document {source_name}: {e}")
    
    def _clean_cache(self) -> None:
        """Clean expired cache entries."""
        now = datetime.now()
        # Only clean cache once per hour
        if (now - self.last_cache_cleanup).total_seconds() < 3600:
            return
            
        expired_keys = []
        for key, (_, timestamp) in self.search_cache.items():
            if (now - timestamp).total_seconds() > self.cache_ttl:
                expired_keys.append(key)
                
        for key in expired_keys:
            self.search_cache.pop(key, None)
            
        self.last_cache_cleanup = now
        logger.debug(f"Cleaned {len(expired_keys)} expired cache entries")
    
    def _keyword_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Perform keyword search on documents."""
        try:
            # Clean and prepare query
            query = clean_text(query.lower())
            query_terms = query.split()
            
            # Check for direct section references
            section_match = re.search(r'(?:section|sec\.?|s\.?)\s*(\d+[A-Za-z]?)', query, re.IGNORECASE)
            
            # Prepare results
            results = []
            
            # Calculate TF-IDF scores for all documents
            for doc_id, doc in self.documents.items():
                content = doc["content"].lower()
                metadata = doc["metadata"]
                
                # Apply filters if provided
                if filters and not self._matches_filters(metadata, filters):
                    continue
                
                # Special handling for section queries
                if section_match:
                    section_num = section_match.group(1)
                    section_clean = re.sub(r'[^\d]', '', section_num)
                    
                    # Look for exact section matches
                    section_in_content = (
                        re.search(fr'\bsection\s+{re.escape(section_num)}\b', content, re.IGNORECASE) or
                        re.search(fr'\bipc\s+{re.escape(section_num)}\b', content, re.IGNORECASE) or
                        re.search(fr'\bipc\s+section\s+{re.escape(section_num)}\b', content, re.IGNORECASE)
                    )
                    
                    # Check metadata for section match
                    section_in_metadata = False
                    if 'section_number' in metadata:
                        metadata_section = str(metadata['section_number'])
                        if metadata_section in [section_num, section_clean]:
                            section_in_metadata = True
                    elif 'Section' in metadata:
                        if section_num in str(metadata['Section']):
                            section_in_metadata = True
                    
                    # If exact section match found, give it a high score
                    if section_in_content or section_in_metadata:
                        results.append({
                            "content": doc["content"],
                            "metadata": doc["metadata"],
                            "score": 1.0,  # Maximum score for direct section matches
                            "id": doc_id,
                            "method": "exact_section_match"
                        })
                    continue
                
                # Calculate matching score (simple TF-based approach)
                matches = 0
                for term in query_terms:
                    if term in content:
                        matches += content.count(term)
                
                # Add to results if at least one match
                if matches > 0:
                    # Calculate a score based on term frequency and document length
                    # Normalize by document length to avoid bias towards longer documents
                    score = matches / (math.log(len(content.split()) + 1))
                    
                    results.append({
                        "content": doc["content"],
                        "metadata": doc["metadata"],
                        "score": score,
                        "id": doc_id,
                        "method": "keyword"
                    })
            
            # Sort by score and limit results
            results = sorted(results, key=lambda x: x["score"], reverse=True)[:limit]
            
            logger.info(f"Keyword search found {len(results)} results for: {query[:50]}...")
            return results
        except Exception as e:
            logger.error(f"Error in keyword search: {e}")
            return []
    
    def _matches_filters(self, metadata: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if a document matches the provided filters."""
        for key, filter_value in filters.items():
            # If the key doesn't exist in metadata, it doesn't match
            if key not in metadata:
                return False
                
            metadata_value = metadata[key]
            
            # Handle different filter types
            if isinstance(filter_value, list):
                # List filter - document must match at least one value in the list
                if metadata_value not in filter_value:
                    return False
            elif isinstance(filter_value, dict) and ("min" in filter_value or "max" in filter_value):
                # Range filter
                try:
                    # Convert values for comparison
                    metadata_value = float(metadata_value) if isinstance(metadata_value, str) else metadata_value
                    
                    if "min" in filter_value and metadata_value < filter_value["min"]:
                        return False
                    if "max" in filter_value and metadata_value > filter_value["max"]:
                        return False
                except (ValueError, TypeError):
                    # If conversion fails, consider it a non-match
                    return False
            elif metadata_value != filter_value:
                # Direct value comparison
                return False
                
        # If we get here, document passed all filters
        return True
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def search_with_vectors(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Search documents using vector embeddings.
        
        Args:
            query: The search query
            limit: Maximum number of results to return
            filters: Optional dictionary of metadata filters
            
        Returns:
            List of document dictionaries
        """
        try:
            # Clean cache periodically
            self._clean_cache()
            
            # Generate cache key
            cache_key = hashlib.md5(f"{query}_{limit}_{json.dumps(filters or {})}".encode()).hexdigest()
            
            # Check cache
            if cache_key in self.search_cache:
                cached_results, timestamp = self.search_cache[cache_key]
                # Check if cache is still valid
                if (datetime.now() - timestamp).total_seconds() < self.cache_ttl:
                    logger.info(f"Returning cached vector search results for: {query[:50]}...")
                    return cached_results
            
            # Check if ChromaDB and embedding function are available
            if not self.documents_collection or not self.embedding_function:
                logger.warning("Vector search not available, falling back to keyword search")
                return self._keyword_search(query, limit, filters)
            
            # Enhance the query for better retrieval in the legal domain
            enhanced_query = enhance_text_for_embedding(query, "unknown")
            
            # Prepare ChromaDB filters in the correct format
            where_filter = None
            if filters:
                # Format filters to ChromaDB's expected format
                where_clauses = []
                for k, v in filters.items():
                    if isinstance(v, list):
                        # Handle multi-value filters (using $in operator)
                        where_clauses.append({k: {"$in": v}})
                    else:
                        # Handle single value filters
                        where_clauses.append({k: v})
                
                # Combine clauses if multiple
                if len(where_clauses) == 1:
                    where_filter = where_clauses[0]
                elif len(where_clauses) > 1:
                    where_filter = {"$and": where_clauses}
            
            # Execute the query
            results = self.documents_collection.query(
                query_texts=[enhanced_query],
                n_results=min(limit * 3, 25),  # Get more results than needed for better filtering
                where=where_filter
            )
            
            # Process the results
            processed_results = []
            seen_content_hashes = set()  # For deduplication
            
            if results and results["documents"] and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    # Get the document ID and metadata
                    doc_id = results["ids"][0][i]
                    metadata = results["metadatas"][0][i] if results["metadatas"] and results["metadatas"][0] else {}
                    distance = results["distances"][0][i] if results["distances"] and results["distances"][0] else 1.0
                    
                    # Convert distance to similarity score (1 - distance)
                    score = 1.0 - distance
                    
                    # Skip very low-similarity results
                    if score < 0.3:  # Minimum threshold for relevance
                        continue
                    
                    # Apply any additional filtering here if needed
                    if filters and not self._matches_filters(metadata, filters):
                        continue
                    
                    # Retrieve the actual document content from memory if available
                    content = doc
                    if doc_id in self.documents:
                        content = self.documents[doc_id]["content"]
                    
                    # Deduplicate by content hash (avoid nearly identical content)
                    content_hash = hashlib.md5(content.encode()).hexdigest()
                    if content_hash in seen_content_hashes:
                        continue
                    seen_content_hashes.add(content_hash)
                    
                    # Add to results
                    processed_results.append({
                            "content": content,
                        "metadata": metadata,
                        "score": float(score),
                        "id": doc_id,
                        "method": "vector"
                    })
            
            # Re-rank results based on both vector similarity and keyword presence
            if processed_results:
                # Extract query keywords (non-stopwords)
                try:
                    query_tokens = word_tokenize(query.lower())
                    keywords = [token for token in query_tokens 
                              if token.isalnum() and token not in STOPWORDS and len(token) > 2]
                except Exception:
                    # Fallback if NLTK resources unavailable
                    keywords = [w.lower() for w in re.findall(r'\b\w{3,}\b', query.lower())]
                
                # Count keyword matches for each result
                for result in processed_results:
                    content_lower = result["content"].lower()
                    keyword_count = sum(1 for keyword in keywords if keyword in content_lower)
                    # Adjust score based on keyword presence (subtle boost)
                    keyword_boost = min(0.1, keyword_count * 0.02)  # Cap the boost at 0.1
                    result["score"] = min(0.99, result["score"] + keyword_boost)  # Cap at 0.99
            
            # Sort by score
            processed_results = sorted(processed_results, key=lambda x: x["score"], reverse=True)
            
            # If no results from vector search, fall back to keyword search
            if not processed_results:
                logger.warning(f"No vector search results for query: {query[:50]}... Falling back to keyword search")
                processed_results = self._keyword_search(query, limit, filters)
            
            # Cache results
            self.search_cache[cache_key] = (processed_results[:limit], datetime.now())
            
            return processed_results[:limit]
            
        except Exception as e:
            logger.error(f"Error in vector search: {e}")
            # Fallback to keyword search
            return self._keyword_search(query, limit, filters)
    
    def hybrid_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None, method: str = "hybrid") -> List[Dict[str, Any]]:
        """
        Perform hybrid search combining vector and keyword search results.
        
        Args:
            query: The search query
            limit: Maximum number of results to return
            filters: Optional dictionary of metadata filters
            method: Search method ("vector", "keyword", or "hybrid")
            
        Returns:
            List of document dictionaries
        """
        try:
            if method == "vector":
                return self.search_with_vectors(query, limit, filters)
            elif method == "keyword":
                return self._keyword_search(query, limit, filters)
            else:  # hybrid
                # Detect query type to optimize search strategy
                query_clean = query.lower().strip()
                
                # Identify different types of legal queries
                sec_pattern = r'(?:section|sec\.?|s\.?)\s*(\d+[A-Za-z]?)'
                article_pattern = r'\b(?:article|art\.?)\s*(\d+[A-Za-z]?)'
                
                # Check for specific legal document references
                section_match = re.search(sec_pattern, query_clean, re.IGNORECASE)
                article_match = re.search(article_pattern, query_clean, re.IGNORECASE)
                
                # Document type indicators
                is_ipc_query = bool(re.search(r'\b(?:ipc|indian\s*penal\s*code)\b', query_clean, re.IGNORECASE))
                is_constitution_query = bool(re.search(r'\b(?:constitution|constitutional|fundamental\s*right)\b', query_clean, re.IGNORECASE))
                
                # Case pattern detection (legal proceedings)
                is_case_query = bool(re.search(r'\bv(?:s|\.)\s', query_clean, re.IGNORECASE) or 
                                    re.search(r'\bversus\b', query_clean, re.IGNORECASE))
                
                # Rights and legal concepts
                is_rights_query = bool(re.search(r'\bright(?:s)?\s+to\b', query_clean, re.IGNORECASE) or
                                      re.search(r'\bfundamental\s+right(?:s)?\b', query_clean, re.IGNORECASE))
                
                logger.info(f"Query classification - IPC: {is_ipc_query}, Constitution: {is_constitution_query}, " 
                          f"Case: {is_case_query}, Rights: {is_rights_query}, "
                          f"Section: {bool(section_match)}, Article: {bool(article_match)}")
                
                # Special handling for IPC section numbers
                special_filters = None
                if section_match and not filters:
                    section_num = section_match.group(1)
                    # Remove any non-numeric characters for better matching
                    section_num_clean = re.sub(r'[^\d]', '', section_num)
                    
                    # Create specific filter for section number
                    if is_ipc_query:
                        special_filters = {"document_type": "ipc", "section_number": section_num_clean}
                    else:
                        # If IPC not explicitly mentioned, try with general section filter
                        special_filters = {"section_number": section_num_clean}
                    
                    logger.info(f"Detected section reference: {section_num} (clean: {section_num_clean})")
                
                elif article_match and not filters:
                    article_num = article_match.group(1)
                    # Remove any non-numeric characters for better matching
                    article_num_clean = re.sub(r'[^\d]', '', article_num)
                    
                    # Create specific filter for article number
                    special_filters = {"document_type": "constitution", "article_number": article_num_clean}
                    logger.info(f"Detected article reference: {article_num} (clean: {article_num_clean})")
                
                # Domain-specific query enhancement
                enhanced_query = query
                
                # For IPC queries, enhance with legal terminology
                if is_ipc_query and section_match:
                    section_num = section_match.group(1)
                    section_clean = re.sub(r'[^\d]', '', section_num)
                    enhanced_query = f"{query} section {section_clean} of indian penal code ipc section {section_clean}"
                    logger.info(f"Enhanced IPC query: {enhanced_query}")
                
                # For constitutional queries
                elif is_constitution_query and article_match:
                    article_num = article_match.group(1)
                    article_clean = re.sub(r'[^\d]', '', article_num)
                    enhanced_query = f"{query} constitution of india article {article_clean} fundamental rights"
                    logger.info(f"Enhanced constitution query: {enhanced_query}")
                
                # For rights-based queries
                elif is_rights_query:
                    enhanced_query = f"{query} fundamental rights constitutional provisions"
                    logger.info(f"Enhanced rights query: {enhanced_query}")
                
                # If using special filters, merge them with existing filters
                search_filters = special_filters if special_filters else filters
                
                # Proceed with original method implementation for direct matching and hybrid search...
                
                # Direct lookup for exact section matches (highest priority)
                direct_matches = []
                if section_match and self.documents:
                    section_num = section_match.group(1)
                    section_clean = re.sub(r'[^\d]', '', section_num)
                    
                    # Try several patterns for direct matching
                    patterns = [
                        fr'\bsection\s+{re.escape(section_num)}\b',
                        fr'\bipc\s+{re.escape(section_num)}\b',
                        fr'\bipc\s+section\s+{re.escape(section_num)}\b',
                        fr'\bsection\s+{re.escape(section_clean)}\b',
                        fr'\bipc\s+{re.escape(section_clean)}\b',
                        fr'\bipc\s+section\s+{re.escape(section_clean)}\b'
                    ]
                    
                    # Check all documents for exact match patterns
                    for doc_id, doc in self.documents.items():
                        content = doc['content'].lower()
                        metadata = doc['metadata']
                        
                        # Look for direct section number matches in metadata
                        section_match_in_metadata = False
                        if 'section_number' in metadata and str(metadata['section_number']) in [section_num, section_clean]:
                            section_match_in_metadata = True
                        elif 'Section' in metadata and section_num in str(metadata['Section']):
                            section_match_in_metadata = True
                        
                        # Look for pattern matches in content
                        pattern_match = any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)
                        
                        if section_match_in_metadata or pattern_match:
                            logger.info(f"Found direct section match for {section_num}")
                            direct_matches.append({
                                "content": doc["content"],
                                "metadata": doc["metadata"],
                                "score": 1.0,  # Maximum score for direct matches
                                "id": doc_id,
                                "method": "exact_match"
                            })
                
                # If we found direct matches, prioritize them
                if direct_matches and is_ipc_query:
                    # Take the top 2 direct matches if we have them
                    top_direct_matches = sorted(direct_matches, 
                                             key=lambda x: len(x['content']),  # Prefer shorter, more focused content
                                             reverse=False)[:2]
                    
                    # For section queries, we might not need additional results
                    if len(top_direct_matches) > 0:
                        remaining_slots = max(1, limit - len(top_direct_matches))
                        logger.info(f"Using {len(top_direct_matches)} direct matches with {remaining_slots} remaining slots")
                    else:
                        remaining_slots = limit
                else:
                    top_direct_matches = []
                    remaining_slots = limit
                
                # Get results from both methods with enhanced limit for better coverage
                vector_limit = max(2, int(remaining_slots * 1.5))  # Get more vector results for reranking
                
                try:
                    # Use enhanced query for vector search
                    vector_results = self.search_with_vectors(enhanced_query, vector_limit, search_filters)
                except Exception as e:
                    logger.error(f"Error in vector search, falling back to keyword search: {e}")
                    vector_results = []
                
                keyword_results = self._keyword_search(query, remaining_slots, search_filters)
                
                # Identify exact matches in keyword results that weren't caught above
                # (for queries like "Section 420", exact matches should be prioritized)
                exact_matches = []
                for kr in keyword_results:
                    # Only check if we don't already have direct matches
                    if not top_direct_matches:
                        # Check for exact section/article matches in content
                        if section_match and re.search(fr'\bsection\s+{section_match.group(1)}\b', 
                                                   kr['content'], re.IGNORECASE):
                            kr['score'] = 1.0  # Boost score for exact section matches
                            kr['method'] = 'exact_match'
                            exact_matches.append(kr)
                        elif article_match and re.search(fr'\barticle\s+{article_match.group(1)}\b', 
                                                      kr['content'], re.IGNORECASE):
                            kr['score'] = 1.0  # Boost score for exact article matches
                            kr['method'] = 'exact_match'
                            exact_matches.append(kr)
                
                # Combine results, giving preference to direct matches first, then exact matches
                combined = top_direct_matches.copy() + exact_matches.copy()
                
                # Add unique vector results
                vector_ids = {r["id"] for r in combined}
                for vr in vector_results:
                    if vr["id"] not in vector_ids:
                        combined.append(vr)
                        vector_ids.add(vr["id"])
                
                # Add remaining unique keyword results
                for kr in keyword_results:
                    if kr["id"] not in vector_ids:
                        # Don't discount keyword scores if we don't have enough results
                        if len(combined) >= limit:
                            kr["score"] = kr["score"] * 0.8  # Discount keyword scores
                        combined.append(kr)
                        vector_ids.add(kr["id"])
                
                # Re-sort combined results by score
                combined = sorted(combined, key=lambda x: x["score"], reverse=True)
                
                # If we don't have enough results, try a direct search for the section content
                if section_match and len(combined) < limit:
                    section_num = section_match.group(1)
                    section_clean = re.sub(r'[^\d]', '', section_num)
                    
                    # Look for section content in raw files
                    try:
                        # Try to find section content in IPC files
                        for file_path in self.knowledge_base_dir.glob("*.csv"):
                            if 'ipc' in file_path.stem.lower():
                                with open(file_path, 'r', encoding='utf-8') as f:
                                    content = f.read()
                                    
                                    # Look for section descriptions
                                    section_pattern = f"(?:Description of IPC Section {section_clean}|Section {section_clean} of IPC|IPC Section {section_clean})"
                                    match = re.search(section_pattern, content, re.IGNORECASE)
                                    
                                    if match:
                                        # Extract the section text - search for the next 1000 chars after match
                                        section_start = match.start()
                                        section_text = content[section_start:section_start + 1000]
                                        
                                        # Create a document for this match if not already in results
                                        doc_id = f"section_{section_clean}_direct"
                                        if doc_id not in vector_ids:
                                            logger.info(f"Found direct file match for Section {section_clean}")
                                            direct_doc = {
                                                "content": section_text,
                                                "metadata": {
                                                    "source": file_path.stem,
                                                    "section_number": section_clean,
                                                    "document_type": "ipc",
                                                    "category": "criminal_law"
                                                },
                                                "score": 0.95,  # High score but below exact matches
                                                "id": doc_id,
                                                "method": "file_direct_match"
                                            }
                                            combined.append(direct_doc)
                                            vector_ids.add(doc_id)
                                            
                                            # Re-sort combined results
                                            combined = sorted(combined, key=lambda x: x["score"], reverse=True)
                    except Exception as e:
                        logger.error(f"Error in direct file search: {e}")
                
                # Ensure some diversity in results by including different document types
                if len(combined) > limit * 2:  # If we have plenty of results to choose from
                    # Get unique document types in results
                    doc_types = set(r['metadata'].get('document_type', 'unknown') for r in combined)
                    
                    # If we have multiple document types, ensure at least one of each type is included
                    if len(doc_types) > 1:
                        # Get top results for each document type
                        type_results = {}
                        for doc_type in doc_types:
                            type_results[doc_type] = next(
                                (r for r in combined if r['metadata'].get('document_type', 'unknown') == doc_type), 
                                None
                            )
                        
                        # Start with one from each type (that exists)
                        diverse_results = [r for r in type_results.values() if r is not None]
                        
                        # Add remaining results by score until we hit the limit
                        remaining_slots = limit - len(diverse_results)
                        if remaining_slots > 0:
                            # Get IDs of results already included
                            included_ids = {r['id'] for r in diverse_results}
                            
                            # Add highest-scoring remaining results
                            for r in combined:
                                if r['id'] not in included_ids and len(diverse_results) < limit:
                                    diverse_results.append(r)
                                    included_ids.add(r['id'])
                        
                        combined = diverse_results
                
                # Check for cross-references in top results
                if combined and limit > 2:
                    # Get IDs of documents already in results
                    result_ids = {r["id"] for r in combined[:limit]}
                    
                    # Look for cross-references in top results
                    cross_refs = []
                    for r in combined[:3]:  # Check only top 3 results for cross-references
                        if 'cross_references' in r['metadata']:
                            # Get cross-referenced document IDs
                            ref_indices = r['metadata']['cross_references']
                            if isinstance(ref_indices, str):
                                # Convert string to list if needed
                                try:
                                    ref_indices = [int(idx.strip()) for idx in ref_indices.split(',')]
                                except ValueError:
                                    ref_indices = []
                            
                            for ref_idx in ref_indices:
                                try:
                                    ref_idx = int(ref_idx)
                                    # If the referenced document exists and isn't already in results
                                    if ref_idx < len(self.documents) and len(cross_refs) < 2:
                                        # Add cross-referenced document
                                        ref_doc = list(self.documents.values())[ref_idx]
                                        if ref_doc['id'] not in result_ids:
                                            ref_doc['score'] = 0.7  # Lower score for cross-references
                                            ref_doc['method'] = 'cross_reference'
                                            cross_refs.append(ref_doc)
                                            # Don't add too many cross-references
                                            if len(cross_refs) >= 2:
                                                break
                                except (ValueError, IndexError):
                                    continue
                    
                    # Add cross-references to results
                    for cr in cross_refs:
                        combined.append(cr)
                    
                    # Re-sort all results
                    combined = sorted(combined, key=lambda x: x["score"], reverse=True)
                
                # Return limited results
                return combined[:limit]
        except Exception as e:
            logger.error(f"Error in hybrid search: {e}")
            # Fallback to keyword search as the most reliable
            return self._keyword_search(query, limit, filters)
    
    def get_relevant_context(self, query: str, limit: int = 4, filters: Optional[Dict[str, Any]] = None, search_method: str = "hybrid") -> str:
        """
        Get relevant context for a query.
        
        Args:
            query: The search query
            limit: Maximum number of results to return
            filters: Optional dictionary of metadata filters
            search_method: Search method to use ("vector", "keyword", or "hybrid")
            
        Returns:
            Formatted context string
        """
        try:
            if not query or not query.strip():
                logger.warning("Empty query provided to get_relevant_context")
                return ""
                
            logger.info(f"Getting relevant context for query: {query[:50]}...")
            
            # Check if we have any documents loaded
            if not self.documents:
                logger.warning("No documents loaded in RAG system")
                return ""
            
            # Expand the query for better retrieval
            expanded_query = expand_query(query)
            logger.debug(f"Expanded query: {expanded_query[:100]}...")
            
            # Use the specified search method with expanded query
            results = self.hybrid_search(expanded_query, limit, filters, search_method)
            
            # If no results with expanded query, try original query
            if not results:
                logger.warning(f"No results with expanded query, trying original query")
                results = self.hybrid_search(query, limit, filters, search_method)
            
            # If still no results with hybrid search, try just keyword
            if not results and search_method == "hybrid":
                logger.warning(f"No hybrid results, falling back to keyword search")
                results = self._keyword_search(query, limit, filters)
            
            # Log the number of results found
            logger.info(f"Found {len(results)} relevant documents for query")
            
            # Format results as context
            context_parts = []
            
            # Check for exact section/article matches first
            exact_matches = [r for r in results if r.get("method") == "exact_match"]
            other_results = [r for r in results if r.get("method") != "exact_match"]
            
            # Put exact matches first
            ordered_results = exact_matches + other_results
            
            # Group results by document type for better context organization
            results_by_type = {}
            for result in ordered_results:
                doc_type = result["metadata"].get("document_type", "unknown")
                if doc_type not in results_by_type:
                    results_by_type[doc_type] = []
                results_by_type[doc_type].append(result)
            
            # Process each document type
            for doc_type, type_results in results_by_type.items():
                # Add a section header for the document type if there are multiple types
                if len(results_by_type) > 1:
                    if doc_type == "constitution":
                        context_parts.append("\n## Constitutional Provisions\n")
                    elif doc_type == "ipc":
                        context_parts.append("\n## Indian Penal Code Sections\n")
                    elif doc_type == "qa":
                        context_parts.append("\n## Legal Q&A Information\n")
                    else:
                        context_parts.append(f"\n## {doc_type.title()} Information\n")
                
                # Format each result in this document type
                for result in type_results:
                    content = result["content"]
                    metadata = result["metadata"]
                    source = metadata.get("source", "Unknown")
                    score = result.get("score", 0.0)
                    method = result.get("method", "unknown")
                    
                    # Create a standardized citation that includes the most relevant metadata
                    citation_parts = []
                    
                    # Primary source information
                    citation_parts.append(f"Source: {source}")
                    
                    # Include search method for transparency
                    if method == "exact_match":
                        citation_parts.append("Match: Exact")
                    elif method == "cross_reference":
                        citation_parts.append("Source: Cross-reference")
                    elif method:
                        citation_parts.append(f"Method: {method}")
                    
                    # Add document-type specific citation information
                    if doc_type == "constitution":
                        # For constitution, prioritize part and article information
                        if "Part" in metadata:
                            citation_parts.append(f"Part: {metadata['Part']}")
                        if "Article" in metadata:
                            citation_parts.append(f"Article: {metadata['Article']}")
                        if "article_number" in metadata:
                            citation_parts.append(f"Article Number: {metadata['article_number']}")
                        if "Title" in metadata:
                            citation_parts.append(f"Title: {metadata['Title']}")
                        
                    elif doc_type == "ipc":
                        # For IPC, prioritize section and offense information
                        if "Section" in metadata:
                            citation_parts.append(f"Section: {metadata['Section']}")
                        elif "section_number" in metadata:
                            citation_parts.append(f"Section: {metadata['section_number']}")
                        if "Offense" in metadata:
                            citation_parts.append(f"Offense: {metadata['Offense']}")
                        if "Chapter" in metadata:
                            citation_parts.append(f"Chapter: {metadata['Chapter']}")
                        if "Punishment" in metadata:
                            # Truncate punishment if too long
                            punishment = metadata['Punishment']
                            if len(punishment) > 50:
                                punishment = punishment[:47] + "..."
                            citation_parts.append(f"Punishment: {punishment}")
                    
                    elif doc_type == "qa":
                        # For Q&A, include topic information
                        if "Topic" in metadata:
                            citation_parts.append(f"Topic: {metadata['Topic']}")
                    
                    # Include cross-reference count if available
                    if "cross_references" in metadata:
                        # If cross_references is a string (new format)
                        if isinstance(metadata["cross_references"], str) and metadata["cross_references"].strip():
                            # Get the count either from cross_references_count or by counting commas
                            if "cross_references_count" in metadata:
                                ref_count = metadata["cross_references_count"]
                            else:
                                ref_count = metadata["cross_references"].count(',') + 1
                            citation_parts.append(f"Related References: {ref_count}")
                        # If cross_references is a list (old format)
                        elif isinstance(metadata["cross_references"], list) and metadata["cross_references"]:
                            citation_parts.append(f"Related References: {len(metadata['cross_references'])}")
                
                    # Include relevance score
                    citation_parts.append(f"Relevance: {score:.2f}")
                    
                    # Include chunk information if available
                    if "chunk_index" in metadata and "total_chunks" in metadata:
                        citation_parts.append(f"Part {metadata['chunk_index']+1} of {metadata['total_chunks']}")
                    
                    # Format citation with brackets
                    citation = f"[{'; '.join(citation_parts)}]\n"
                    
                    # Format the content differently based on document type
                    if doc_type == "qa" and "Question:" in content and "Answer:" in content:
                        # For Q&A, format as question and answer
                        context_parts.append(f"{content}\n{citation}")
                    else:
                        # For other document types, add citation after content
                        context_parts.append(f"{content}\n{citation}")
            
            # Join all context parts
            context = "\n".join(context_parts)
            
            # Log context length
            logger.info(f"Generated context of length {len(context)}")
            
            return context
        except Exception as e:
            logger.error(f"Error getting relevant context for RAG: {e}")
            return ""

    def _get_documents_by_ids(self, ids: List[str]) -> List[Dict[str, Any]]:
        """Get documents by their IDs.
        
        Args:
            ids: List of document IDs
            
        Returns:
            List of document dictionaries
        """
        results = []
        for doc_id in ids:
            if doc_id in self.documents:
                results.append(self.documents[doc_id])
        return results

    def _get_cross_references(self, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get cross-referenced documents.
        
        Args:
            metadata: Document metadata containing cross_references
            
        Returns:
            List of cross-referenced documents
        """
        referenced_docs = []
        
        # Handle the new format where cross_references is a comma-separated string
        if 'cross_references' in metadata:
            # Check if it's a string (new format) and split it
            if isinstance(metadata['cross_references'], str):
                reference_ids = metadata['cross_references'].split(',')
                referenced_docs = self._get_documents_by_ids(reference_ids)
            # Old format where it's a list
            elif isinstance(metadata['cross_references'], list):
                referenced_docs = self._get_documents_by_ids(metadata['cross_references'])
            
        return referenced_docs

# Create singleton instance
rag_document_service = RAGDocumentService()