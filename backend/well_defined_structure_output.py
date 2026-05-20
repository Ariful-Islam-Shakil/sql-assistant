from functools import wraps
import json
import logging
import os
import time
from typing import Callable, List, Optional
from dotenv import load_dotenv
from backend.get_db_schema import execute_query, get_db_schema
import ollama
import sqlparse
from pydantic import BaseModel, Field

# ============================================
# 1. LOGGER SETUP
# ============================================
def setup_logger(name: str = "sql_pipeline", log_file: str = "pipeline.log") -> logging.Logger:
    """
    Sets up a logger with both console and file handlers.
    - Console: colored, human-readable output
    - File: full structured logs for debugging
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    fmt_console = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    fmt_file = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(funcName)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler — INFO and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt_console)

    # File handler — DEBUG and above (captures everything)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt_file)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


log = setup_logger()


# ============================================
# 2. CONFIGURATION
# ============================================
load_dotenv()
OLLAMA_HOST    = "http://localhost:11434"
PLANNER_MODEL  = "llama3.1:8b-instruct-q8_0"
CODER_MODEL    = "qwen2.5-coder:7b-instruct-q8_0"

client = ollama.Client(host=OLLAMA_HOST)

DATABASE_URL        = os.getenv("DATABASE_URL")
SCHEMA_RAW          = get_db_schema(DATABASE_URL)
DATABASE_SCHEMA_STR = json.dumps(SCHEMA_RAW, indent=2)

log.info("Schema loaded. Tables found: %s", list(SCHEMA_RAW.keys()) if isinstance(SCHEMA_RAW, dict) else "N/A")
print(20*"=")
print(DATABASE_SCHEMA_STR)
print(20*"=", "\n\n\n")

# ============================================
# 3. RETRY DECORATOR
# ============================================
def retry_on_failure(retries: int = 3, delay: int = 2):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    log.warning(
                        "[%s] Attempt %d/%d failed: %s",
                        func.__name__, attempt, retries, e,
                    )
                    if attempt < retries:
                        time.sleep(delay)
            log.error("[%s] All %d attempts failed.", func.__name__, retries)
            raise last_exception
        return wrapper
    return decorator


# ============================================
# 4. STRUCTURED OUTPUT MODELS
# ============================================
class ColumnDetail(BaseModel):
    name: str = Field(
        description="The exact name of the column verbatim from the database schema."
    )
    data_type: str = Field(
        description="The database data type of the column, e.g. INTEGER, VARCHAR(255), BOOLEAN, ENUM('men', 'women', 'unisex')."
    )
    description: str = Field(
        description=(
            "A brief description of this column. "
            "If the column is an ENUM or has specific values, you MUST list all the allowed values "
            "verbatim (case-sensitive) and specify that using other values will result in a database error."
        )
    )


class TableRelation(BaseModel):
    table_name: str = Field(
        description="The exact name of the table verbatim from the database schema."
    )
    table_description: str = Field(
        description="A brief description of this table's role and purpose in answering the query."
    )
    columns: List[ColumnDetail] = Field(
        description="List of ALL columns belonging to this table, including data types and descriptions/enums."
    )
    joins: List[str] = Field(
        default_factory=list,
        description="Explicit JOIN conditions / relationships with other tables, e.g. ['products.brand_id = brands.id']."
    )


class SQLGenerationPlan(BaseModel):
    rewritten_user_query: str = Field(
        description=(
            "A grammatically correct, spelling-corrected, and clear specification of the request. "
            "It should fix any spelling mistakes, resolve ambiguities, and clarify the query structure. "
            "Describe exactly what to retrieve, what filters to apply, what order, and what limit. "
            "CRITICAL: Do NOT write any SQL syntax here — use natural/technical language only."
        )
    )
    required_tables: List[TableRelation] = Field(
        description=(
            "A structured list of tables needed to answer the question, along with column descriptions "
            "and relationships. If the query is irrelevant or cannot be answered, return an empty list []."
        )
    )
    is_relevant: bool = Field(
        description="True if the question is relevant to the schema and database. False otherwise."
    )


class SQLQueryResponse(BaseModel):
    sql_query: str = Field(
        description=(
            "A single, valid PostgreSQL SELECT statement. "
            "No markdown, no code fences, no explanations — raw SQL only."
        )
    )
    explanation: str = Field(
        default="",
        description="One-sentence explanation of what the query does (for logging purposes only)."
    )


# ============================================
# 5. PROMPT BUILDERS
# ============================================
def build_planner_system_prompt() -> str:
    return f"""You are a database analyst for a shoe store application.
Your only task: read the user question and fill in a JSON plan — nothing else.

DATABASE SCHEMA (PostgreSQL):
{DATABASE_SCHEMA_STR}

STEPS (follow in order):
1. Decide whether the question is answerable from the schema above (is_relevant).
   - Set is_relevant=false for anything unrelated to products, orders, users, inventory, etc.
