# Daily Engineering Activity Report

This report summarizes the progress made on the **Agentic SQL Pipeline**, focusing on implementing a robust, self-healing architecture for translating natural language queries into validated PostgreSQL statements using local LLM orchestration (Ollama).


## Topics & Features Discussed

*   **Database Schema Extraction Utility**: Created an automated database introspection function using SQLAlchemy's `inspect` module (in `get_db_schema.py`) to dynamically extract tables, column names, raw data types, nullability, and primary key constraints.
*   **Structured AI Planning & Coding Architecture**: Implemented a multi-model agent pipeline using Ollama. Used `llama3.1:8b-instruct-q8_0` for structural planning and validation, and `qwen2.5-coder:7b` for precise SQL translation.
*   **Automated Query Safety Gatekeeping**: Configured Pydantic structure schemas to inspect incoming user queries at the structural planning stage. Queries outside the schema bounds are flagged as irrelevant and halted before execution.
*   **Self-Correction Runtime Execution Engine**: Developed an iterative self-healing query cycle that executes SQL, captures database engine errors, and feeds the error context back into the coding agent for automatic syntax correction.

---

## Problems Encountered

1.  **JSON Serialization Type Crashes**: Raw database extraction yielded native SQLAlchemy column types and complex objects (Decimal, datetime) which caused serialization errors in `json.dumps()`.
2.  **Case-Sensitive Enum Rejections**: The model initially generated lowercase string filters (e.g., `WHERE gender = 'male'`) for PostgreSQL ENUMs, resulting in `psycopg2.errors.InvalidTextRepresentation` errors against case-strict configurations (e.g., 'Male').
3.  **Third-Party Formatter Failures**: Passing uppercase configuration variables (e.g., `keyword_case='UPPER'`) directly to `sqlparse.format()` caused issues as the parser expects lowercase argument keys (e.g., `'upper'`).
4.  **Planner Constraint Distortions**: The structural planning model occasionally overextended its instructions by adding arbitrary filter restrictions that mutated the original intent of the user queries.

---

## Solved Problems & Resolutions

*   **Robust Type Casting & Handling**: Explicitly coerced database types to serializable formats. Added logic to convert `Decimal` to `float` and `date`/`datetime` instances to `isoformat()` strings before JSON operations.
*   **Runtime Database Exception Feedback Loop**: Implemented a `max_correction_attempts` loop. If execution fails, the system intercepts the precise database engine error message and appends it to the prompt context for real-time model resolution.
*   **Syntax & Key Adjustments**: Rectified the string case parameters for `sqlparse` configuration and added defensive error handling to prevent formatter glitches from cascading into pipeline failures.
*   **Intent Preservation Tuning**: Refined system prompts to strictly define the boundary between layout formatting and raw intent preservation. The planner now validates structural relevance without inventing arbitrary constraints.

---

## Technical Progress Summary

### File Architecture
*   **`app/database.py`**: Houses connection engines, metadata readers, table schema parsers, and safe transaction runner routines.
*   **`app/agents.py`**: Contains the `MainAgent` orchestration logic, tool definitions, and the specialized `sql_agent_tool` with its self-correction loop.
*   **`main.py`**: The FastAPI entry point serving the web interface and API endpoints.
*   **`well_defined_structure_output.py`**: A standalone implementation of the structured pipeline featuring Pydantic validation and comprehensive logging.

### Active Tech Stack
*   **Language**: Python 3.10+
*   **Database**: SQLAlchemy Core, psycopg2 (PostgreSQL)
*   **AI Integration**: Ollama local client API
*   **Validation & Formatting**: Pydantic (V2), `sqlparse`, `loguru`

---

If your tracker requires specific metrics, let me know if you want to add details regarding average execution times, token efficiency rates, or model generation temperatures.


