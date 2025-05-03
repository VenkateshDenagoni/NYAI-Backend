import re
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import numpy as np
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
import uuid
import logging

from src.utils.logger import logger

# Initialize logger
logger = logging.getLogger("nyai.rag_utils")

# Try to import NLTK components with fallbacks
try:
    import nltk
    from nltk.tokenize import word_tokenize
    from nltk.corpus import stopwords
    
    NLTK_AVAILABLE = True
    
    # Try to get stopwords - if they're not downloaded, use an empty set
    try:
        STOPWORDS = set(stopwords.words('english'))
    except LookupError:
        logger.warning("NLTK stopwords not found, using empty stopwords set")
        STOPWORDS = set()
        
except ImportError:
    # NLTK not available, create fallback functions
    NLTK_AVAILABLE = False
    STOPWORDS = set()
    
    def word_tokenize(text: str) -> List[str]:
        """Simple fallback for NLTK word_tokenize."""
        # Basic whitespace and punctuation splitting
        text = re.sub(r'[^\w\s]', ' ', text)
        return [word for word in text.split() if word]
    
    logger.warning("NLTK import failed, using fallback tokenization functions")

def clean_text(text: str) -> str:
    """Clean and normalize text for better embedding quality."""
    if not text or not isinstance(text, str):
        return ""
        
    # Replace multiple whitespace with single space
    text = re.sub(r'\s+', ' ', text)
    # Remove special characters but keep punctuation
    text = re.sub(r'[^\w\s.,;:?!()"\-]', '', text)
    # Normalize whitespace around punctuation
    text = re.sub(r'\s*([.,;:?!()"\-])\s*', r'\1 ', text)
    # Remove extra spaces
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
    """Split text into overlapping chunks for better retrieval.
    
    Args:
        text: The text to chunk
        chunk_size: Target size of each chunk in characters
        overlap: Number of characters to overlap between chunks
        
    Returns:
        List of text chunks
    """
    if not text or not isinstance(text, str):
        return []
        
    # Clean the text first
    text = clean_text(text)
    
    # If text is smaller than chunk size, return as is
    if len(text) <= chunk_size:
        return [text]
    
    # Split text into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        # If adding this sentence would exceed chunk size
        if len(current_chunk) + len(sentence) > chunk_size and current_chunk:
            # Add current chunk to results
            chunks.append(current_chunk.strip())
            # Start new chunk with overlap
            words = current_chunk.split()
            # Calculate how many words to keep for overlap
            overlap_word_count = min(len(words), int(overlap / 5))  # Approximate words in overlap
            current_chunk = " ".join(words[-overlap_word_count:]) + " "
        
        # Add sentence to current chunk
        current_chunk += sentence + " "
    
    # Add the last chunk if not empty
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    # Ensure we have at least one chunk
    if not chunks and text.strip():
        # If we couldn't split by sentences, just split by characters with overlap
        i = 0
        while i < len(text):
            end = min(i + chunk_size, len(text))
            chunks.append(text[i:end])
            i += chunk_size - overlap
    
    return chunks

def preprocess_csv_for_rag(file_path: Path, text_columns: List[str] = None, 
                          chunk_size: int = 500, overlap: int = 100) -> List[Dict[str, Any]]:
    """Preprocess a CSV file for RAG by chunking text columns.
    
    Args:
        file_path: Path to the CSV file
        text_columns: List of column names containing text to chunk
                     If None, will try to detect text columns
        chunk_size: Target size of each chunk in characters
        overlap: Number of characters to overlap between chunks
        
    Returns:
        List of dictionaries with chunked text and metadata
    """
    try:
        # Load CSV file
        df = pd.read_csv(file_path)
        
        # If no text columns specified, try to detect them
        if not text_columns:
            # Columns likely to contain text content
            potential_text_cols = ['content', 'text', 'description', 'body']
            text_columns = [col for col in df.columns if col.lower() in potential_text_cols]
            
            # If still no text columns found, use columns with string values and longer content
            if not text_columns:
                for col in df.columns:
                    if df[col].dtype == 'object':
                        # Check if column has string values with substantial content
                        sample = df[col].dropna().astype(str).iloc[0] if not df[col].empty else ""
                        if len(sample) > 100:  # Assume columns with longer text are content
                            text_columns.append(col)
        
        # If still no text columns, use all string columns
        if not text_columns:
            text_columns = [col for col in df.columns if df[col].dtype == 'object']
        
        # Prepare results
        results = []
        
        # Process each row
        for _, row in df.iterrows():
            # Extract metadata (non-text columns)
            metadata = {col: row[col] for col in df.columns if col not in text_columns}
            
            # Combine text from all text columns
            combined_text = " ".join([str(row[col]) for col in text_columns if pd.notna(row[col])])
            
            # Chunk the combined text
            chunks = chunk_text(combined_text, chunk_size, overlap)
            
            # Create a document for each chunk with metadata
            for i, chunk in enumerate(chunks):
                results.append({
                    "content": chunk,
                    "metadata": {
                        **metadata,
                        "source": file_path.stem,
                        "chunk_index": i,
                        "total_chunks": len(chunks)
                    }
                })
        
        logger.info(f"Preprocessed {file_path.name} into {len(results)} chunks")
        return results
    except Exception as e:
        logger.error(f"Error preprocessing {file_path}: {e}")
        return []

