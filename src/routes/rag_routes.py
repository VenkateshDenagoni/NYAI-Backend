from flask import Blueprint, request, jsonify, g, Response, stream_with_context
import uuid
import time
import json

from src.config import config
from src.middleware import rate_limit, auth_required
from src.utils.logger import logger
from src.utils.errors import ValidationError, NotFoundError
from src.services.rag_ai_service_improved import rag_ai_service

# Create blueprint
rag_routes = Blueprint("rag_routes", __name__, url_prefix="/api/rag")

# Dictionary to store feedback data (in-memory, non-persistent)
# This would ideally be replaced with a proper database in the future
feedback_store = {}

@rag_routes.route("/query", methods=["POST"])
@rate_limit()
@auth_required
def rag_query():
    """
    Generate streaming AI response using the RAG system.
    
    Accepts a JSON payload with:
    - query: The user's query
    - session_id: (Optional) Session ID for conversation continuity
    - filters: (Optional) Dictionary of metadata filters to apply
    - search_method: (Optional) Search method to use ("vector", "keyword", or "hybrid")
    
    Returns:
    - A streaming response with chunks of the AI response
    """
    # Start request timing
    start_time = time.time()
    
    # Get request data
    data = request.json
    if not data:
        return jsonify({"error": "Missing request body"}), 400
        
    if "query" not in data:
        return jsonify({"error": "Missing 'query' field"}), 400
    
    # Get or create session ID for conversation context
    session_id = data.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())
        logger.info(f"Created new session: {session_id}")
    
    # Extract search parameters
    filters = data.get("filters", {})
    search_method = data.get("search_method", "hybrid")
    
    # Validate search method
    if search_method not in ["vector", "keyword", "hybrid"]:
        search_method = "hybrid"
    
    # Create request ID for tracking
    request_id = g.get('request_id')
    
    # Get context with filters
    from src.services.rag_document_service_improved import rag_document_service
    context = rag_document_service.get_relevant_context(
        query=data["query"],
        filters=filters,
        search_method=search_method
    )
    
    @stream_with_context
    def generate():
        # Send session and search info first - modified to match frontend expected format
        yield json.dumps({
            "type": "init", 
            "data": {
                "session_id": session_id,
                "search_method": search_method,
                "filters_applied": bool(filters)
            }
        }) + "\n"
        
        # Stream the response chunks - modified to match frontend expected format
        for chunk in rag_ai_service.stream_response(
            prompt=data["query"],
            session_id=session_id,
            request_id=request_id
        ):
            yield json.dumps({
                "type": "content", 
                "data": {
                    "content": chunk
                }
            }) + "\n"
            
        # Send completion indicator with timing - modified to match frontend expected format
        processing_time = time.time() - start_time
        yield json.dumps({
            "type": "done", 
            "data": {
                "timing": {
                    "total_ms": round(processing_time * 1000, 0)
                },
                "request_id": request_id or "unknown"
            }
        }) + "\n"
    
    return Response(generate(), mimetype="application/x-ndjson")

@rag_routes.route("/status", methods=["GET"])
def rag_status():
    """
    Get RAG system status.
    
    Returns:
    - JSON with RAG system status
    """
    from src.services.rag_document_service_improved import rag_document_service
    
    # Check RAG document service status
    chroma_status = "healthy" if rag_document_service.chroma_client else "unavailable"
    embedding_status = "healthy" if rag_document_service.embedding_function else "unavailable"
    
    # Get document counts and session counts
    doc_count = len(rag_document_service.documents)
    session_count = len(rag_ai_service.conversation_histories)
    
    return jsonify({
        "status": "healthy",
        "components": {
            "chromadb": chroma_status,
            "embedding_function": embedding_status
        },
        "documents": {
            "count": doc_count
        },
        "sessions": {
            "active_count": session_count
        },
        "version": config.VERSION
    })

@rag_routes.route("/sessions/<session_id>", methods=["DELETE"])
@auth_required
def delete_session(session_id):
    """
    Delete a specific conversation session.
    
    Path parameters:
    - session_id: ID of the session to delete
    
    Returns:
    - JSON with status message
    """
    if not session_id:
        raise ValidationError("Missing session ID")
    
    # Check if session exists
    if session_id not in rag_ai_service.conversation_histories:
        raise NotFoundError(f"Session {session_id} not found")
    
    # Clear conversation history for session
    rag_ai_service.clear_conversation_history(session_id)
    
    return jsonify({
        "status": "success", 
        "message": f"Session {session_id} deleted"
    })

