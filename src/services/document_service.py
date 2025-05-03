import os
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import json
import hashlib
from datetime import datetime, timedelta
import re
from collections import defaultdict
import numpy as np
import chromadb
from chromadb.utils import embedding_functions
import uuid

from src.config import config
from src.utils.logger import logger

class DocumentService:
    """Service for handling legal document processing and retrieval."""
    
    def __init__(self):
        """Initialize the Document Service."""
        self.knowledge_base_dir = Path(__file__).parent.parent.parent / "knowledge_base"
        self.documents = {}
        self.metadata = {}
        self.search_cache = {}
        self.last_cache_cleanup = datetime.now()
        
        # First set up embedding function BEFORE ChromaDB initialization
        try:
            self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            logger.info("Embedding function initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing embedding function: {e}")
            logger.warning("Vector search will not be available")
            self.embedding_function = None
        
        # Initialize ChromaDB only after embedding function is set up
        try:
            self.chroma_client = chromadb.PersistentClient(
                path=str(Path(__file__).parent.parent.parent / "db" / "chroma")
            )
            
            # Only create collections if embedding function is available
            if self.embedding_function:
                # Create collections if they don't exist
                self.constitution_collection = self._get_or_create_collection("constitution")
                self.ipc_collection = self._get_or_create_collection("ipc")
                self.additional_laws_collection = self._get_or_create_collection("additional_laws")
                logger.info("ChromaDB collections initialized successfully")
            else:
                logger.warning("Skipping ChromaDB collection creation due to missing embedding function")
                self.constitution_collection = None
                self.ipc_collection = None
                self.additional_laws_collection = None
            
            logger.info("ChromaDB initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing ChromaDB: {e}")
            logger.warning("Falling back to in-memory storage; vector search will not be available")
            self.chroma_client = None
            self.constitution_collection = None
            self.ipc_collection = None
            self.additional_laws_collection = None
        
        self._load_documents()
    
    def _get_or_create_collection(self, name: str) -> Any:
        """Get or create a ChromaDB collection."""
        if not self.chroma_client or not self.embedding_function:
            logger.warning(f"Cannot create collection {name}: ChromaDB or embedding function not available")
            return None
        
        try:
            return self.chroma_client.get_or_create_collection(
                name=name,
                embedding_function=self.embedding_function,
                metadata={"description": f"Legal documents for {name}"}
            )
        except Exception as e:
            logger.error(f"Error creating collection {name}: {e}")
            return None
    
    def _load_documents(self) -> None:
        """Load and process all documents from the knowledge base."""
        try:
            # Load Indian Constitution
            constitution_path = self.knowledge_base_dir / "indian_constitution.csv"
            if constitution_path.exists():
                constitution_df = pd.read_csv(constitution_path)
                self._validate_constitution_df(constitution_df)
                self._process_constitution(constitution_df)
                logger.info(f"Loaded Indian Constitution with {len(constitution_df)} articles")
            
            # Load IPC Sections
            ipc_path = self.knowledge_base_dir / "ipc_sections.csv"
            if ipc_path.exists():
                ipc_df = pd.read_csv(ipc_path)
                self._validate_ipc_df(ipc_df)
                self._process_ipc(ipc_df)
                logger.info(f"Loaded IPC with {len(ipc_df)} sections")
            
            # Load Additional Laws
            laws_path = self.knowledge_base_dir / "Laws and Constitution of India_Cleanned.csv"
            if laws_path.exists():
                laws_df = pd.read_csv(laws_path)
                self._validate_laws_df(laws_df)
                self._process_additional_laws(laws_df)
                logger.info(f"Loaded additional laws with {len(laws_df)} entries")
            
            # Create search index for keyword search
            self._create_search_index()
            
            # Check for duplicates
            self._check_duplicates()
            
        except pd.errors.EmptyDataError:
            logger.error("One or more CSV files are empty")
            raise
        except pd.errors.ParserError:
            logger.error("Error parsing CSV files")
            raise
        except Exception as e:
            logger.error(f"Error loading documents: {e}")
            raise
    
    def _validate_constitution_df(self, df: pd.DataFrame) -> None:
        """Validate constitution dataframe structure."""
        required_columns = ['Part No.', 'Article No.', 'Article Heading', 'Article Description']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns in constitution CSV: {missing_columns}")

    def _validate_ipc_df(self, df: pd.DataFrame) -> None:
        """Validate IPC dataframe structure."""
        required_columns = ['Section', 'Description', 'Offense', 'Punishment']
        
        # Check if we have any of these columns
        if not any(col in df.columns for col in required_columns):
            # Alternative column structure in some IPC CSVs
            alternative_columns = ['Description', 'Offense', 'Punishment', 'Section']
            missing_columns = [col for col in alternative_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns in IPC CSV: {missing_columns}")
        else:
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns in IPC CSV: {missing_columns}")

    def _validate_laws_df(self, df: pd.DataFrame) -> None:
        """Validate additional laws dataframe structure."""
        required_columns = ['instruction', 'input', 'output']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns in laws CSV: {missing_columns}")

    def _check_duplicates(self) -> None:
        """Check for duplicate document entries."""
        section_counts = {}
        for doc_id, doc in self.documents.items():
            if doc['metadata']['type'] == 'ipc_section':
                section = doc['metadata']['section']
                if section in section_counts:
                    logger.warning(f"Duplicate IPC section found: {section}")
                    section_counts[section] += 1
                else:
                    section_counts[section] = 1

    def _create_search_index(self) -> None:
        """Create an inverted index for faster searching."""
        self.search_index = defaultdict(list)
        legal_terms = set()  # Track legal terms for better search
        
        for doc_id, doc in self.documents.items():
            # Tokenize content with legal-specific handling
            content = doc['content'].lower()
            
            # Extract legal terms (e.g., "IPC Section 302", "Article 21")
            legal_terms.update(re.findall(r'(?:ipc|article|section)\s+\d+', content))
            
            # Basic word tokenization
            words = re.findall(r'\w+', content)
            
            # Add to index
            for term in set(words + list(legal_terms)):  # Combine regular words and legal terms
                self.search_index[term].append(doc_id)
                
                # Add variations of legal terms
                if term.startswith(('ipc', 'article', 'section')):
                    # Add without spaces
                    self.search_index[term.replace(' ', '')].append(doc_id)
                    # Add with hyphen
                    self.search_index[term.replace(' ', '-')].append(doc_id)

    def _process_constitution(self, df: pd.DataFrame) -> None:
        """Process the Indian Constitution CSV file."""
        documents = []
        ids = []
        metadatas = []
        
        # Track seen document IDs to prevent duplicates
        seen_ids = set()
        
        for _, row in df.iterrows():
            try:
                part_no = row['Part No.']
                article_no = str(row['Article No.']).strip()
                heading = row['Article Heading']
                description = row['Article Description']
                
                # Clean up article number to extract just the number
                article_num = re.search(r'\d+[A-Z]*', article_no)
                if article_num:
                    article_num = article_num.group(0)
                else:
                    article_num = article_no.replace('\n', '').replace('Article', '').strip()
                
                # Create a unique ID for this article
                doc_id = f"constitution_part{part_no}_article{article_num}"
                
                # Ensure ID is truly unique by adding a suffix if needed
                original_doc_id = doc_id
                counter = 1
                while doc_id in seen_ids:
                    doc_id = f"{original_doc_id}_{counter}"
                    counter += 1
                
                # Add to seen IDs
                seen_ids.add(doc_id)
                
                # Store in memory
                self.documents[doc_id] = {
                    'content': description,
                    'metadata': {
                        'source': 'Indian Constitution',
                        'part': part_no,
                        'article': article_num,
                        'heading': heading,
                        'type': 'constitutional_article',
                        'last_accessed': None,
                        'access_count': 0
                    }
                }
                
                # Prepare for ChromaDB
                if self.constitution_collection:
                    documents.append(description)
                    ids.append(doc_id)
                    metadatas.append({
                        'source': 'Indian Constitution',
                        'part': str(part_no),
                        'article': article_num,
                        'heading': heading,
                        'type': 'constitutional_article'
                    })
            except Exception as e:
                logger.warning(f"Error processing Constitution article, skipping row: {e}")
        
        # Add to ChromaDB in batches
        if self.constitution_collection and documents and self.embedding_function:
            try:
                # Clear existing documents
                try:
                    self.constitution_collection.delete(where={'type': 'constitutional_article'})
                except Exception as del_e:
                    logger.warning(f"Error clearing existing constitution articles: {del_e}")
                
                # Log unique vs total count for debugging
                logger.info(f"Preparing to add {len(documents)} constitution articles to ChromaDB (unique IDs: {len(set(ids))})")
                
                # Check for duplicate IDs
                id_counts = {}
                for doc_id in ids:
                    id_counts[doc_id] = id_counts.get(doc_id, 0) + 1
                
                duplicates = [doc_id for doc_id, count in id_counts.items() if count > 1]
                if duplicates:
                    logger.warning(f"Found {len(duplicates)} duplicate document IDs in constitution data: {duplicates[:5]}" + ("..." if len(duplicates) > 5 else ""))
                
                # Add in batches of 100
                batch_size = 100
                total_added = 0
                
                for i in range(0, len(documents), batch_size):
                    try:
                        batch_end = min(i + batch_size, len(documents))
                        batch_docs = documents[i:batch_end]
                        batch_ids = ids[i:batch_end]
                        batch_meta = metadatas[i:batch_end]
                        
                        # Double-check this batch for duplicates
                        batch_set = set()
                        unique_batch_docs = []
                        unique_batch_ids = []
                        unique_batch_meta = []
                        
                        for j, doc_id in enumerate(batch_ids):
                            if doc_id not in batch_set:
                                batch_set.add(doc_id)
                                unique_batch_docs.append(batch_docs[j])
                                unique_batch_ids.append(batch_ids[j])
                                unique_batch_meta.append(batch_meta[j])
                        
                        if len(unique_batch_ids) < len(batch_ids):
                            logger.warning(f"Removed {len(batch_ids) - len(unique_batch_ids)} duplicate IDs from batch {i//batch_size + 1}")
                        
                        # Only add if we have documents
                        if unique_batch_docs:
                            self.constitution_collection.add(
                                documents=unique_batch_docs,
                                ids=unique_batch_ids,
                                metadatas=unique_batch_meta
                            )
                            total_added += len(unique_batch_docs)
                    except Exception as batch_e:
                        logger.error(f"Error adding batch {i//batch_size + 1} to constitution collection: {batch_e}")
                
                logger.info(f"Successfully added {total_added} constitution articles to ChromaDB")
            except Exception as e:
                logger.error(f"Error adding constitution articles to ChromaDB: {e}")
    
    def _process_ipc(self, df: pd.DataFrame) -> None:
        """Process the IPC CSV file."""
        documents = []
        ids = []
        metadatas = []
        
        # Track seen document IDs to prevent duplicates
        seen_ids = set()
        
        # Check if we need to adjust columns
        if 'Section' not in df.columns and 'Description' in df.columns and 'Punishment' in df.columns:
            # Handle columns in a different order
            section_col = df.columns[-1]  # Assuming Section is the last column
            description_col = 'Description'
            offense_col = 'Offense'
            punishment_col = 'Punishment'
        else:
            section_col = 'Section'
            description_col = 'Description'
            offense_col = 'Offense'
            punishment_col = 'Punishment'
        
        for _, row in df.iterrows():
            # Extract values with error handling
            try:
                section = str(row[section_col])
                description = str(row[description_col])
                offense = str(row[offense_col]) if offense_col in df.columns else ""
                punishment = str(row[punishment_col]) if punishment_col in df.columns else ""
                
                # Clean up section ID if needed
                section_id = section.replace(' ', '_').replace('.', '_')
                if not section_id.startswith('IPC_') and not section_id.startswith('ipc_'):
                    section_id = f"IPC_{section_id}"
                
                # Create a unique ID for this section
                doc_id = section_id
                
                # Ensure ID is truly unique by adding a suffix if needed
                original_doc_id = doc_id
                counter = 1
                while doc_id in seen_ids:
                    doc_id = f"{original_doc_id}_{counter}"
                    counter += 1
                
                # Add to seen IDs
                seen_ids.add(doc_id)
                
                # Store in memory
                self.documents[doc_id] = {
                    'content': description,
                    'metadata': {
                        'source': 'Indian Penal Code',
                        'section': section,
                        'offense': offense,
                        'punishment': punishment,
                        'type': 'ipc_section',
                        'last_accessed': None,
                        'access_count': 0
                    }
                }
                
                # Prepare for ChromaDB
                if self.ipc_collection:
                    documents.append(description)
                    ids.append(doc_id)
                    metadatas.append({
                        'source': 'Indian Penal Code',
                        'section': section,
                        'offense': offense,
                        'punishment': punishment,
                        'type': 'ipc_section'
                    })
            except Exception as e:
                logger.warning(f"Error processing IPC section, skipping row: {e}")
        
        # Add to ChromaDB in batches
        if self.ipc_collection and documents and self.embedding_function:
            try:
                # Clear existing documents
                try:
                    self.ipc_collection.delete(where={'type': 'ipc_section'})
                except Exception as del_e:
                    logger.warning(f"Error clearing existing IPC sections: {del_e}")
                
                # Log unique vs total count for debugging
                logger.info(f"Preparing to add {len(documents)} IPC sections to ChromaDB (unique IDs: {len(set(ids))})")
                
                # Check for duplicate IDs
                id_counts = {}
                for doc_id in ids:
                    id_counts[doc_id] = id_counts.get(doc_id, 0) + 1
                
                duplicates = [doc_id for doc_id, count in id_counts.items() if count > 1]
                if duplicates:
                    logger.warning(f"Found {len(duplicates)} duplicate document IDs in IPC data: {duplicates[:5]}" + ("..." if len(duplicates) > 5 else ""))
                
                # Add in batches of 100
                batch_size = 100
                total_added = 0
                
                for i in range(0, len(documents), batch_size):
                    try:
                        batch_end = min(i + batch_size, len(documents))
                        batch_docs = documents[i:batch_end]
                        batch_ids = ids[i:batch_end]
                        batch_meta = metadatas[i:batch_end]
                        
                        # Double-check this batch for duplicates
                        batch_set = set()
                        unique_batch_docs = []
                        unique_batch_ids = []
                        unique_batch_meta = []
                        
                        for j, doc_id in enumerate(batch_ids):
                            if doc_id not in batch_set:
                                batch_set.add(doc_id)
                                unique_batch_docs.append(batch_docs[j])
                                unique_batch_ids.append(batch_ids[j])
                                unique_batch_meta.append(batch_meta[j])
                        
                        if len(unique_batch_ids) < len(batch_ids):
                            logger.warning(f"Removed {len(batch_ids) - len(unique_batch_ids)} duplicate IDs from batch {i//batch_size + 1}")
                        
                        # Only add if we have documents
                        if unique_batch_docs:
                            self.ipc_collection.add(
                                documents=unique_batch_docs,
                                ids=unique_batch_ids,
                                metadatas=unique_batch_meta
                            )
                            total_added += len(unique_batch_docs)
                    except Exception as batch_e:
                        logger.error(f"Error adding batch {i//batch_size + 1} to IPC collection: {batch_e}")
                
                logger.info(f"Successfully added {total_added} IPC sections to ChromaDB")
            except Exception as e:
                logger.error(f"Error adding IPC sections to ChromaDB: {e}")
    
    def _process_additional_laws(self, df: pd.DataFrame) -> None:
        """Process the additional laws CSV file."""
        documents = []
        ids = []
        metadatas = []
        
        # Track seen document IDs to prevent duplicates
        seen_ids = set()
        
        for _, row in df.iterrows():
            try:
                chapter = str(row['instruction'])
                section = str(row['input'])
                content = str(row['output'])
                
                # Skip rows with empty content
                if not content.strip():
                    continue
                
                # Clean up section identifier for the doc_id
                section_id = section.replace(' ', '_').replace('.', '_').replace('/', '_')
                
                # Create a unique ID that doesn't conflict with IPC sections
                if section.startswith('IPC') or section.startswith('ipc'):
                    # For IPC sections in the additional laws, use a different prefix
                    doc_id = f"additional_law_{section_id}"
                else:
                    doc_id = f"law_{section_id}"
                
                # Ensure ID is truly unique by adding a suffix if needed
                original_doc_id = doc_id
                counter = 1
                while doc_id in seen_ids:
                    doc_id = f"{original_doc_id}_{counter}"
                    counter += 1
                
                # Add to seen IDs
                seen_ids.add(doc_id)
                
                # Store in memory
                self.documents[doc_id] = {
                    'content': content,
                    'metadata': {
                        'source': 'Additional Laws',
                        'chapter': chapter,
                        'section': section,
                        'type': 'additional_law',
                        'last_accessed': None,
                        'access_count': 0
                    }
                }
                
                # Prepare for ChromaDB
                if self.additional_laws_collection:
                    documents.append(content)
                    ids.append(doc_id)
                    metadatas.append({
                        'source': 'Additional Laws',
                        'chapter': chapter,
                        'section': section,
                        'type': 'additional_law'
                    })
            except Exception as e:
                logger.warning(f"Error processing additional law, skipping row: {e}")
        
        # Add to ChromaDB in batches
        if self.additional_laws_collection and documents and self.embedding_function:
            try:
                # Clear existing documents
                try:
                    self.additional_laws_collection.delete(where={'type': 'additional_law'})
                except Exception as del_e:
                    logger.warning(f"Error clearing existing additional laws: {del_e}")
                
                # Log unique vs total count for debugging
                logger.info(f"Preparing to add {len(documents)} additional laws to ChromaDB (unique IDs: {len(set(ids))})")
                
                # Check for duplicate IDs
                id_counts = {}
                for doc_id in ids:
                    id_counts[doc_id] = id_counts.get(doc_id, 0) + 1
                
                duplicates = [doc_id for doc_id, count in id_counts.items() if count > 1]
                if duplicates:
                    logger.warning(f"Found {len(duplicates)} duplicate document IDs in additional laws data: {duplicates[:5]}" + ("..." if len(duplicates) > 5 else ""))
                
                # Add in batches of 100
                batch_size = 100
                total_added = 0
                
                for i in range(0, len(documents), batch_size):
                    try:
                        batch_end = min(i + batch_size, len(documents))
                        batch_docs = documents[i:batch_end]
                        batch_ids = ids[i:batch_end]
                        batch_meta = metadatas[i:batch_end]
                        
                        # Double-check this batch for duplicates
                        batch_set = set()
                        unique_batch_docs = []
                        unique_batch_ids = []
                        unique_batch_meta = []
                        
                        for j, doc_id in enumerate(batch_ids):
                            if doc_id not in batch_set:
                                batch_set.add(doc_id)
                                unique_batch_docs.append(batch_docs[j])
                                unique_batch_ids.append(batch_ids[j])
                                unique_batch_meta.append(batch_meta[j])
                        
                        if len(unique_batch_ids) < len(batch_ids):
                            logger.warning(f"Removed {len(batch_ids) - len(unique_batch_ids)} duplicate IDs from batch {i//batch_size + 1}")
                        
                        # Only add if we have documents
                        if unique_batch_docs:
                            self.additional_laws_collection.add(
                                documents=unique_batch_docs,
                                ids=unique_batch_ids,
                                metadatas=unique_batch_meta
                            )
                            total_added += len(unique_batch_docs)
                    except Exception as batch_e:
                        logger.error(f"Error adding batch {i//batch_size + 1} to additional laws collection: {batch_e}")
                
                logger.info(f"Successfully added {total_added} additional laws to ChromaDB")
            except Exception as e:
                logger.error(f"Error adding additional laws to ChromaDB: {e}")
    
    def _cleanup_search_cache(self) -> None:
        """Clean up old search cache entries."""
        current_time = datetime.now()
        expired_keys = []
        
        # Identify expired cache entries (older than 1 hour)
        for key, (_, timestamp) in self.search_cache.items():
            if (current_time - timestamp).total_seconds() > 3600:  # 1 hour
                expired_keys.append(key)
        
        # Remove expired entries
        for key in expired_keys:
            del self.search_cache[key]
        
        # Update last cleanup timestamp
        self.last_cache_cleanup = current_time
        
        logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
    
    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a document by ID.
        
        Args:
            doc_id: Document ID
            
        Returns:
            Document dict if found, None otherwise
        """
        if doc_id in self.documents:
            # Update access metadata for analytics and smart retrieval
            self.documents[doc_id]['metadata']['last_accessed'] = datetime.now()
            self.documents[doc_id]['metadata']['access_count'] = self.documents[doc_id]['metadata'].get('access_count', 0) + 1
            
            return self.documents[doc_id]
        
        return None
    
    def search_documents(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Search documents using keyword-based search.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of matching documents with scores
        """
        # Check cache first
        cache_key = hashlib.md5(f"keyword:{query}:{limit}".encode()).hexdigest()
        if cache_key in self.search_cache:
            cached_results, timestamp = self.search_cache[cache_key]
            if (datetime.now() - timestamp).total_seconds() < 3600:  # 1 hour cache
                return cached_results

        # Periodically clean up cache
        if (datetime.now() - self.last_cache_cleanup).total_seconds() > 3600:  # 1 hour
            self._cleanup_search_cache()
        
        # Initialize results dictionary
        results = {}
        
        # Preprocess query
        query = query.lower()
        
        # Enhanced query expansion with more comprehensive legal synonyms
        expanded_query = query
        legal_synonyms = {
            'murder': ['homicide', 'killing', '302', 'culpable homicide', 'manslaughter'],
            'police': ['police officer', 'law enforcement', 'cop', 'constable', 'officer'],
            'theft': ['stealing', 'larceny', 'robbery', 'burglary', 'theft', 'stolen'],
            'assault': ['attack', 'battery', 'violence', 'hurt', 'injure', 'grievous'],
            'rape': ['sexual assault', 'sexual violence', '376'],
            'rights': ['fundamental rights', 'constitutional rights', 'legal rights', 'human rights'],
            'court': ['tribunal', 'bench', 'judiciary', 'judge', 'magistrate'],
            'punishment': ['penalty', 'sentence', 'fine', 'imprisonment', 'jail', 'incarceration']
        }
        
        # Add synonyms to query
        for term, synonyms in legal_synonyms.items():
            if term in query:
                expanded_terms = ' '.join(synonyms)
                expanded_query = f"{expanded_query} {expanded_terms}"
        
        # Special case for murder of police officer
        if 'murder' in query and any(term in query for term in legal_synonyms['police']):
            expanded_query += " section 302 section 303 murder of police officer law enforcement killing"
        
        # Process special legal references
        # Handle IPC section numbers
        ipc_section_match = re.search(r'\b(?:section|sec|s)\.?\s*(\d+[A-Za-z]*)', query, re.IGNORECASE)
        if ipc_section_match:
            section_num = ipc_section_match.group(1)
            specific_section_matches = []
            
            # Try to find exact section matches
            for doc_id, doc in self.documents.items():
                if doc['metadata']['type'] == 'ipc_section':
                    if section_num.lower() in doc['metadata']['section'].lower():
                        specific_section_matches.append(doc_id)
            
            # If we found exact matches, prioritize them
            if specific_section_matches:
                for doc_id in specific_section_matches:
                    doc = self.documents[doc_id]
                    results[doc_id] = {
                        'doc_id': doc_id,
                        'content': doc['content'],
                        'metadata': doc['metadata'],
                        'score': 0.95  # High score for exact section matches
                    }
        
        # Handle Constitution article numbers
        article_match = re.search(r'\b(?:article|art)\.?\s*(\d+[A-Za-z]*)', query, re.IGNORECASE)
        if article_match:
            article_num = article_match.group(1)
            specific_article_matches = []
            
            # Try to find exact article matches
            for doc_id, doc in self.documents.items():
                if doc['metadata']['type'] == 'constitutional_article':
                    if article_num.lower() in doc['metadata']['article'].lower():
                        specific_article_matches.append(doc_id)
            
            # If we found exact matches, prioritize them
            if specific_article_matches:
                for doc_id in specific_article_matches:
                    doc = self.documents[doc_id]
                    results[doc_id] = {
                        'doc_id': doc_id,
                        'content': doc['content'],
                        'metadata': doc['metadata'],
                        'score': 0.95  # High score for exact article matches
                    }
                    
        # Check for specific crime types
        crime_keywords = {
            "murder": ["302", "homicide", "killing", "death"],
            "police": ["police officer", "law enforcement", "cop", "constable"],
            "assault": ["assault", "attack", "battery", "hurt"],
            "theft": ["theft", "stealing", "robbery", "burglary"],
            "rape": ["rape", "sexual assault", "376"],
            "fraud": ["fraud", "cheating", "deception", "420"],
            "kidnapping": ["kidnapping", "abduction", "363", "364"],
            "defamation": ["defamation", "libel", "slander", "499"]
        }
        
        # Add specific IPC sections for crimes mentioned in query
        for crime, keywords in crime_keywords.items():
            if crime in query or any(keyword in query for keyword in keywords):
                # Special case for murder of police officer
                if crime == "murder" and "police" in query:
                    # Find and prioritize IPC sections 302 and 303
                    for doc_id, doc in self.documents.items():
                        if doc['metadata']['type'] == 'ipc_section':
                            section = doc['metadata']['section'].lower()
                            if '302' in section or '303' in section:
                                # Check if content is relevant to killing police
                                content = doc['content'].lower()
                                if 'police' in content or 'officer' in content or 'public servant' in content:
                                    results[doc_id] = {
                                        'doc_id': doc_id,
                                        'content': doc['content'],
                                        'metadata': doc['metadata'],
                                        'score': 0.98  # Very high score for this specific case
                                    }
        
        # Tokenize query
        query_tokens = re.findall(r'\w+', expanded_query)
        
        # Calculate document frequencies for BM25-like scoring
        doc_count = len(self.documents)
        idf = {}
        for token in set(query_tokens):
            doc_freq = len(self.search_index.get(token, []))
            if doc_freq > 0:
                idf[token] = np.log((doc_count - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
            else:
                idf[token] = 0
        
        # Get matching documents
        doc_matches = defaultdict(int)
        
        # Score exact phrases higher
        exact_phrases = []
        for i in range(2, min(6, len(query_tokens) + 1)):  # Phrases of length 2 to 5
            for j in range(len(query_tokens) - i + 1):
                phrase = ' '.join(query_tokens[j:j+i])
                if len(phrase) > 4:  # Only consider phrases of reasonable length
                    exact_phrases.append(phrase)
        
        # Search for tokens
        for token in query_tokens:
            # Skip very common words and very short tokens
            if len(token) <= 2:
                continue
            
            # Get matching documents for this token
            matching_docs = self.search_index.get(token, [])
            
            # Update match count
            for doc_id in matching_docs:
                doc_matches[doc_id] += 1
        
        # Calculate scores using BM25-like formula
        k1 = 1.5  # Term frequency saturation
        b = 0.75   # Document length normalization
        
        # Precompute document lengths
        doc_lengths = {}
        avg_doc_length = 0
        for doc_id, doc in self.documents.items():
            length = len(re.findall(r'\w+', doc['content']))
            doc_lengths[doc_id] = length
            avg_doc_length += length
        
        if self.documents:
            avg_doc_length /= len(self.documents)
        else:
            avg_doc_length = 1
        
        # Calculate BM25 scores
        for doc_id, match_count in doc_matches.items():
            # Skip if already added from exact match
            if doc_id in results:
                continue
            
            # Get document
            doc = self.documents.get(doc_id)
            if not doc:
                continue
            
            score = 0
            doc_length = doc_lengths.get(doc_id, avg_doc_length)
            
            # Basic BM25 calculation
            for token in set(query_tokens):
                if token in self.search_index and doc_id in self.search_index[token]:
                    # Count token occurrences in document
                    token_freq = doc['content'].lower().count(token)
                    
                    # BM25 term score
                    term_score = (idf.get(token, 0) * token_freq * (k1 + 1)) / \
                                 (token_freq + k1 * (1 - b + b * doc_length / avg_doc_length))
                                
                    score += term_score
            
            # Boost score based on number of matching tokens
            token_coverage = match_count / len(query_tokens)
            score *= (0.5 + 0.5 * token_coverage)
            
            # Check for exact phrases
            doc_content = doc['content'].lower()
            phrase_matches = sum(1 for phrase in exact_phrases if phrase in doc_content)
            if phrase_matches > 0:
                score += phrase_matches * 0.2  # Boost for phrase matches
            
            # Document type boosting
            doc_type = doc['metadata']['type']
            query_lower = query.lower()
            
            # Apply document-type specific boosts based on query
            if doc_type == 'constitutional_article' and any(term in query_lower for term in ['constitution', 'article', 'fundamental', 'right']):
                score *= 1.3
            elif doc_type == 'ipc_section' and any(term in query_lower for term in ['ipc', 'criminal', 'offense', 'crime', 'punishment']):
                score *= 1.3
            
            # Normalize score to 0-1 range (approximately)
            normalized_score = min(0.99, score / (2 * len(set(query_tokens))))
            
            # Add to results
            results[doc_id] = {
                'doc_id': doc_id,
                'content': doc['content'],
                'metadata': doc['metadata'],
                'score': normalized_score
            }
        
        # Convert to list and sort by score
        results_list = list(results.values())
        results_list.sort(key=lambda x: x['score'], reverse=True)
        
        # Apply diversity to ensure we get different types of documents
        diverse_results = []
        included_types = set()
        
        # First include top scoring documents of different types
        for result in results_list:
            doc_type = result['metadata']['type']
            if doc_type not in included_types and len(diverse_results) < limit * 0.6:
                diverse_results.append(result)
                included_types.add(doc_type)
        
        # Then fill remaining slots with top scoring documents
        remaining_slots = limit - len(diverse_results)
        added_docs = set(res['doc_id'] for res in diverse_results)
        
        for result in results_list:
            if result['doc_id'] not in added_docs and len(diverse_results) < limit:
                diverse_results.append(result)
                added_docs.add(result['doc_id'])
        
        # Sort final results by score
        diverse_results.sort(key=lambda x: x['score'], reverse=True)
        
        # Cache results
        self.search_cache[cache_key] = (diverse_results, datetime.now())
        
        return diverse_results[:limit]

    def search_with_chroma(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Perform enhanced vector-based semantic search using ChromaDB for accurate legal document retrieval.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of matching documents with scores
        """
        # Check cache first
        cache_key = hashlib.md5(f"vector:{query}:{limit}".encode()).hexdigest()
        if cache_key in self.search_cache:
            cached_results, timestamp = self.search_cache[cache_key]
            if (datetime.now() - timestamp).total_seconds() < 3600:  # 1 hour cache
                return cached_results
        
        results = []
        
        # Check if ChromaDB is available
        if not self.chroma_client:
            logger.warning("ChromaDB not available, vector search cannot be performed")
            return []
        
        try:
            # Pre-process query for better vector search
            processed_query = query
            query_lower = query.lower()
            
            # Enhanced query processing for legal domain
            # Extract specific legal references for better matching
            section_match = re.search(r'\b(?:section|sec)\s*(\d+[A-Za-z]*)\b', query_lower)
            article_match = re.search(r'\b(?:article|art)\s*(\d+[A-Za-z]*)\b', query_lower)
            
            # Determine search strategy based on query content
            search_strategy = "general"
            collection_boost = {}
            
            # Identify query type and relevant collections
            if section_match or any(term in query_lower for term in ['ipc', 'penal code', 'criminal', 'offense', 'crime', 'punishment']):
                search_strategy = "ipc_focused"
                collection_boost = {"ipc": 1.3, "constitution": 0.8, "additional": 0.7}
            elif article_match or any(term in query_lower for term in ['constitution', 'article', 'fundamental right', 'directive principle']):
                search_strategy = "constitution_focused"
                collection_boost = {"constitution": 1.3, "ipc": 0.8, "additional": 0.7}
            else:
                # General search across all collections
                collection_boost = {"ipc": 1.0, "constitution": 1.0, "additional": 1.0}
            
            # Collect results from all relevant collections
            all_results = []
            
            # Search constitution collection
            if self.constitution_collection:
                try:
                    # Adjust search parameters based on strategy
                    n_results = limit
                    if search_strategy == "constitution_focused":
                        n_results = limit * 2  # Get more results from the focused collection
                    
                    constitution_results = self.constitution_collection.query(
                        query_texts=[processed_query],
                        n_results=n_results
                    )
                    
                    if constitution_results['ids'][0]:
                        for i, doc_id in enumerate(constitution_results['ids'][0]):
                            # Extract distance and convert to similarity score (1 - distance)
                            if 'distances' in constitution_results and constitution_results['distances'][0]:
                                distance = constitution_results['distances'][0][i]
                                score = 1.0 - min(1.0, distance)  # Convert distance to similarity
                                
                                # Apply collection-specific boost
                                score *= collection_boost["constitution"]
                                
                                # Apply specific article boost if mentioned in query
                                if article_match and doc_id in self.documents:
                                    doc = self.documents[doc_id]
                                    if 'article' in doc['metadata'] and article_match.group(1) in doc['metadata']['article']:
                                        score *= 1.5  # Significant boost for exact article match
                            else:
                                score = 0.7 * collection_boost["constitution"]  # Default score if distances not available
                                
                            # Get document from memory
                            if doc_id in self.documents:
                                doc = self.documents[doc_id]
                                
                                # Update access metadata for analytics
                                doc['metadata']['last_accessed'] = datetime.now()
                                doc['metadata']['access_count'] = doc['metadata'].get('access_count', 0) + 1
                                
                                all_results.append({
                                    'doc_id': doc_id,
                                    'content': doc['content'],
                                    'metadata': doc['metadata'],
                                    'score': score
                                })
                except Exception as e:
                    logger.error(f"Error searching constitution collection: {e}")
            
            # Search IPC collection
            if self.ipc_collection:
                try:
                    # Adjust search parameters based on strategy
                    n_results = limit
                    if search_strategy == "ipc_focused":
                        n_results = limit * 2  # Get more results from the focused collection
                    
                    ipc_results = self.ipc_collection.query(
                        query_texts=[processed_query],
                        n_results=n_results
                    )
                    
                    if ipc_results['ids'][0]:
                        for i, doc_id in enumerate(ipc_results['ids'][0]):
                            # Extract distance and convert to similarity score
                            if 'distances' in ipc_results and ipc_results['distances'][0]:
                                distance = ipc_results['distances'][0][i]
                                score = 1.0 - min(1.0, distance)
                                
                                # Apply collection-specific boost
                                score *= collection_boost["ipc"]
                                
                                # Apply specific section boost if mentioned in query
                                if section_match and doc_id in self.documents:
                                    doc = self.documents[doc_id]
                                    if 'section' in doc['metadata'] and section_match.group(1) in doc['metadata']['section']:
                                        score *= 1.5  # Significant boost for exact section match
                            else:
                                score = 0.7 * collection_boost["ipc"]
                                
                            # Get document from memory
                            if doc_id in self.documents:
                                doc = self.documents[doc_id]
                                
                                # Update access metadata for analytics
                                doc['metadata']['last_accessed'] = datetime.now()
                                doc['metadata']['access_count'] = doc['metadata'].get('access_count', 0) + 1
                                
                                all_results.append({
                                    'doc_id': doc_id,
                                    'content': doc['content'],
                                    'metadata': doc['metadata'],
                                    'score': score
                                })
                except Exception as e:
                    logger.error(f"Error searching IPC collection: {e}")
            
            # Search additional laws collection
            if self.additional_laws_collection:
                try:
                    additional_results = self.additional_laws_collection.query(
                        query_texts=[processed_query],
                        n_results=limit
                    )
                    
                    if additional_results['ids'][0]:
                        for i, doc_id in enumerate(additional_results['ids'][0]):
                            # Extract distance and convert to similarity score
                            if 'distances' in additional_results and additional_results['distances'][0]:
                                distance = additional_results['distances'][0][i]
                                score = 1.0 - min(1.0, distance)
                                
                                # Apply collection-specific boost
                                score *= collection_boost["additional"]
                            else:
                                score = 0.7 * collection_boost["additional"]
                                
                            # Get document from memory
                            if doc_id in self.documents:
                                doc = self.documents[doc_id]
                                
                                # Update access metadata for analytics
                                doc['metadata']['last_accessed'] = datetime.now()
                                doc['metadata']['access_count'] = doc['metadata'].get('access_count', 0) + 1
                                
                                all_results.append({
                                    'doc_id': doc_id,
                                    'content': doc['content'],
                                    'metadata': doc['metadata'],
                                    'score': score
                                })
                except Exception as e:
                    logger.error(f"Error searching additional laws collection: {e}")
            
            # Apply content relevance boosting
            for result in all_results:
                doc_content = result['content'].lower()
                doc_type = result['metadata']['type']
                
                # Check for content relevance to specific crimes
                crime_keywords = {
                    "murder": ["302", "homicide", "killing"],
                    "police": ["police officer", "law enforcement", "cop"],
                    "assault": ["assault", "attack", "battery"],
                    "theft": ["theft", "stealing", "robbery"],
                    "rape": ["rape", "sexual assault"],
                    "fraud": ["fraud", "cheating", "deception"],
                    "kidnapping": ["kidnapping", "abduction"],
                    "defamation": ["defamation", "libel", "slander"]
                }
                
                for crime, keywords in crime_keywords.items():
                    if crime in query_lower or any(keyword in query_lower for keyword in keywords):
                        # Check if document content is relevant to this crime
                        if crime in doc_content or any(keyword in doc_content for keyword in keywords):
                            result['score'] *= 1.3  # Boost for content relevance
                            
                            # Special case for murder of police officer
                            if crime == "murder" and "police" in query_lower and "police" in doc_content:
                                result['score'] *= 1.2  # Additional boost for this specific case
                
                # Apply recency and popularity boosts
                access_count = result['metadata'].get('access_count', 0)
                popularity_boost = min(1.15, 1.0 + (access_count / 100))  # Cap at 15% boost
                
                if result['metadata'].get('last_accessed'):
                    # Boost recently accessed documents
                    time_since_access = (datetime.now() - result['metadata']['last_accessed']).total_seconds()
                    recency_boost = 1.0 + min(0.1, (1 / (1 + time_since_access / 86400)))  # Small decay over days
                    result['score'] *= recency_boost
                
                result['score'] *= popularity_boost
            
            # Sort by score and return top results
            all_results.sort(key=lambda x: x['score'], reverse=True)
            
            # Apply diversity to ensure we get different types of documents
            diverse_results = []
            included_types = set()
            
            # First include top scoring documents of different types
            for result in all_results:
                doc_type = result['metadata']['type']
                if doc_type not in included_types and len(diverse_results) < limit * 0.5:
                    diverse_results.append(result)
                    included_types.add(doc_type)
            
            # Then fill remaining slots with top scoring documents
            remaining_slots = limit - len(diverse_results)
            added_docs = set(res['doc_id'] for res in diverse_results)
            
            for result in all_results:
                if result['doc_id'] not in added_docs and len(diverse_results) < limit:
                    diverse_results.append(result)
                    added_docs.add(result['doc_id'])
            
            # Sort final results by score
            diverse_results.sort(key=lambda x: x['score'], reverse=True)
            
            # Cache the results
            self.search_cache[cache_key] = (diverse_results[:limit], datetime.now())
            
            return diverse_results[:limit]
            
        except Exception as e:
            logger.error(f"Error in vector search: {e}")
            return []
    
    def hybrid_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Perform vector-based search for legal document retrieval.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of matching documents with scores
        """
        # This method now exclusively uses vector search as requested
        # No hybrid approach combining keyword and vector search
        
        # Periodically clean up cache
        if (datetime.now() - self.last_cache_cleanup).total_seconds() > 3600:  # 1 hour
            self._cleanup_search_cache()
        
        # Use enhanced vector search for best accuracy
        results = self.search_with_chroma(query, limit)
        
        # If vector search returned no results (e.g., ChromaDB not available)
        if not results:
            logger.warning(f"Vector search returned no results for query: {query}")
        
        return results
    
    def hybrid_search_with_boost(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Perform hybrid search with additional boosting factors.
        This is an alternative implementation that can be enabled if needed.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of matching documents with scores
        """
        # Check cache first
        cache_key = hashlib.md5(f"hybrid:{query}:{limit}".encode()).hexdigest()
        if cache_key in self.search_cache:
            cached_results, timestamp = self.search_cache[cache_key]
            if (datetime.now() - timestamp).total_seconds() < 3600:  # 1 hour cache
                return cached_results
        
        # Periodically clean up cache
        if (datetime.now() - self.last_cache_cleanup).total_seconds() > 3600:  # 1 hour
            self._cleanup_search_cache()
            
        query_lower = query.lower()
        doc_content = ""
        doc_type = ""
        doc = {}
        access_count = 0
        recency_boost = 1.0
        doc_type_boost = 1.0
        norm_semantic_score = 0
        norm_keyword_score = 0
        combined_scores = {}
        semantic_results = []
        keyword_results = []
        
        # Check for specific crime types in query
        crime_keywords = {
            "murder": ["302", "homicide", "killing"],
            "police": ["police officer", "law enforcement", "cop"],
            "assault": ["assault", "attack", "battery"],
            "theft": ["theft", "stealing", "robbery"],
            "rape": ["rape", "sexual assault"],
            "fraud": ["fraud", "cheating", "deception"],
            "kidnapping": ["kidnapping", "abduction"],
            "defamation": ["defamation", "libel", "slander"]
        }
        
        # Check for content relevance to specific crimes
        for crime, keywords in crime_keywords.items():
            if crime in query_lower or any(keyword in query_lower for keyword in keywords):
                # Check if document content is relevant to this crime
                if crime in doc_content or any(keyword in doc_content for keyword in keywords):
                    content_relevance_boost = 1.5  # Significant boost for content relevance
                    
                    # Special case for murder of police officer
                    if crime == "murder" and "police" in query_lower and "police" in doc_content:
                        content_relevance_boost = 2.0  # Even higher boost for this specific case

                        # Document type specific boosts
                        if doc_type == 'constitutional_article' and any(term in query_lower for term in ['constitution', 'article', 'fundamental', 'right']):
                            doc_type_boost = 1.3
                        elif doc_type == 'ipc_section' and any(term in query_lower for term in ['ipc', 'criminal', 'offense', 'crime', 'punishment']):
                            doc_type_boost = 1.3
                            
                            # Check for specific IPC sections mentioned in query
                            section_match = re.search(r'\b(?:section|sec)\s*(\d+[A-Za-z]*)', query_lower)
                            if section_match and section_match.group(1) in doc['metadata']['section'].lower():
                                doc_type_boost = 2.0  # Higher boost for exact section match
                            
                        # Apply access count boost (popular documents get a boost)
                        popularity_boost = min(1.2, 1.0 + (access_count / 50))  # Cap at 20% boost
                        doc_type_boost *= popularity_boost * recency_boost * content_relevance_boost
                    
                    # Weighted combination with adjusted weights
                    # For legal queries, hybrid search often works better with more weight on keyword search
                    semantic_weight = 0.5
                    keyword_weight = 0.5
                    
                    # Check if query contains specific legal terms that benefit from higher keyword weighting
                    if any(term in query.lower() for term in ['section', 'article', 'ipc', '302', 'constitution']):
                        semantic_weight = 0.3
                        keyword_weight = 0.7
                    
                    combined_scores[doc_id] = (semantic_weight * norm_semantic_score + 
                                              keyword_weight * norm_keyword_score) * doc_type_boost
        
        # Create final result list
        results = []
        for doc_id, score in sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)[:limit]:
            # Get document details from semantic or keyword results, or from memory
            doc_info = next((r for r in semantic_results if r['doc_id'] == doc_id), None)
            if not doc_info:
                doc_info = next((r for r in keyword_results if r['doc_id'] == doc_id), None)
            
            if doc_info:
                doc_info['score'] = score  # Update with combined score
                results.append(doc_info)
            elif doc_id in self.documents:
                # Get from memory
                doc = self.documents[doc_id]
                
                # Update access metadata
                doc['metadata']['last_accessed'] = datetime.now()
                doc['metadata']['access_count'] = doc['metadata'].get('access_count', 0) + 1
                
                results.append({
                    'doc_id': doc_id,
                    'content': doc['content'],
                    'metadata': doc['metadata'],
                    'score': score
                })
        
        # Cache the results
        self.search_cache[cache_key] = (results, datetime.now())
        
        return results
    
    def get_relevant_context(self, query: str, limit: int = 3) -> str:
        """
        Get relevant context from documents for a query using vector search only.
        
        Args:
            query: The user's query
            limit: Maximum number of documents to include
            
        Returns:
            Formatted context string with confidence scores
        """
        # Pre-process query to identify specific legal concepts
        query_lower = query.lower()
        
        # Check for specific legal topics to improve retrieval
        legal_keywords = {
            # Criminal law keywords
            "murder": ["302", "homicide", "killing"],
            "police": ["police officer", "law enforcement", "cop"],
            "assault": ["assault", "attack", "battery"],
            "theft": ["theft", "stealing", "robbery"],
            "rape": ["rape", "sexual assault"],
            "fraud": ["fraud", "cheating", "deception"],
            "kidnapping": ["kidnapping", "abduction"],
            "defamation": ["defamation", "libel", "slander"],
            
            # Civil law keywords
            "tenant": ["rent", "rental", "lease", "landlord", "property", "eviction", "housing"],
            "property": ["ownership", "title", "deed", "real estate", "land", "building"],
            "family": ["divorce", "marriage", "custody", "maintenance", "alimony"],
            "contract": ["agreement", "breach", "terms", "clause", "party"],
            "consumer": ["product", "service", "complaint", "refund", "warranty"],
            "employment": ["worker", "salary", "wage", "termination", "workplace"]
        }
        
        # Expand query with relevant legal terms
        expanded_query = query
        
        # Handle criminal law topics
        for topic, keywords in legal_keywords.items():
            if topic in query_lower or any(keyword in query_lower for keyword in keywords):
                # Add relevant IPC sections for specific crimes
                if topic == "murder" and "police" in query_lower:
                    expanded_query += " IPC Section 302 IPC Section 303 murder of police officer"
                elif topic == "murder":
                    expanded_query += " IPC Section 302 murder homicide"
                elif topic == "assault" and "police" in query_lower:
                    expanded_query += " IPC Section 332 IPC Section 353 assault on public servant"
                # Handle civil law topics
                elif topic == "tenant":
                    expanded_query += " tenant rights rental agreement lease landlord property Maharashtra Rent Control Act housing law"
                elif topic == "property":
                    expanded_query += " property rights ownership Transfer of Property Act real estate"
                elif topic == "family":
                    expanded_query += " family law marriage divorce custody maintenance Hindu Marriage Act"
                elif topic == "contract":
                    expanded_query += " contract law agreement Indian Contract Act breach remedy"
                elif topic == "consumer":
                    expanded_query += " consumer protection Consumer Protection Act rights complaint redressal"
                elif topic == "employment":
                    expanded_query += " employment law worker rights Industrial Disputes Act labor law"
        
        # Adjust limit based on query complexity
        adjusted_limit = limit
        if any(topic in query_lower for topic in legal_keywords):
            adjusted_limit = max(limit, 4)  # Get more results for specific legal topics
        
        # Use vector search with expanded query for better semantic understanding
        results = self.search_with_chroma(expanded_query, adjusted_limit * 2)  # Get more results to filter
        
        if not results:
            # Fallback to original query if expanded query returns no results
            results = self.search_with_chroma(query, adjusted_limit * 2)
            
        if not results:
            # Provide fallback context for common legal topics when no results are found
            if "tenant" in query_lower or "rent" in query_lower or "lease" in query_lower or "landlord" in query_lower:
                return "Relevant Legal Context:\n\n[Low Confidence] Tenant Rights in India:\nIn India, tenancy is primarily governed by state-specific rent control acts. For Mumbai, the Maharashtra Rent Control Act, 1999 applies, which covers aspects like fair rent, eviction procedures, and tenant protections. Tenants generally have rights regarding proper notice periods, essential repairs and maintenance, security deposit limits, and protection against arbitrary eviction. For specific provisions, please refer to the Maharashtra Rent Control Act, 1999 and local municipal regulations.\n\n"
            
            # Add other fallbacks for common topics as needed
            return ""
        
        context = "Relevant Legal Context:\n\n"
        
        # Filter out irrelevant results
        filtered_results = []
        for result in results:
            # Check if the result is relevant to the query
            content_lower = result['content'].lower()
            metadata = result['metadata']
            
            # Calculate relevance score based on keyword matching
            relevance = 0
            
            # Check for topic-specific relevance
            for topic, keywords in legal_keywords.items():
                if topic in query_lower or any(keyword in query_lower for keyword in keywords):
                    if topic in content_lower or any(keyword in content_lower for keyword in keywords):
                        relevance += 2
                        
            # Special handling for location-specific queries (like Mumbai)
            locations = ["mumbai", "delhi", "bangalore", "kolkata", "chennai", "hyderabad", "pune", "ahmedabad"]
            for location in locations:
                if location in query_lower and location in content_lower:
                    relevance += 3  # Higher boost for location matches
            
            # Check for specific legal terms in both query and content
            legal_terms = ["section", "ipc", "article", "constitution", "law", "punishment", "offense"]
            for term in legal_terms:
                if term in query_lower and term in content_lower:
                    relevance += 1
            
            # Only include results with minimum relevance or high confidence score
            if relevance > 0 or result['score'] > 0.75:
                filtered_results.append((result, relevance))
        
        # Sort by combined score (original score + relevance)
        filtered_results.sort(key=lambda x: (x[0]['score'] + 0.1 * x[1]), reverse=True)
        
        # Use top results up to limit
        used_results = [r[0] for r in filtered_results[:adjusted_limit]]
        
        for result in used_results:
            metadata = result['metadata']
            content = result['content']
            score = result['score']
            
            # More granular confidence levels with higher thresholds
            if score > 0.80:
                confidence = "High"
            elif score > 0.60:
                confidence = "Medium"
            else:
                confidence = "Low"
            
            # Format document content with clearer structure
            if metadata['type'] == 'constitutional_article':
                context += f"[{confidence} Confidence] Constitution Article {metadata['article']} ({metadata['heading']}):\n{content}\n\n"
            elif metadata['type'] == 'ipc_section':
                context += f"[{confidence} Confidence] IPC Section {metadata['section']}:\n{content}\n\n"
                if 'offense' in metadata and metadata['offense']:
                    context += f"Offense: {metadata['offense']}\n"
                if 'punishment' in metadata and metadata['punishment']:
                    context += f"Punishment: {metadata['punishment']}\n\n"
            elif metadata['type'] == 'additional_law':
                context += f"[{confidence} Confidence] {metadata['chapter']} - {metadata['section']}:\n{content}\n\n"
        
        return context.strip()

# Create a singleton instance
document_service = DocumentService()