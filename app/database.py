import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from loguru import logger
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def execute_query(query: str):
    """Executes a read-only SQL query and returns the results."""
    # Extra safety check
    if not query.lower().strip().startswith("select"):
        raise ValueError("Only SELECT queries are allowed.")
    
    with engine.connect() as connection:
        # We can also set the session to read-only for extra safety
        connection.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"))
        result = connection.execute(text(query))
        if result.returns_rows:
            columns = result.keys()
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            return rows
        return []

def get_schema_summary():
    """Returns a string representation of the database schema for the LLM."""
    with engine.connect() as connection:
        # Get tables
        tables_query = text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """)
        tables = connection.execute(tables_query).fetchall()
        
        schema_summary = []
        for table in tables:
            table_name = table[0]
            cols_query = text(f"""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = '{table_name}'
            """)
            columns = connection.execute(cols_query).fetchall()
            col_desc = ", ".join([f"{col[0]} ({col[1]})" for col in columns])
            schema_summary.append(f"Table {table_name}: {col_desc}")

        return "\n".join(schema_summary)
