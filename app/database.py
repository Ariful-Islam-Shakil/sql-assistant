import os
from sqlalchemy import create_engine, text
from decimal import Decimal
from datetime import datetime, date
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from loguru import logger
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

import csv
import pandas as pd
from datetime import datetime

MAX_ROWS = int(os.getenv("MAX_ROWS", 20))

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
            rows = []
            for row in result.fetchall():
                row_dict = dict(zip(columns, row))
                # Convert Decimals and datetimes for JSON serialization
                for key, value in row_dict.items():
                    if isinstance(value, Decimal):
                        row_dict[key] = float(value)
                    elif isinstance(value, (datetime, date)):
                        row_dict[key] = value.isoformat()
                rows.append(row_dict)
            return rows
        return []

def process_results(rows, sql_query):
    """Processes results: saves to CSV, limits rows, and generates summary."""
    if not rows:
        return {"summary": "No results found.", "rows": [], "csv_path": None}

    # 1. Create Summary
    df = pd.DataFrame(rows)
    num_rows = len(rows)
    
    summary = {
        "total_rows": num_rows,
        "columns": list(df.columns),
    }
    
    # Simple stats for numeric columns
    numeric_cols = df.select_dtypes(include=['number']).columns
    if not numeric_cols.empty:
        summary["numeric_stats"] = df[numeric_cols].describe().to_dict()

    # 2. Save to CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("exports", exist_ok=True)
    csv_filename = f"query_result_{timestamp}.csv"
    csv_path = os.path.join("exports", csv_filename)
    df.to_csv(csv_path, index=False)

    # 3. Limit rows for the LLM
    limited_rows = rows[:MAX_ROWS]
    
    return {
        "summary": summary,
        "rows": limited_rows,
        "csv_path": csv_path,
        "full_results_count": num_rows
    }

def get_schema_summary():
    """Reads schema from schema.md."""
    try:
        with open("schema.md", "r") as f:
            return f.read()
    except FileNotFoundError:
        # Fallback to DB fetch if file missing
        return "Schema file not found. Please refer to database structure."