def expand_query(query: str) -> str:
    """Expand a query with synonyms and related terms for better retrieval.
    
    Args:
        query: The original query
        
    Returns:
        Expanded query
    """
    # Clean and tokenize the query
    clean_query = clean_text(query.lower())
    
    try:
        # Tokenize and remove stopwords
        tokens = word_tokenize(clean_query)
        stop_words = set(stopwords.words('english'))
        tokens = [token for token in tokens if token.isalnum() and token not in stop_words]
    except Exception as e:
        logger.warning(f"Error in NLTK processing: {e}. Using simple tokenization.")
        tokens = [token for token in re.findall(r'\w+', clean_query) 
                 if len(token) > 2]  # Simple fallback tokenization
    
    # Legal term mappings with expanded synonyms
    legal_synonyms = {
        "murder": ["homicide", "killing", "manslaughter", "assassination", "slaying"],
        "theft": ["stealing", "larceny", "robbery", "burglary", "shoplifting", "misappropriation"],
        "assault": ["attack", "battery", "violence", "striking", "physical harm"],
        "fraud": ["deception", "misrepresentation", "cheating", "scam", "swindle", "forgery"],
        "divorce": ["marital dissolution", "separation", "annulment", "marital breakdown"],
        "contract": ["agreement", "covenant", "obligation", "pact", "legal document"],
        "evidence": ["proof", "testimony", "exhibit", "documentation", "substantiation"],
        "lawsuit": ["litigation", "legal action", "case", "suit", "legal proceeding"],
        "property": ["real estate", "assets", "possessions", "holdings", "land"],
        "rights": ["entitlements", "privileges", "freedoms", "legal claims"],
        "constitution": ["fundamental law", "basic law", "charter", "constitutional law"],
        "section": ["provision", "clause", "article", "paragraph"],
        "ipc": ["indian penal code", "penal code", "criminal code"],
        "bail": ["surety", "bond", "release", "security"],
        "punishment": ["penalty", "sentence", "sanctions", "fine", "imprisonment"],
        "arrest": ["apprehension", "detention", "custody", "capture"],
        "appeal": ["petition", "judicial review", "challenge", "legal recourse"],
        "damages": ["compensation", "reparation", "restitution", "redress"],
        "fundamental rights": ["basic rights", "constitutional rights", "human rights", "civil liberties"],
        "court": ["tribunal", "judiciary", "bench", "legal forum"],
        "document": ["legal paper", "instrument", "filing", "deed"],
        "lawyer": ["advocate", "attorney", "counsel", "legal representative"],
        "law": ["statute", "legislation", "regulation", "legal code", "act"],
        "criminal": ["offender", "accused", "defendant", "convict"],
        "crpc": ["criminal procedure code", "code of criminal procedure"]
    }
    
    # Extract section/article numbers
    legal_references = re.findall(r'section\s+(\d+[A-Z]?)|\bart(?:icle)?\s+(\d+[A-Z]?)', clean_query, re.IGNORECASE)
    reference_expansions = []
    
    # Flatten the tuples from re.findall
    for ref_tuple in legal_references:
        ref = next((r for r in ref_tuple if r), None)
        if ref:
            # Add variants of section references
            reference_expansions.extend([
                f"section {ref}",
                f"section {ref} of ipc",
                f"section {ref} of the indian penal code",
                f"s. {ref}",
                f"s.{ref}"
            ])
    
    # Expand tokens with synonyms
    expanded_tokens = set(tokens)
    for token in tokens:
        if token in legal_synonyms:
            expanded_tokens.update(legal_synonyms[token])
    
    # Build expanded query - start with original for context preservation
    expanded_query = clean_query
    
    # Add reference expansions if found
    if reference_expansions:
        expanded_query += " " + " ".join(reference_expansions)
    
    # Add expanded tokens that weren't in the original query
    new_tokens = set(expanded_tokens) - set(tokens)
    if new_tokens:
        expanded_query += " " + " ".join(new_tokens)
    
    return expanded_query

