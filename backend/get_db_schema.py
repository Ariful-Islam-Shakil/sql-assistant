from datetime import date, datetime
from decimal import Decimal
import json
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

# Load environment variables early
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Initialize global engine instance safely
engine = None
if DATABASE_URL:
    engine = create_engine(DATABASE_URL)


def get_db_schema(db_url: str) -> dict:
    """Connects to a database and returns a dictionary of all tables,

    their columns, data types, and primary key status.
    """
    if not db_url:
        return {"error": "No database URL provided."}

    try:
        local_engine = create_engine(db_url)
        inspector = inspect(local_engine)
        schema_dict = {}

        for table_name in inspector.get_table_names():
            columns_info = []
            for column in inspector.get_columns(table_name):
                col_type = column["type"]
                type_str = str(col_type)
                
                # Handle ENUM types to provide valid values to the LLM
                if hasattr(col_type, 'enums'):
                    type_str = f"ENUM({', '.join([f'\'{e}\'' for e in col_type.enums])})"
                
                columns_info.append(
                    {
                        "name": column["name"],
                        "type": type_str,
                        "nullable": column.get("nullable"),
                        "default": str(column.get("default"))
                        if column.get("default")
                        else None,
                        "primary_key": column.get("primary_key", 0) > 0,
                    }
                )
            schema_dict[table_name] = columns_info

        # Save as JSON
        with open("schema.json", "w", encoding="utf-8") as f:
            json.dump(schema_dict, f, indent=4)

        return schema_dict
    except Exception as e:
        return {"error": str(e)}


def execute_query(query: str) -> list:
    """Executes a read-only SELECT SQL query and returns serialized results."""
    if not engine:
        raise RuntimeError(
            "Database engine is not initialized. Check your DATABASE_URL."
        )

    # Extra safety check
    if not query.lower().strip().startswith("select"):
        raise ValueError("Only SELECT queries are allowed.")

    with engine.connect() as connection:
        # PostgreSQL specific safety configuration. Remove if utilizing SQLite.
        try:
            connection.execute(
                text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            )
        except Exception:
            pass  # Fallback for target databases that don't support transaction modifiers

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


# --- Execution and Readable Print ---
if __name__ == "__main__":
    if not DATABASE_URL:
        print("Error: DATABASE_URL not found in environment variables.")
    else:
        schema = get_db_schema(DATABASE_URL)
        if "error" in schema:
            print(f"Failed to fetch schema: {schema['error']}")
        else:
            print(f"=== Database Schema Summary ===")
            print(f"Total Tables Found: {len(schema)}\n")

            for table, columns in schema.items():
                print(f"Table: {table}")
                print("-" * (len(table) + 7))
                for col in columns:
                    pk_marker = " [PK]" if col["primary_key"] else ""
                    null_marker = " NULL" if col["nullable"] else " NOT NULL"
                    print(
                        f"  └─ {col['name']}: {col['type']}{pk_marker}{null_marker}"
                    )
                print()