2. Rewrite the user question as a grammatically correct, spelling-corrected, clear technical specification.
   - Resolve any spelling mistakes, ambiguity, or typos (e.g. map 'males' or 'mans' to 'men').
   - Describe exactly what data to retrieve, what filters to apply, what ordering, and what limit to use.
   - CRITICAL: DO NOT write any SQL syntax or queries in rewritten_user_query. Use plain descriptive English only.
   - For string/enum filter values, specify them EXACTLY as they appear in the schema (e.g. 'men' not 'males', 'Running' not 'running').
3. Identify the required_tables.
   - Each element must be a structured TableRelation object detailing:
     * table_name: exact table name verbatim from the schema.
     * table_description: brief description of its role/purpose in this specific query.
     * columns: A list of ALL columns belonging to this table according to the schema.
       For EACH column, specify its name, its exact data_type, and its description.
       CRITICAL: If a column has ENUM values, you MUST list every single allowed ENUM value exactly as defined in the schema.
       Note that any value mismatch/casing mismatch in the query will trigger database execution failure.
     * joins: list of explicit JOIN conditions relating this table to others, e.g. ['products.brand_id = brands.id'].
   - If is_relevant=false, set required_tables=[].

CRITICAL RULES FOR ACCURATE COLUMN-TO-TABLE MAPPING:
1. NEVER assume a column belongs to a table. You MUST look up each column in the provided SCHEMA JSON.
2. For example, in this schema, the 'color' and 'size' columns do NOT exist in the 'products' table. They exist in the 'product_variants' table. Therefore, if the user asks for a specific color (like 'Black') or size, you MUST include 'product_variants' in required_tables, and define the columns and joins accordingly.
3. If the columns needed to answer a query are spread across multiple tables, you MUST list ALL of those tables in required_tables. Do not merge or combine columns of different tables.
4. Each TableRelation in required_tables must ONLY contain columns that are physically listed under that table in the DATABASE SCHEMA. Never list a column under Table A if the schema shows it belongs to Table B.

OUTPUT RULES:
- Respond ONLY with the JSON object. No prose, no markdown, no code fences.
- Do not hallucinate table or column names. Only reference what exists in the schema.
"""


def build_coder_system_prompt(schema_str: str) -> str:
    return f"""You are an expert PostgreSQL query writer for a shoe store database.
Your task is to convert a data-retrieval instruction and a structured metadata plan (which includes required tables, columns, and relationships) into a single executable SQL query.

DATABASE SCHEMA (PostgreSQL):
{schema_str}

STRICT RULES — each violation will cause a runtime error:
1. sql_query must be a raw SQL SELECT statement ONLY.
   No markdown, no ```sql fences, no inline comments, no explanations.
2. Use ONLY table and column names that exist verbatim in the schema. Never invent names.
3. String/ENUM literals must match the schema exactly (case-sensitive).
   Example: 'Male' not 'male', 'Running' not 'running'.
4. Always qualify column names with their table (e.g. products.name, not just name).
5. Use explicit JOIN … ON syntax. Never use implicit comma-joins. Relate tables using the joins listed in the metadata plan.
6. Prefer JOINs over subqueries unless a subquery is strictly necessary.
7. If a row limit is needed, add LIMIT at the end.
8. The query must run on PostgreSQL 14+ without modification.
9. Respond ONLY with the JSON object matching the required schema. No extra text.
"""


# ============================================
# 6. CORE PIPELINE FUNCTIONS
# ============================================
@retry_on_failure(retries=3, delay=2)
def get_sql_plan(user_query: str) -> SQLGenerationPlan:
    log.debug("Calling planner model: %s", PLANNER_MODEL)

    response = client.chat(
        model=PLANNER_MODEL,
        messages=[
            {"role": "system", "content": build_planner_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"User question: {user_query}\n\n"
                    "Produce the JSON plan now."
                ),
            },
        ],
        format=SQLGenerationPlan.model_json_schema(),
    )

    raw = response["message"]["content"]
    log.debug("Planner raw response:\n%s", raw)
    plan = SQLGenerationPlan.model_validate_json(raw)
    log.info("Plan — relevant=%s | tables=%s", plan.is_relevant, [t.table_name for t in plan.required_tables])
    return plan


@retry_on_failure(retries=3, delay=1)
def generate_final_sql(
    user_query: str,
    plan: SQLGenerationPlan,
    error_context: Optional[str] = None,
) -> SQLQueryResponse:
    log.debug("Calling coder model: %s", CODER_MODEL)

    # Filter SCHEMA_RAW to only include the required tables that the planner returned
    allowed_table_names = [t.table_name for t in plan.required_tables]
    coder_schema = {
        table: SCHEMA_RAW[table]
        for table in allowed_table_names
        if isinstance(SCHEMA_RAW, dict) and table in SCHEMA_RAW
    }
    coder_schema_str = json.dumps(coder_schema, indent=2)

    required_tables_json = json.dumps([t.model_dump() for t in plan.required_tables], indent=2)
    user_content = (
        f"Data-retrieval instruction: {plan.rewritten_user_query}\n\n"
        f"Required tables and metadata:\n{required_tables_json}\n"
    )

    if error_context:
        user_content += (
            f"\n\n--- PREVIOUS QUERY FAILED ---\n"
            f"Database error: {error_context}\n\n"
            f"Common causes to check:\n"
            f"  • ENUM value casing (e.g. 'Male' vs 'male')\n"
            f"  • Column name typos — recheck schema\n"
            f"  • Missing table alias in JOIN\n"
            f"  • Syntax incompatible with PostgreSQL 14\n"
            f"Fix the query and return corrected JSON."
        )

    response = client.chat(
        model=CODER_MODEL,
        messages=[
            {"role": "system", "content": build_coder_system_prompt(coder_schema_str)},
            {"role": "user", "content": user_content},
        ],
        format=SQLQueryResponse.model_json_schema(),
        options={"temperature": 0.1},
    )

    raw = response["message"]["content"]
    log.debug("Coder raw response:\n%s", raw)
    result = SQLQueryResponse.model_validate_json(raw)
    log.info("Generated SQL explanation: %s", result.explanation)
    return result


# ============================================
# 7. EXECUTION PIPELINE WITH SELF-CORRECTION
# ============================================
def run_safe_pipeline(user_query: str, max_correction_attempts: int = 3):
    log.info("=" * 60)
    log.info("PIPELINE START  |  query: %s", user_query)
    log.info("=" * 60)

    try:
        # ── Stage 1: Planning ──────────────────────────────────────
        log.info("[Stage 1/3] Running planner...")
        plan = get_sql_plan(user_query)

        log.info("Execution plan:\n%s", plan.model_dump_json(indent=2))

        if not plan.is_relevant or not plan.required_tables:
            log.warning("PIPELINE HALTED — query not relevant to schema.")
            log.warning("Reason: %s", plan.rewritten_user_query)
            return {
                "status": "irrelevant",
                "reason": plan.rewritten_user_query,
            }

        # ── Stage 2 & 3: Generation + Self-Correction loop ────────
        error_msg: Optional[str] = None

        for attempt in range(1, max_correction_attempts + 1):
            log.info("[Stage 2/3] Generating SQL (attempt %d/%d)...", attempt, max_correction_attempts)

            sql_response = generate_final_sql(user_query, plan, error_context=error_msg)
            raw_sql      = sql_response.sql_query

            formatted_sql = sqlparse.format(raw_sql, reindent=True, keyword_case="upper")

            log.info("[Stage 3/3] Executing SQL (attempt %d/%d):\n%s", attempt, max_correction_attempts, formatted_sql)

            try:
                query_results = execute_query(formatted_sql)

                log.info("✅ Query succeeded on attempt %d/%d", attempt, max_correction_attempts)
                log.debug("Result rows: %d", len(query_results) if isinstance(query_results, list) else -1)
                log.info("Result:\n%s", json.dumps(query_results, indent=2))

                return {
                    "status":  "success",
                    "sql":     formatted_sql,
                    "results": query_results,
                    "attempt": attempt,
                }

            except Exception as db_error:
                error_msg       = str(db_error)
                first_line      = error_msg.splitlines()[0] if error_msg else "Unknown DB error"
                log.warning("DB rejected query on attempt %d: %s", attempt, first_line)
                log.debug("Full DB error:\n%s", error_msg)

                if attempt < max_correction_attempts:
                    log.info("Sending error context back to LLM for self-correction...")

        log.error(
            "⛔ PIPELINE FAILED — could not repair query after %d attempts.",
            max_correction_attempts,
        )
        return {"status": "failed", "last_error": error_msg}

    except Exception as fatal:
        log.exception("⛔ FATAL pipeline error: %s", fatal)
        return {"status": "fatal_error", "error": str(fatal)}


# ============================================
# 8. TEST RUNNER
# ============================================
if __name__ == "__main__":
    practice_queries = [
        "show me the top 3 most expensive Black shoes for men",
        "show price and shoe name of all males shoes",
        "Show me all 'men' products from 'Nike' that are in the 'Running' category, including their price and primary image path.",
        "What is the weather like in New York right now?",  # Irrelevant query
    ]

    if isinstance(SCHEMA_RAW, dict) and "error" in SCHEMA_RAW:
        log.critical("Schema load failed — aborting. Error: %s", SCHEMA_RAW["error"])
    else:
        for query in practice_queries:
            result = run_safe_pipeline(query)
            log.info("Pipeline result status: %s\n", result.get("status"))