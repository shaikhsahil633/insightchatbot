"""
FastAPI application — main entry point for the NLP Chatbot Dashboard backend.
Provides REST API endpoints for chat, schema info, and health checks.
"""
import time
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from config import settings
from chat_engine import process_question
from database import get_schema_description, get_table_relationships
from llm_provider import get_llm_provider
from dotenv import load_dotenv
from pathlib import Path


# load_dotenv()
load_dotenv(Path(__file__).resolve().parent / ".env")

# ─── App Setup ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="NLP Chatbot Dashboard API",
    description="Natural language query interface for the Effect Manager PostgreSQL database",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    #allow_origins=settings.CORS_ORIGINS,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# In-memory conversation storage (per-session; swap to Redis for production)
conversations: dict = {}


# ─── Request/Response Models ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    session_id: str = Field(default="default")


class ChatResponse(BaseModel):
    answer: str
    sql: Optional[str] = None
    data: Optional[dict] = None
    chart: Optional[dict] = None
    error: Optional[str] = None
    latency_ms: int = 0


class HealthResponse(BaseModel):
    status: str
    database: str
    llm_provider: str
    llm_status: str


# ─── API Endpoints ──────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process a natural language question about the database.
    Returns answer text, SQL query, data results, and optional chart config.
    """
    start_time = time.time()

    # Get conversation history for this session
    history = conversations.get(request.session_id, [])

    # Process the question through the NL-to-SQL pipeline
    result = await process_question(request.question, history)

    # Store in conversation history
    if request.session_id not in conversations:
        conversations[request.session_id] = []

    conversations[request.session_id].append({
        "question": request.question,
        "answer": result["answer"],
        "sql": result.get("sql"),
    })

    # Keep only last 10 turns per session
    if len(conversations[request.session_id]) > 10:
        conversations[request.session_id] = conversations[request.session_id][-10:]

    latency = int((time.time() - start_time) * 1000)

    return ChatResponse(
        answer=result["answer"],
        sql=result.get("sql"),
        data=result.get("data"),
        chart=result.get("chart"),
        error=result.get("error"),
        latency_ms=latency,
    )


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Check the health of all system components."""
    # Check database
    db_status = "healthy"
    try:
        from database import get_connection
        conn = get_connection()
        conn.close()
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    # Check LLM
    llm = get_llm_provider()
    llm_healthy = await llm.health_check()

    return HealthResponse(
        status="ok" if db_status == "healthy" and llm_healthy else "degraded",
        database=db_status,
        llm_provider=settings.LLM_PROVIDER,
        llm_status="healthy" if llm_healthy else "unhealthy",
    )


@app.get("/api/schema")
async def get_schema():
    """Return the database schema metadata for debugging/transparency."""
    return {
        "schema": get_schema_description(),
        "relationships": get_table_relationships(),
        "allowed_tables": settings.ALLOWED_TABLES,
    }


@app.get("/api/suggestions")
async def get_suggestions():
    """Return suggested questions to help users get started."""
    return {
        "suggestions": [
            "What are the top 10 most expensive products at Bilka?",
            "Compare average unit prices between Netto and Rema for the last month",
            "How many products are currently in stock across all retailers?",
            "Show me the price trend for products in the dairy category",
            "Which retailer has the most products on promotion?",
            "What is the average discounted price by retailer?",
            "List the top 5 brands with the most products",
            "How many unique products does each retailer carry?",
        ]
    }


@app.delete("/api/chat/{session_id}")
async def clear_session(session_id: str):
    """Clear conversation history for a session."""
    if session_id in conversations:
        del conversations[session_id]
    return {"status": "cleared"}


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )
