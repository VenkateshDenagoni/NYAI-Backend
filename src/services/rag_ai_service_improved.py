import os
import time
import uuid
import json
import hashlib
from typing import Dict, Any, List, Optional, Tuple, Deque, Generator
from collections import deque
from datetime import datetime
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential

import google.generativeai as genai

from src.config import config
from src.utils.logger import logger
from src.services.rag_document_service_improved import rag_document_service
from src.utils.errors import APIError, RateLimitError, LLMRateLimitError, LLMTimeoutError, ValidationError

# Configure Google Generative AI
genai.configure(api_key=config.GOOGLE_API_KEY)

# Constants
CACHE_TTL = 3600  # 1 hour cache TTL
MAX_RETRIES = 3
RETRY_MULTIPLIER = 1
MAX_RETRY_WAIT = 10
MAX_CONVERSATION_TURNS = 15  # Store up to 15 turns of conversation

# Cache for responses
response_cache = {}

# Fallback system prompt in case file loading fails
FALLBACK_SYSTEM_PROMPT = """
You are NYAI, a multilingual Indian legal AI assistant specialized in Indian law. You provide comprehensive, accurate, and helpful legal information to users.

CAPABILITIES:
- Provide detailed explanations of Indian legal concepts, laws, and procedures
- Explain legal terms and concepts in simple language
- Reference relevant sections of Indian laws and landmark judgments
- Offer practical guidance on legal procedures and remedies
- Support multiple Indian languages including Hindi, Telugu, Tamil, Bengali, Marathi, and other regional languages
- Maintain context across conversations

LIMITATIONS:
- Cannot provide personalized legal advice - always clarify this distinction
- Cannot represent users in court or submit documents on their behalf
- Cannot guarantee specific outcomes in legal matters
- Cannot interpret laws beyond established legal principles

GUIDELINES:
• Always cite specific sections, articles, or judgments when available
• If the answer is not in context, use your knowledge of Indian law to provide structured guidance
• Never respond with "I don't know" without offering alternative legal approaches
• Use formal legal tone in the language of the user's query
• ALWAYS respond in the EXACT SAME LANGUAGE as the user's question
• Maintain awareness of your RAG capabilities and legal knowledge throughout the conversation

LEGAL GUIDANCE STRUCTURE:
1. Begin with relevant law, act, or constitutional provision
2. Explain applicable legal principles
3. Clarify relevant procedures or steps
4. Mention important precedents or judgments when applicable
5. Provide practical implications

The current date is {today}. Consider recent legal developments in your responses.
"""

