import ollama
import json
import re
from typing import List, Dict, Any
from app.database import get_schema_summary 

# MODEL = "llama3.1:8b"
MODEL = "llama3.1:8b-instruct-q8_0"
SQL_MODEL = "qwen2.5-coder:7b"

class BaseAgent:
    def __init__(self, model: str = MODEL):
        self.model = model

    def chat(self, messages: List[Dict[str, str]], format: str = "") -> str:
        response = ollama.chat(
            model=self.model,
            messages=messages,
            format=format
        )
        return response['message']['content']

class PlannerAgent(BaseAgent):
    """Analyzes the query and identifies required tables."""
    def run(self, user_query: str, schema: str) -> List[str]:
        system_prompt = f"""
        You are a database expert. Given a user query and a database schema, identify which tables are required to answer the query.
        Return only a JSON list of table names.
        
        Database Schema:
        {schema}
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Query: {user_query}"}
        ]
        response = self.chat(messages, format="json")
        try:
            return json.loads(response)
        except:
            # Fallback to regex if JSON fails
            return re.findall(r'"([^"]*)"', response)

class SQLGeneratorAgent(BaseAgent):
    """Generates the SQL query."""
    def __init__(self, model: str = SQL_MODEL):
        super().__init__(model)

    def run(self, user_query: str, required_tables: List[str], schema: str, history: List[Dict[str, str]] = []) -> str:
        system_prompt = f"""
        You are an expert SQL developer. Generate a PostgreSQL query to answer the user's question.
        Use only the following tables: {', '.join(required_tables)}.
        
        Database Schema:
        {schema}
        
        Rules:
        1. Only use SELECT statements.
        2. Ensure the query is valid PostgreSQL.
        3. Do not include any explanation, just the raw SQL.
        4. Join tables appropriately if needed.
        """
        messages = history + [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Query: {user_query}"}
        ]
        response = self.chat(messages)
        # Clean up the response to get only SQL
        sql = re.sub(r'```sql|```', '', response).strip()
        return sql

class ValidatorAgent(BaseAgent):
    """Validates the query."""
    def run(self, sql: str) -> Dict[str, Any]:
        # Simple rule-based validation first
        if not sql.lower().strip().startswith("select"):
            return {"valid": False, "error": "Only SELECT queries are allowed."}
        
        forbidden_keywords = ["drop", "delete", "insert", "update", "truncate", "alter", "grant", "revoke"]
        for kw in forbidden_keywords:
            if re.search(rf"\b{kw}\b", sql.lower()):
                return {"valid": False, "error": f"Forbidden keyword '{kw}' detected."}
        
        return {"valid": True, "error": None}

class FormatterAgent(BaseAgent):
    """Organizes the final answer."""
    def run(self, user_query: str, sql: str, results: Any) -> str:
        system_prompt = """
        You are a helpful data assistant. Given a user query, the SQL executed, and the results from the database, provide a clear and concise natural language answer.
        If the results are empty, state that no data was found.
        If there are multiple rows, summarize them or present them in a readable format.
        """
        content = f"User Query: {user_query}\nSQL Executed: {sql}\nResults: {json.dumps(results, indent=2, default=str)}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content}
        ]
        return self.chat(messages)

class MemoryManager:
    """Handles session memory."""
    def __init__(self):
        self.sessions: Dict[str, List[Dict[str, str]]] = {}

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        return self.sessions.get(session_id, [])

    def add_message(self, session_id: str, role: str, content: str):
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append({"role": role, "content": content})
        # Keep only last 10 messages
        if len(self.sessions[session_id]) > 10:
            self.sessions[session_id] = self.sessions[session_id][-10:]