@rag_routes.route("/sessions", methods=["DELETE"])
@auth_required
def delete_all_sessions():
    """
    Delete all conversation sessions.
    
    Returns:
    - JSON with status message
    """
    # Get session count before deletion
    session_count = len(rag_ai_service.conversation_histories)
    
    # Clear all conversation histories
    rag_ai_service.clear_conversation_history()
    
    return jsonify({
        "status": "success", 
        "message": f"All {session_count} sessions deleted"
    })

@rag_routes.route("/feedback", methods=["POST"])
@auth_required
def submit_feedback():
    """
    Submit feedback for a RAG response.
    
    Accepts a JSON payload with:
    - session_id: Session ID that the response was generated for
    - query: The original query
    - response: The response that feedback is for
    - rating: Numeric rating (1-5) or boolean (thumbs up/down)
    - comment: Optional comment explaining the rating
    
    Returns:
    - JSON with status message
    """
    # Get request data
    data = request.json
    if not data:
        return jsonify({"error": "Missing request body"}), 400
        
    # Extract feedback data
    session_id = data.get("session_id")
    query = data.get("query")
    response = data.get("response")
    rating = data.get("rating")
    comment = data.get("comment", "")
    
    # Validate required fields
    if not session_id:
        return jsonify({"error": "Missing 'session_id' field"}), 400
    if not query:
        return jsonify({"error": "Missing 'query' field"}), 400
    if not response:
        return jsonify({"error": "Missing 'response' field"}), 400
    if rating is None:
        return jsonify({"error": "Missing 'rating' field"}), 400
    
    # Generate a unique ID for this feedback item
    feedback_id = str(uuid.uuid4())
    
    # Store feedback
    feedback_store[feedback_id] = {
        "session_id": session_id,
        "query": query,
        "response": response,
        "rating": rating,
        "comment": comment,
        "timestamp": time.time(),
        "ip_address": request.remote_addr,
        "user_agent": request.headers.get("User-Agent", "Unknown")
    }
    
    logger.info(f"Feedback received: ID={feedback_id}, Rating={rating}, Session={session_id}")
    
    # Log for analysis (this could be extended to write to a database or file)
    if rating <= 2 if isinstance(rating, int) else not rating:
        logger.warning(f"Low rating feedback: ID={feedback_id}, Query={query[:50]}...")
    
    return jsonify({
        "status": "success",
        "feedback_id": feedback_id,
        "message": "Thank you for your feedback"
    })

@rag_routes.route("/feedback/<feedback_id>", methods=["GET"])
@auth_required
def get_feedback(feedback_id):
    """
    Get specific feedback by ID.
    
    Path parameters:
    - feedback_id: ID of the feedback to retrieve
    
    Returns:
    - JSON with feedback details
    """
    if feedback_id not in feedback_store:
        return jsonify({"error": f"Feedback with ID {feedback_id} not found"}), 404
        
    return jsonify(feedback_store[feedback_id])

@rag_routes.route("/feedback", methods=["GET"])
@auth_required
def get_all_feedback():
    """
    Get all feedback.
    
    Query parameters:
    - session_id: (Optional) Filter by session ID
    - min_rating: (Optional) Filter by minimum rating
    - max_rating: (Optional) Filter by maximum rating
    
    Returns:
    - JSON with list of feedback items
    """
    session_id = request.args.get("session_id")
    min_rating = request.args.get("min_rating")
    max_rating = request.args.get("max_rating")
    
    # Apply filters
    results = feedback_store.values()
    
    if session_id:
        results = [f for f in results if f["session_id"] == session_id]
        
    if min_rating is not None:
        min_rating = float(min_rating)
        results = [f for f in results if f["rating"] >= min_rating]
        
    if max_rating is not None:
        max_rating = float(max_rating)
        results = [f for f in results if f["rating"] <= max_rating]
    
    return jsonify({
        "count": len(results),
        "feedback": list(results)
    })