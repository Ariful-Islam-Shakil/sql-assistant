import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_schema():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Get all tables
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
    """)
    tables = cur.fetchall()
    
    schema_info = {}
    for table in tables:
        table_name = table[0]
        cur.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}'
        """)
        columns = cur.fetchall()
        schema_info[table_name] = columns
        
    cur.close()
    conn.close()
    return schema_info

if __name__ == "__main__":
    try:
        schema = get_schema()
        for table, columns in schema.items():
            print(f"Table: {table}")
            for col, dtype in columns:
                print(f"  - {col} ({dtype})")
    except Exception as e:
        print(f"Error: {e}")