def detect_document_type(df: pd.DataFrame) -> str:
    """Detect the type of legal document based on column structure.
    
    Args:
        df: DataFrame containing legal document data
        
    Returns:
        Document type ('constitution', 'ipc', 'laws_qa', or 'unknown')
    """
    # Check column names (case-insensitive)
    columns_lower = [col.lower() if isinstance(col, str) else str(col).lower() for col in df.columns]
    
    # Check for constitution columns
    if 'part' in columns_lower and 'article' in columns_lower:
        return 'constitution'
    
    # Check for IPC section indicators
    if ('section' in ''.join(columns_lower) and 'ipc' in ''.join(columns_lower)) or 'section_number' in columns_lower:
        return 'ipc'
    
    # Alternative detection for IPC - look at first few rows for patterns
    if df.shape[0] > 0:
        # Check first row for IPC indicators
        first_row_str = ' '.join(str(val).lower() for val in df.iloc[0].values if pd.notna(val))
        if 'ipc section' in first_row_str or 'indian penal code' in first_row_str:
            return 'ipc'
        
        # Check section_number column if it exists
        if 'section_number' in df.columns:
            sample_vals = df['section_number'].dropna().astype(str).head(5).tolist()
            if any('ipc' in val.lower() for val in sample_vals):
                return 'ipc'
    
    # Check for Q&A format
    if 'question' in columns_lower and 'answer' in columns_lower:
        return 'laws_qa'
    
    # Default
    return 'unknown'

def get_optimal_chunk_params(document_type: str) -> Tuple[int, int]:
    """Get optimal chunking parameters based on document type.
    
    Args:
        document_type: Type of legal document
        
    Returns:
        Tuple of (chunk_size, overlap)
    """
    # Customize chunking strategy based on document type
    if document_type == 'constitution':
        # Constitution articles - smaller chunks with moderate overlap
        return (400, 100)
    elif document_type == 'ipc':
        # IPC sections - larger chunks to capture full section text
        return (600, 150)
    elif document_type == 'laws_qa':
        # Q&A pairs - smaller chunks to preserve question-answer relationship
        return (350, 75)
    else:
        # Default
        return (500, 100)

def extract_legal_metadata(row: pd.Series, document_type: str) -> Dict[str, Any]:
    """Extract optimized metadata from legal documents.
    
    Args:
        row: Pandas Series representing a row in the dataset
        document_type: Type of legal document
        
    Returns:
        Dictionary of metadata fields
    """
    metadata = {}
    
    # Common metadata
    for col in row.index:
        if pd.notna(row[col]) and col.lower() not in ['content', 'text', 'description']:
            metadata[col] = str(row[col])
    
    # Document-specific metadata enrichment
    if document_type == 'constitution':
        # Extract part and article numbers as separate fields for filtering
        if 'Part' in row and pd.notna(row['Part']):
            metadata['part_number'] = re.sub(r'[^\d]', '', str(row['Part']))
        
        if 'Article' in row and pd.notna(row['Article']):
            metadata['article_number'] = re.sub(r'[^\d]', '', str(row['Article']))
            
        # Add document type for filtering
        metadata['document_type'] = 'constitution'
        metadata['category'] = 'fundamental_law'
            
    elif document_type == 'ipc':
        # Extract section number for filtering
        section_num = None
        
        # Try different ways to extract section number
        if 'Section' in row and pd.notna(row['Section']):
            section_text = str(row['Section'])
            # Check for formats like "IPC_420" or "420"
            match = re.search(r'(?:IPC_)?(\d+[A-Za-z]?)', section_text)
            if match:
                section_num = match.group(1)
            else:
                # Extract numeric part of section
                section_num = re.sub(r'[^\d]', '', section_text)
        
        # Try section_number column
        elif 'section_number' in row and pd.notna(row['section_number']):
            section_text = str(row['section_number'])
            # Extract the numeric part if it's in format "IPC_420"
            match = re.search(r'(?:IPC_)?(\d+[A-Za-z]?)', section_text)
            if match:
                section_num = match.group(1)
            else:
                section_num = re.sub(r'[^\d]', '', section_text)
        
        # Try to extract from other columns or content
        else:
            # Check if there's a column containing section info
            for col, val in row.items():
                if pd.notna(val) and isinstance(val, str):
                    # Look for patterns like "Section 420" or "IPC Section 420"
                    match = re.search(r'(?:IPC)?\s*[Ss]ection\s+(\d+[A-Za-z]?)', val)
                    if match:
                        section_num = match.group(1)
                        break
        
        # Add section number to metadata if found
        if section_num:
            metadata['section_number'] = section_num
            
        # Extract keywords as tags
        if 'Keywords' in row and pd.notna(row['Keywords']):
            keywords = str(row['Keywords']).split(',')
            metadata['keywords'] = [kw.strip().lower() for kw in keywords]
        elif 'keywords' in row and pd.notna(row['keywords']):
            keywords = str(row['keywords']).split(',')
            metadata['keywords'] = [kw.strip().lower() for kw in keywords]
            
        # Add document type for filtering
        metadata['document_type'] = 'ipc'
        metadata['category'] = 'criminal_law'
        
    elif document_type == 'laws_qa':
        # Extract topic information
        if 'Topic' in row and pd.notna(row['Topic']):
            metadata['topic'] = str(row['Topic']).strip().lower()
        elif 'topic' in row and pd.notna(row['topic']):
            metadata['topic'] = str(row['topic']).strip().lower()
            
        # Document type
        metadata['document_type'] = 'qa'
        metadata['category'] = 'legal_qa'
        
    return metadata

def create_cross_references(documents: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Create cross-references between related legal documents.
    
    Args:
        documents: List of document dictionaries
        
    Returns:
        Dictionary of document IDs to document dictionaries with cross-references
    """
    # Check if documents is empty
    if not documents:
        return {}
        
    # Convert to dictionary if it's a list and ensure each document has an ID
    documents_dict = {}
    if isinstance(documents, list):
        for doc in documents:
            if 'id' in doc:
                doc_id = doc['id']
                documents_dict[doc_id] = doc
            else:
                # Generate an ID if none exists
                doc_id = str(uuid.uuid4())
                doc['id'] = doc_id
                documents_dict[doc_id] = doc
    else:
        # If already a dictionary, use as is
        documents_dict = documents
    
    # Create indices for faster lookup
    section_index = {}
    article_index = {}
    topic_index = {}
    
    # First pass - build indices
    for doc_id, doc in documents_dict.items():
        metadata = doc.get('metadata', {})
        
        # Index IPC sections
        if 'section_number' in metadata:
            section_num = metadata['section_number']
            if section_num not in section_index:
                section_index[section_num] = []
            section_index[section_num].append(doc_id)
            
        # Index constitution articles
        if 'article_number' in metadata:
            article_num = metadata['article_number']
            if article_num not in article_index:
                article_index[article_num] = []
            article_index[article_num].append(doc_id)
            
        # Index by topic
        if 'topic' in metadata:
            topic = metadata['topic']
            if topic not in topic_index:
                topic_index[topic] = []
            topic_index[topic].append(doc_id)
    
    # Second pass - add cross-references
    for doc_id, doc in documents_dict.items():
        metadata = doc.get('metadata', {})
        cross_refs = []
        
        # Find related sections/articles in content
        content = doc.get('content', '').lower()
        
        # Look for section references
        section_refs = re.findall(r'section\s+(\d+[A-Z]?)', content, re.IGNORECASE)
        for ref in section_refs:
            ref_num = re.sub(r'[^\d]', '', ref)
            if ref_num in section_index:
                # Add cross-references to other sections
                cross_refs.extend([idx for idx in section_index[ref_num] if idx != doc_id])
        
        # Look for article references
        article_refs = re.findall(r'\barticle\s+(\d+[A-Z]?)', content, re.IGNORECASE)
        for ref in article_refs:
            ref_num = re.sub(r'[^\d]', '', ref)
            if ref_num in article_index:
                # Add cross-references to constitution articles
                cross_refs.extend([idx for idx in article_index[ref_num] if idx != doc_id])
        
        # Add topic-based relationships
        if 'topic' in metadata and metadata['topic'] in topic_index:
            cross_refs.extend([idx for idx in topic_index[metadata['topic']] if idx != doc_id])
        
        # Add cross-references to metadata (limit to top 5 most relevant)
        if cross_refs:
            # Make sure metadata exists
            if 'metadata' not in doc:
                doc['metadata'] = {}
            doc['metadata']['cross_references'] = list(set(cross_refs))[:5]
    
    return documents_dict

def enhanced_chunk_text(text: str, document_type: str = 'unknown') -> List[str]:
    """Enhanced text chunking optimized for legal documents.
    
    Args:
        text: The text to chunk
        document_type: Type of legal document
        
    Returns:
        List of text chunks
    """
    if not text or not isinstance(text, str):
        return []
    
    # Get optimal chunking parameters
    chunk_size, overlap = get_optimal_chunk_params(document_type)
    
    # For IPC sections, try to preserve section boundaries
    if document_type == 'ipc':
        # Check if this is a complete section
        if re.search(r'^Section\s+\d+', text, re.IGNORECASE):
            # For shorter sections, keep them intact
            if len(text) <= chunk_size * 1.2:  # Allow 20% more for complete sections
                return [clean_text(text)]
    
    # For Q&A format, try to keep Q&A pairs together
    if document_type == 'laws_qa':
        if len(text) <= chunk_size * 1.5:  # Allow 50% more for complete Q&A
            return [clean_text(text)]
    
    # For constitution articles, try to keep articles intact
    if document_type == 'constitution':
        if re.search(r'^Article\s+\d+', text, re.IGNORECASE) and len(text) <= chunk_size * 1.2:
            return [clean_text(text)]
    
    # Fall back to standard chunking for longer text
    return chunk_text(text, chunk_size, overlap)

# Additional utility for advanced domain-specific normalization
def normalize_legal_text(text: str) -> str:
    """Normalize legal text with domain-specific rules.
    
    Args:
        text: The legal text to normalize
        
    Returns:
        Normalized text
    """
    if not text or not isinstance(text, str):
        return ""
    
    # Clean the text first
    text = clean_text(text)
    
    # Normalize section/article references
    text = re.sub(r'[Ss]ection[s]?\s+(\d+[A-Za-z]?)', r'Section \1', text)
    text = re.sub(r'[Aa]rticle[s]?\s+(\d+[A-Za-z]?)', r'Article \1', text)
    
    # Normalize IPC references
    text = re.sub(r'I\.\s*P\.\s*C\.', r'IPC', text)
    text = re.sub(r'Indian\s+Penal\s+Code', r'IPC', text)
    
    # Normalize CrPC references
    text = re.sub(r'Cr\.\s*P\.\s*C\.', r'CrPC', text)
    text = re.sub(r'Criminal\s+Procedure\s+Code', r'CrPC', text)
    
    # Normalize legal abbreviations
    text = re.sub(r'Hon\'ble', r'Honorable', text)
    text = re.sub(r'w\.r\.t\.', r'with respect to', text)
    
    return text

def enhance_text_for_embedding(text: str, document_type: str = 'unknown', metadata: Dict[str, Any] = None) -> str:
    """Enhance text for improved legal domain vector embeddings by adding domain knowledge and structure.
    
    Args:
        text: The original text to enhance
        document_type: Type of legal document
        metadata: Optional metadata to incorporate into the text
        
    Returns:
        Enhanced text optimized for embedding
    """
    if not text or not isinstance(text, str):
        return ""
    
    # First normalize the text
    clean_text_result = normalize_legal_text(text)
    
    # Buffer for enhanced text
    enhanced_parts = []
    
    # Add document type prefix to guide the embedding model
    if document_type == 'ipc':
        enhanced_parts.append("INDIAN PENAL CODE: ")
    elif document_type == 'constitution':
        enhanced_parts.append("INDIAN CONSTITUTION: ")
    elif document_type == 'laws_qa':
        enhanced_parts.append("LEGAL QUESTION AND ANSWER: ")
    
    # Add critical metadata as context
    if metadata:
        metadata_parts = []
        # Document type-specific metadata
        if document_type == 'ipc' and 'section_number' in metadata:
            metadata_parts.append(f"Section {metadata['section_number']}")
        elif document_type == 'constitution' and 'article_number' in metadata:
            metadata_parts.append(f"Article {metadata['article_number']}")
        
        # Add any category or topic
        if 'category' in metadata:
            metadata_parts.append(f"Category: {metadata['category']}")
        if 'topic' in metadata:
            metadata_parts.append(f"Topic: {metadata['topic']}")
            
        # Add keywords if available
        if 'keywords' in metadata and metadata['keywords']:
            if isinstance(metadata['keywords'], list):
                metadata_parts.append(f"Keywords: {', '.join(metadata['keywords'])}")
            else:
                metadata_parts.append(f"Keywords: {metadata['keywords']}")
        
        # Add metadata prefix
        if metadata_parts:
            enhanced_parts.append("[" + "; ".join(metadata_parts) + "] ")
    
    # Add the main text content
    enhanced_parts.append(clean_text_result)
    
    # For IPC sections, add interpretative elements
    if document_type == 'ipc' and 'punishment' in (metadata or {}):
        enhanced_parts.append(f"\nPunishment: {metadata['punishment']}")
    
    # Join all parts
    return " ".join(enhanced_parts)