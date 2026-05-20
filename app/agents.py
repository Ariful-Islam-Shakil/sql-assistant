import ollama
import json
import re
import os
from typing import List, Dict, Any, Optional
from app.database import execute_query, get_schema_summary, process_results
from loguru import logger

from decimal import Decimal
from datetime import datetime, date

# Models
MAIN_MODEL = "llama3.1:8b-instruct-q8_0"
SQL_MODEL = "qwen2.5-coder:7b"

def serialize_tool_result(obj):
    """Recursively converts non-serializable objects (like Decimal) to serializable ones."""
    if isinstance(obj, list):
        return [serialize_tool_result(item) for item in obj]
    if isinstance(obj, dict):
        return {k: serialize_tool_result(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj

class ToolRegistry:
    """Registry for tools that the Main Agent can call."""
    
    @staticmethod
    def run_sql_tool(sql: str) -> Dict[str, Any]:
        """
        Validates and runs a SQL query. 
        Returns (result_summary, full_sql_used).
        """
        logger.info(f"🛠️ Tool Calling: run_sql_tool with SQL:\n {sql}")
        
        # 1. Basic Validation
        if not sql.lower().strip().startswith("select"):
            return {"error": "Invalid SQL: Only SELECT queries are allowed."}
        
        forbidden = ["drop", "delete", "insert", "update", "truncate", "alter"]
        for kw in forbidden:
            if re.search(rf"\b{kw}\b", sql.lower()):
                return {"error": f"Invalid SQL: Forbidden keyword '{kw}' detected."}

        # 2. Execution
        try:
            raw_results = execute_query(sql)
            processed = process_results(raw_results, sql)
            return {
                "status": "success",
                "summary": processed["summary"],
                "sample_rows": processed["rows"],
                "csv_path": processed["csv_path"],
                "full_count": processed.get("full_results_count", 0),
                "sql": sql
            }
        except Exception as e:
            logger.error(f"❌ SQL Execution Error: {str(e)}")
            return {"status": "error", "error": str(e), "sql": sql}

    @staticmethod
    def sql_agent_tool(query: str) -> Dict[str, Any]:
        """
        Specialized agent that identifies tables, generates SQL, and validates it.
        Includes self-correction loop.
        """
        logger.info(f"🛠️ Tool Calling: sql_agent_tool for query: {query}")
        
        schema = get_schema_summary()
        
        # 1. Identify relevant tables (Planner)
        planner_prompt = f"""
        You are a database expert. Identify the relevant tables and their relations needed for this query.
        Schema:
        {schema}
        
        Return only a JSON list of table names.
        """
        try:
            planner_resp = ollama.chat(
                model=MAIN_MODEL,
                messages=[{"role": "system", "content": planner_prompt}, {"role": "user", "content": query}],
                format="json"
            )
            tables = json.loads(planner_resp['message']['content'])
        except Exception as e:
            logger.error(f"Planner error: {e}")
            tables = [] # Fallback

        # 2. Generate SQL (Generator) with retry loop
        max_retries = 2
        last_error = None
        sql = ""
        
        for attempt in range(max_retries + 1):
            gen_prompt = f"""
            You are an expert SQL developer. Generate a PostgreSQL query.
            Tables: {tables}
            Schema: {schema}
            
            Rules:
            1. Only SELECT statements.
            2. Valid PostgreSQL.
            3. Raw SQL only, no markdown.
            {f"PREVIOUS ERROR: {last_error}. Please fix the query." if last_error else ""}
            """
            
            gen_resp = ollama.chat(
                model=SQL_MODEL,
                messages=[{"role": "system", "content": gen_prompt}, {"role": "user", "content": query}]
            )
            sql = re.sub(r'```sql|```', '', gen_resp['message']['content']).strip()
            
            # Try to run it internally for validation
            result = ToolRegistry.run_sql_tool(sql)
            if result.get("status") == "success":
                return result
            else:
                last_error = result.get("error")
                logger.warning(f"Retry {attempt+1}: SQL failed with error: {last_error}")

        return {"status": "error", "error": f"Failed to generate valid SQL after retries. Last error: {last_error}", "sql": sql}

class MainAgent:
    """The orchestration agent that interacts with the user and uses tools."""
    
    def __init__(self):
        self.model = MAIN_MODEL
        self.tools = {
            "sql_agent_tool": ToolRegistry.sql_agent_tool,
            "run_sql_tool": ToolRegistry.run_sql_tool
        }
        self.tool_definitions = [
            {
                "type": "function",
                "function": {
                    "name": "sql_agent_tool",
                    "description": "Generates and runs a SQL query for a natural language request. Use this if you don't have a SQL query yet.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The natural language query from the user."}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_sql_tool",
                    "description": "Executes a provided SQL query. Use this if you already have a SQL query in history and want to run it again.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string", "description": "The SQL query to execute."}
                        },
                        "required": ["sql"]
                    }
                }
            }
        ]

    def run(self, user_input: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": """
                    You are a smart database assistant.

                    Use tools only when database access or SQL execution is required.
                    Do not call tools for greetings, explanations, small talk, or general programming questions.

                    If the answer is already available from conversation history, respond directly without tools.
                    Reuse previous SQL queries whenever possible.

                    Use:
                    - sql generation tool → when SQL needs to be created
                    - sql execution tool → when SQL already exists and only execution is needed

                    stricktly follow: 
                        1. Avoid unnecessary tool calls.
                        2. Be concise, accurate, and efficient.
                        3. give an organaize response at final stage
                """
            }
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        print(f"Initilal size of memory : {len(messages)}\n messages:\n {messages}\n\n")

        last_tool_result = None
        
        # Agent Loop: Allow the agent to call tools and process results multiple times
        max_iterations = 5
        for i in range(max_iterations):
            print(f"----- Iteration {i+1} -----\n\n")
            response = ollama.chat(
                model=self.model,
                messages=messages,
                tools=self.tool_definitions
            )
            
            assistant_message = response['message']
            messages.append(assistant_message)

            # If the model wants to call tools
            if "tool_calls" in assistant_message and assistant_message["tool_calls"]:
                for tool_call in assistant_message["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    args = tool_call["function"]["arguments"]
                    
                    if tool_name in self.tools:
                        result = self.tools[tool_name](**args)
                        serialized_result = serialize_tool_result(result)
                        print(f"serialised result:\n {serialized_result}\n\n")
                        last_tool_result = serialized_result
                        messages.append({
                            "role": "tool",
                            "content": json.dumps(serialized_result),
                            "name": tool_name
                        })
                # After handling tool calls, continue the loop to let the LLM process the results
                continue
            
            # If no tool calls, it's the final answer
            return {
                "answer": assistant_message['content'],
                "tool_results": last_tool_result
            }
        
        return {
            "answer": "I reached the maximum number of reasoning steps. Here is what I have so far.",
            "tool_results": last_tool_result
        }

class MemoryManager:
    """Handles session memory."""
    def __init__(self):
        self.sessions: Dict[str, List[Dict[str, str]]] = {}

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        return self.sessions.get(session_id, [])

    def add_message(self, session_id: str, role: str, content: str, tool_calls: Optional[List] = None):
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        msg = {"role": role, "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.sessions[session_id].append(msg)
        if len(self.sessions[session_id]) > 20:
            self.sessions[session_id] = self.sessions[session_id][-20:]
