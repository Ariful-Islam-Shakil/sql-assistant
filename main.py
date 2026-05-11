import uuid
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from app.agents import PlannerAgent, SQLGeneratorAgent, ValidatorAgent, FormatterAgent, MemoryManager
from app.database import execute_query, get_schema_summary
from loguru import logger

app = FastAPI(title="SQL Generator Agent API")

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")

# Initialize agents and memory
planner = PlannerAgent()
generator = SQLGeneratorAgent()
validator = ValidatorAgent()
formatter = FormatterAgent()
memory = MemoryManager()

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None

class QueryResponse(BaseModel):
    session_id: str
    sql: str
    answer: str
    results: List[Dict[str, Any]]

@app.post("/query", response_model=QueryResponse)
async def handle_query(request: QueryRequest):
    session_id = request.session_id or str(uuid.uuid4())
    user_query = request.query
    
    # 1. Get Schema
    schema = get_schema_summary()
    logger.info(f'✅ Schema fetched:\n\n {schema}')
    
    # 2. Plan (Identify tables) 
    try:
        tables = planner.run(user_query, schema)
        logger.info(f'✅ Tables fetched:\n\n {tables}')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Planning error: {str(e)}")
    
    # 3. Generate SQL
    history = memory.get_history(session_id)
    try:
        sql = generator.run(user_query, tables, schema, history)
        logger.info(f'✅ SQL generated:\n\n {sql}')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL generation error: {str(e)}")
    
    # 4. Validate SQL
    validation = validator.run(sql)
    logger.info(f'✅ SQL validated:\n\n {validation}')
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=f"SQL Validation failed: {validation['error']}")
    
    # 5. Execute SQL
    try:
        results = execute_query(sql)
        logger.info(f'✅ SQL executed:\n\n {results}')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL Execution error: {str(e)}")
    
    # 6. Organize Answer
    try:
        answer = formatter.run(user_query, sql, results)
        logger.info(f'✅ Answer organized:\n\n {answer}')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Formatting error: {str(e)}")
    
    # 7. Update Memory
    memory.add_message(session_id, "user", user_query)
    memory.add_message(session_id, "assistant", answer)
    
    return QueryResponse(
        session_id=session_id,
        sql=sql,
        answer=answer,
        results=results
    ) 

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
