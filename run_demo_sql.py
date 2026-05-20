import pyodbc

def run_mssql_query(connection_string: str, query: str) -> list:
    """
    Connects to an MS SQL Server, runs a query, and returns the results.
    Example connection_string: "DRIVER={ODBC Driver 18 for SQL Server};SERVER=my_server;DATABASE=my_db;UID=my_user;PWD=my_password"
    """
    connection = pyodbc.connect(connection_string)
    cursor = connection.cursor()
    
    try:
        cursor.execute(query)
        
        # Check if the query returns rows
        if cursor.description:
            # Map column names to row values to construct a dictionary
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        # Commit and return rowcount for INSERT/UPDATE/DELETE
        connection.commit()
        return {"message": "Query executed successfully", "rows_affected": cursor.rowcount}
        
    except Exception as e:
        connection.rollback()
        return {"error": str(e)}
        
    finally:
        cursor.close()
        connection.close()




from sqlalchemy import create_engine, text

def run_sql_query(connection_uri: str, query: str) -> list:
    """
    Executes a SQL query on any database supported by SQLAlchemy and returns the response.
    
    PostgreSQL URI example: "postgresql+psycopg2://user:password@localhost:5432/mydb"
    MS SQL URI example: "mssql+pyodbc://user:password@server_name/mydb?driver=ODBC+Driver+18+for+SQL+Server"
    """
    # Create the database engine
    engine = create_engine(connection_uri)
    
    # Use context manager to handle connection lifecycle automatically
    with engine.begin() as connection:
        try:
            # text() ensures the query is handled safely by SQLAlchemy
            result = connection.execute(text(query))
            
            # Check if the query returned rows (e.g., SELECT statements)
            if result.returns_rows:
                # Convert rows into a list of dictionaries using mappings()
                return [dict(row) for row in result.mappings()]
            
            # For non-SELECT queries (INSERT, UPDATE, DELETE)
            return {"message": "Query executed successfully", "rows_affected": result.rowcount}
            
        except Exception as e:
            return {"error": str(e)}
