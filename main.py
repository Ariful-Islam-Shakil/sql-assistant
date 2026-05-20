import uuid
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from app.agents import MainAgent, MemoryManager
from app.database import execute_query, get_schema_summary
from loguru import logger

app = FastAPI(title="SQL Generator Agent API")

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")

# Initialize agents and memory
main_agent = MainAgent()
memory = MemoryManager()

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None

class QueryResponse(BaseModel):
    session_id: str
    sql: str
    answer: str
    results: List[Dict[str, Any]]
    csv_path: Optional[str] = None
    summary: Optional[Any] = None

@app.post("/query", response_model=QueryResponse)
async def handle_query(request: QueryRequest):
    session_id = request.session_id or str(uuid.uuid4())
    user_query = request.query
    
    logger.info(f"🚀 Processing Query for session {session_id}: {user_query}")
    
    # Get History
    history = memory.get_history(session_id)
    
    # Run Agent
    try:
        agent_result = main_agent.run(user_query, history)
    except Exception as e:
        logger.error(f"❌ Main Agent Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Agent Error: {str(e)}")
    
    answer = agent_result["answer"]
    tool_results = agent_result.get("tool_results", {})
    
    # Extract data from tool results
    sql = tool_results.get("sql", "N/A")
    results = tool_results.get("sample_rows", [])
    csv_path = tool_results.get("csv_path")
    summary = tool_results.get("summary")
    
    # Update Memory 
    memory.add_message(session_id, "user", user_query)
    memory.add_message(session_id, "assistant", answer + "\n\n**SQL Used:**\n" + sql)
    
    return QueryResponse(
        session_id=session_id,
        sql=sql,
        answer=answer,
        results=results,
        csv_path=csv_path,
        summary=summary
    )
 

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