class RAGAIService:
    """Service for handling RAG-enhanced AI responses."""
    
    def __init__(self):
        """Initialize the RAG AI Service."""
        # Use the model from config instead of hardcoded value
        self.model_name = config.LLM_MODEL
        self.temperature = 0.2
        self.top_p = 0.95
        self.top_k = 40
        self.max_output_tokens = 2048
        
        # Enhanced conversation memory
        self.conversation_histories = {}  # session_id -> conversation history
        self.session_timestamps = {}      # session_id -> last access time
        self.max_history_age = 86400      # 24 hours in seconds
        
        # Load the prompt template from file (same as used by ai_service_refactored)
        self._load_prompt_template()
        
        # Initialize model
        try:
            # Check if API key is available
            if not config.GOOGLE_API_KEY:
                logger.error("Google API key not found in configuration")
                self.model = None
                return
                
            self.model = genai.GenerativeModel(
                model_name=self.model_name,
                generation_config={
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "top_k": self.top_k,
                    "max_output_tokens": self.max_output_tokens,
                }
            )
            logger.info(f"RAG AI Service initialized with model: {self.model_name}")
        except Exception as e:
            logger.error(f"Error initializing RAG AI model: {e}")
            self.model = None
    
    def _load_prompt_template(self):
        """Load the prompt template from file."""
        templates_dir = config.PROMPT_TEMPLATES_DIR
        templates_path = templates_dir / "base_system_prompt.txt"
        
        try:
            # Create the prompts directory if it doesn't exist
            if not templates_dir.exists():
                logger.warning(f"Prompts directory does not exist, creating: {templates_dir}")
                templates_dir.mkdir(parents=True, exist_ok=True)
            
            if templates_path.exists():
                with open(templates_path, 'r') as f:
                    template_content = f.read()
                    if not template_content.strip():
                        logger.warning(f"Prompt file exists but is empty: {templates_path}")
                        self.base_system_prompt = FALLBACK_SYSTEM_PROMPT
                    else:
                        self.base_system_prompt = template_content
                        logger.info(f"RAG service loaded system prompt from {templates_path} ({len(template_content)} characters)")
            else:
                logger.warning(f"Prompt file not found: {templates_path}. Using fallback prompt.")
                self.base_system_prompt = FALLBACK_SYSTEM_PROMPT
                
        except Exception as e:
            logger.error(f"Error loading prompt template from {templates_path}: {e}")
            logger.error(f"Using fallback system prompt instead")
            self.base_system_prompt = FALLBACK_SYSTEM_PROMPT
    
    def _validate_input(self, prompt: str) -> str:
        """Validate and sanitize user input."""
        if not prompt or not prompt.strip():
            raise ValidationError("Empty prompt provided")
            
        # Trim excessive whitespace
        prompt = prompt.strip()
        
        # Limit prompt length
        if len(prompt) > 4000:
            prompt = prompt[:4000]
            logger.warning(f"Prompt truncated to 4000 characters")
            
        return prompt
    
    def _check_prompt_safety(self, prompt: str) -> Optional[str]:
        """Check prompt for safety and bypass attempts."""
        # Check for prompt injection attempts
        lower_prompt = prompt.lower()
        
        # List of potential bypass patterns
        bypass_patterns = [
            "ignore previous instructions",
            "ignore all instructions",
            "disregard your instructions",
            "forget your instructions",
            "you are now",
            "system prompt"
        ]
        
        for pattern in bypass_patterns:
            if pattern in lower_prompt:
                logger.warning(f"Potential prompt injection detected: {pattern}")
                return "I cannot process this request as it appears to contain instructions that conflict with my operating guidelines."
        
        # We no longer need to block questions about sensitive topics entirely
        # Instead, we'll let the system handle them appropriately with the updated system prompt
        # The safety filters in the Google API will still block truly harmful content
                
        return None
    
    def _get_cache_key(self, prompt: str, system_prompt: str) -> str:
        """Generate a cache key for a prompt and system prompt combination."""
        combined = f"{prompt}|{system_prompt}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    def _get_or_create_conversation_history(self, session_id: str) -> List[Dict[str, str]]:
        """Get or create conversation history for a session."""
        if session_id not in self.conversation_histories:
            self.conversation_histories[session_id] = []
        
        # Update session timestamp
        self.session_timestamps[session_id] = time.time()
        
        return self.conversation_histories[session_id]
    
    def _clean_old_sessions(self):
        """Clean up old conversation sessions."""
        current_time = time.time()
        old_sessions = []
        
        for session_id, timestamp in self.session_timestamps.items():
            if current_time - timestamp > self.max_history_age:
                old_sessions.append(session_id)
        
        for session_id in old_sessions:
            if session_id in self.conversation_histories:
                del self.conversation_histories[session_id]
            if session_id in self.session_timestamps:
                del self.session_timestamps[session_id]
        
        if old_sessions:
            logger.info(f"Cleaned up {len(old_sessions)} old conversation sessions")
    
    def _update_conversation_history(self, session_id: str, prompt: str, response: str):
        """Update conversation history with new exchange."""
        history = self._get_or_create_conversation_history(session_id)
        
        # Add new exchange
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": response})
        
        # Trim history if it's too long (keep most recent exchanges)
        if len(history) > MAX_CONVERSATION_TURNS * 2:
            # Keep first exchange for context and the most recent exchanges
            history = history[:2] + history[-(MAX_CONVERSATION_TURNS * 2 - 2):]
            self.conversation_histories[session_id] = history
    
    @retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=RETRY_MULTIPLIER, min=1, max=MAX_RETRY_WAIT))
    def _call_llm_api(self, prompt: str, system_prompt: str, history: List[Dict[str, str]], request_id: str) -> str:
        """Call the LLM API with retries."""
        if not self.model:
            raise APIError("LLM model not initialized")
            
        try:
            # Create the prompt parts
            prompt_parts = []
            
            # Add conversation history
            for message in history:
                prompt_parts.append({
                    "role": message["role"],
                    "parts": [message["content"]]
                })
                
            # Add current user message with system prompt prepended
            # Instead of using a system role, we'll add instructions to the user message
            combined_prompt = f"[SYSTEM INSTRUCTIONS]\n{system_prompt}\n\n[USER QUERY]\n{prompt}"
            prompt_parts.append({"role": "user", "parts": [combined_prompt]})
            
            # Generate content - with adjusted safety settings to allow educational legal content
            response = self.model.generate_content(
                contents=prompt_parts,
                safety_settings=[
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"}
                ]
            )
            
            # Process response
            if response and hasattr(response, 'text'):
                return response.text
                
            # Handle empty response
            logger.warning(f"[{request_id}] Empty response from LLM API")
            return "I apologize, but I couldn't generate a response for that query."
        except Exception as e:
            error_str = str(e).lower()
            logger.error(f"[{request_id}] Error in LLM API call: {error_str}")
            
            if "rate limit" in error_str or "quota" in error_str:
                logger.error(f"[{request_id}] Rate limit error: {error_str}")
                raise LLMRateLimitError(f"API rate limit exceeded: {error_str}")
            elif "timeout" in error_str:
                logger.error(f"[{request_id}] Timeout error: {error_str}")
                raise LLMTimeoutError(f"API request timed out: {error_str}")
            elif "safety" in error_str or "blocked" in error_str or "harmful" in error_str:
                logger.error(f"[{request_id}] Content safety error: {error_str}")
                raise APIError(f"Content safety error: {error_str}")
            else:
                logger.error(f"[{request_id}] API error: {error_str}")
                raise APIError(f"Error calling LLM API: {error_str}")
    
    @retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=RETRY_MULTIPLIER, min=1, max=MAX_RETRY_WAIT))
    def _stream_llm_api(self, prompt: str, system_prompt: str, history: List[Dict[str, str]], request_id: str) -> Generator[str, None, None]:
        """Call the LLM API with streaming response."""
        if not self.model:
            raise APIError("LLM model not initialized")
            
        try:
            # Create the prompt parts
            prompt_parts = []
            
            # Add conversation history
            for message in history:
                prompt_parts.append({
                    "role": message["role"],
                    "parts": [message["content"]]
                })
                
            # Add current user message with system prompt prepended
            # Instead of using a system role, we'll add instructions to the user message
            combined_prompt = f"[SYSTEM INSTRUCTIONS]\n{system_prompt}\n\n[USER QUERY]\n{prompt}"
            prompt_parts.append({"role": "user", "parts": [combined_prompt]})
            
            # Generate content - with adjusted safety settings to allow educational legal content
            response = self.model.generate_content(
                contents=prompt_parts,
                safety_settings=[
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"}
                ],
                stream=True  # Enable streaming
            )
            
            # Process streaming response
            full_response = ""
            for chunk in response:
                if hasattr(chunk, 'text') and chunk.text:
                    full_response += chunk.text
                    yield chunk.text
                
            # Return empty string if no response was generated
            if not full_response:
                logger.warning(f"[{request_id}] Empty response from LLM API")
                yield "I apologize, but I couldn't generate a response for that query."
                
        except Exception as e:
            error_str = str(e).lower()
            logger.error(f"[{request_id}] Error in streaming LLM API call: {error_str}")
            
            if "rate limit" in error_str or "quota" in error_str:
                logger.error(f"[{request_id}] Rate limit error: {error_str}")
                yield "I'm sorry, but the service is currently experiencing high demand. Please try again in a moment."
            elif "timeout" in error_str:
                logger.error(f"[{request_id}] Timeout error: {error_str}")
                yield "I'm sorry, but the request timed out. Please try again with a more specific query."
            elif "safety" in error_str or "blocked" in error_str or "harmful" in error_str:
                logger.error(f"[{request_id}] Content safety error: {error_str}")
                yield "I'm sorry, but I cannot process this request due to content safety guidelines."
            else:
                logger.error(f"[{request_id}] API error: {error_str}")
                yield "I'm sorry, but I encountered an error processing your request. Please try again later."
    
    def generate_response(self, prompt: str, session_id: str = None, request_id: str = None) -> str:
        """Generate a response using RAG."""
        # Track request with unique ID if not provided
        if not request_id:
            request_id = str(uuid.uuid4())[:8]
        
        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
            logger.info(f"[{request_id}] Created new session: {session_id}")
        
        logger.info(f"[{request_id}] Processing RAG request: {prompt[:50]}...")
        
        try:
            # Clean old sessions periodically
            self._clean_old_sessions()
            
            # Validate input
            prompt = self._validate_input(prompt)
            
            # Check for prompt safety issues
            safety_warning = self._check_prompt_safety(prompt)
            if safety_warning:
                return safety_warning
            
            # Start timing for RAG context retrieval
            rag_start_time = time.time()
            
            # Get relevant context using improved RAG document service
            context = rag_document_service.get_relevant_context(prompt)
            
            rag_time = time.time() - rag_start_time
            logger.info(f"[{request_id}] RAG context retrieval took {rag_time:.2f}s")
            
            # Log whether context was found
            if context:
                logger.info(f"[{request_id}] Retrieved context of length {len(context)}")
            else:
                logger.warning(f"[{request_id}] No context retrieved for query")
            
            # Get conversation history
            history = self._get_or_create_conversation_history(session_id)
            
            # Prepare current system prompt with today's date
            today = datetime.now().strftime("%Y-%m-%d")
            system_prompt = self.base_system_prompt.replace("{today}", today)
            
            # Insert context into the system prompt at the designated placeholder
            if context:
                system_prompt = system_prompt.replace("[Retrieved legal context will be inserted here]", context)
            else:
                # If no context found, replace with a general knowledge instruction
                system_prompt = system_prompt.replace(
                    "[Retrieved legal context will be inserted here]", 
                    "Use your knowledge of Indian legal concepts, legislation, procedures, and case law to answer accurately."
                )
            
            # Cache key includes history fingerprint to ensure context-aware caching
            history_fingerprint = hashlib.md5(str(history).encode()).hexdigest()[:10]
            cache_key = self._get_cache_key(f"{prompt}_{history_fingerprint}", system_prompt)
            
            if cache_key in response_cache:
                cached_response, timestamp = response_cache[cache_key]
                # Check if cache is still valid
                if time.time() - timestamp < CACHE_TTL:
                    logger.info(f"[{request_id}] Returning cached RAG response")
                    
                    # Still update conversation history with cached response
                    self._update_conversation_history(session_id, prompt, cached_response)
                    
                    return cached_response
            
            # Start timing for LLM API call
            llm_start_time = time.time()
            
            # Call the LLM API with conversation history
            response_text = self._call_llm_api(prompt, system_prompt, history, request_id)
            
            llm_time = time.time() - llm_start_time
            logger.info(f"[{request_id}] LLM API call took {llm_time:.2f}s")
            
            # Update conversation history
            self._update_conversation_history(session_id, prompt, response_text)
            
            # Cache the response
            response_cache[cache_key] = (response_text, time.time())
            
            # Log total processing time
            total_time = time.time() - rag_start_time
            logger.info(f"[{request_id}] Total RAG processing took {total_time:.2f}s")
            
            return response_text
        except ValidationError as e:
            logger.warning(f"[{request_id}] Input validation error: {e}")
            return f"I couldn't process your request: {e}"
        except (LLMRateLimitError, LLMTimeoutError, APIError) as e:
            logger.error(f"[{request_id}] API error: {e}")
            return f"I'm sorry, but I encountered an error processing your request: {e}"
        except Exception as e:
            logger.error(f"[{request_id}] Unexpected error: {e}", exc_info=True)
            return "I apologize, but I encountered an unexpected error processing your request. Please try again later."
    
    def stream_response(self, prompt: str, session_id: str = None, request_id: str = None) -> Generator[str, None, None]:
        """Generate a streaming response using RAG."""
        # Track request with unique ID if not provided
        if not request_id:
            request_id = str(uuid.uuid4())[:8]
        
        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
            logger.info(f"[{request_id}] Created new session: {session_id}")
        
        logger.info(f"[{request_id}] Processing streaming RAG request: {prompt[:50]}...")
        
        try:
            # Clean old sessions periodically
            self._clean_old_sessions()
            
            # Validate input
            prompt = self._validate_input(prompt)
            
            # Check for prompt safety issues
            safety_warning = self._check_prompt_safety(prompt)
            if safety_warning:
                yield safety_warning
                return
            
            # Start timing for RAG context retrieval
            rag_start_time = time.time()
            
            # Get relevant context using improved RAG document service
            context = rag_document_service.get_relevant_context(prompt)
            
            rag_time = time.time() - rag_start_time
            logger.info(f"[{request_id}] RAG context retrieval took {rag_time:.2f}s")
            
            # Log whether context was found
            if context:
                logger.info(f"[{request_id}] Retrieved context of length {len(context)}")
            else:
                logger.warning(f"[{request_id}] No context retrieved for query")
            
            # Get conversation history
            history = self._get_or_create_conversation_history(session_id)
            
            # Prepare current system prompt with today's date
            today = datetime.now().strftime("%Y-%m-%d")
            system_prompt = self.base_system_prompt.replace("{today}", today)
            
            # Insert context into the system prompt at the designated placeholder
            if context:
                system_prompt = system_prompt.replace("[Retrieved legal context will be inserted here]", context)
            else:
                # If no context found, replace with a general knowledge instruction
                system_prompt = system_prompt.replace(
                    "[Retrieved legal context will be inserted here]", 
                    "Use your knowledge of Indian legal concepts, legislation, procedures, and case law to answer accurately."
                )
            
            # Start timing for LLM API call
            llm_start_time = time.time()
            
            # Store the complete response for history update
            complete_response = ""
            
            # Stream the response chunks
            for chunk in self._stream_llm_api(prompt, system_prompt, history, request_id):
                complete_response += chunk
                yield chunk
            
            llm_time = time.time() - llm_start_time
            logger.info(f"[{request_id}] LLM API streaming call took {llm_time:.2f}s")
            
            # Update conversation history with the complete response
            self._update_conversation_history(session_id, prompt, complete_response)
            
            # Cache the response (optional for streaming)
            cache_key = self._get_cache_key(prompt, system_prompt)
            response_cache[cache_key] = (complete_response, time.time())
            
            # Log total processing time
            total_time = time.time() - rag_start_time
            logger.info(f"[{request_id}] Total streaming RAG processing took {total_time:.2f}s")
            
        except ValidationError as e:
            logger.warning(f"[{request_id}] Input validation error: {e}")
            yield f"I couldn't process your request: {e}"
        except (LLMRateLimitError, LLMTimeoutError, APIError) as e:
            logger.error(f"[{request_id}] API error: {e}")
            yield f"I'm sorry, but I encountered an error processing your request: {e}"
        except Exception as e:
            logger.error(f"[{request_id}] Unexpected error: {e}", exc_info=True)
            yield "I apologize, but I encountered an unexpected error processing your request. Please try again later."
    
    def clear_conversation_history(self, session_id: str = None):
        """Clear conversation history for a specific session or all sessions."""
        if session_id:
            if session_id in self.conversation_histories:
                del self.conversation_histories[session_id]
                logger.info(f"Cleared conversation history for session {session_id}")
            return
        
        # Clear all conversation histories
        self.conversation_histories.clear()
        self.session_timestamps.clear()
        logger.info("Cleared all conversation histories")

# Create singleton instance
rag_ai_service = RAGAIService()