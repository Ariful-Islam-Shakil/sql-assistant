from functools import wraps
import json
import logging
import os
import time
from typing import Callable, List, Optional
from dotenv import load_dotenv
from get_db_schema import execute_query, get_db_schema
import sqlparse
from pydantic import BaseModel, Field
from config import Settings
import requests

load_dotenv()


# ============================================
# 1. LOGGER SETUP
# ============================================
def setup_logger(name: str = "sql_pipeline", log_file: str = "pipeline.log") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger

    fmt_console = logging.Formatter(fmt="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
    fmt_file = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(funcName)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt_console)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt_file)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


log = setup_logger()
log.setLevel(getattr(logging, Settings.LOG_LEVEL, logging.INFO))


# ============================================
# 2. CONFIGURATION & CLIENT SETUP
# ============================================
settings = Settings()

PLANNER_MODEL = settings.PLANNER_MODEL
CODER_MODEL = settings.CODER_MODEL
DATABASE_URL = settings.DATABASE_URL
SCHEMA_RAW = get_db_schema(DATABASE_URL)
DATABASE_SCHEMA_STR = json.dumps(SCHEMA_RAW, indent=2)

log.info("Schema loaded. Tables found: %s", list(SCHEMA_RAW.keys()) if isinstance(SCHEMA_RAW, dict) else "N/A")


# ============================================
# 3. PROVIDER-AWARE CHAT WRAPPER
# ============================================
def _json_schema_instruction(schema: dict) -> str:
    """Appends a JSON schema instruction to a system prompt for providers that lack native format enforcement."""
    return (
        "\n\nCRITICAL: Your response MUST be a single valid JSON object — "
        "no prose, no markdown fences, no explanations.\n"
        f"It must conform EXACTLY to this JSON schema:\n{json.dumps(schema, indent=2)}"
    )


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences that some providers add despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = text[text.index("\n") + 1:] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[: text.rfind("```")].rstrip()
    return text.strip()



def _sanitize_for_gemini(schema: dict) -> dict:
    """
    Convert a standard JSON Schema (as produced by Pydantic) into a
    Gemini-compatible schema. Gemini rejects:
      - $defs / $ref  (must be fully inlined)
      - title, default, additionalProperties, $schema at any level
      - anyOf containing null  (Pydantic uses for Optional[X]; flatten to X)
    """
    defs = schema.get("$defs", {})

    def resolve(node: dict) -> dict:
        if "$ref" in node:
            ref_key = node["$ref"].split("/")[-1]
            node = dict(defs.get(ref_key, {}))

        if "anyOf" in node:
            non_null = [s for s in node["anyOf"] if s.get("type") != "null"]
            node = dict(non_null[0]) if len(non_null) == 1 else {**node, "anyOf": non_null}

        DISALLOWED = {"title", "default", "additionalProperties", "$schema", "$defs", "$ref", "format"}
        result = {k: v for k, v in node.items() if k not in DISALLOWED}

        if "properties" in result:
            result["properties"] = {k: resolve(v) for k, v in result["properties"].items()}
        if "items" in result:
            result["items"] = resolve(result["items"])
        if "anyOf" in result:
            result["anyOf"] = [resolve(s) for s in result["anyOf"]]

        if "properties" in result and "type" not in result:
            result["type"] = "object"

        return result

    return resolve({k: v for k, v in schema.items() if k != "$defs"})

def chat(
    model: str,
    messages: list,
    response_schema: Optional[dict] = None,
    temperature: float = 0.0,
) -> str:
    """
    Unified chat function that returns the raw string content from the LLM.
    Handles structured-output enforcement per provider.

    Args:
        model:           Model name string.
        messages:        List of {"role": ..., "content": ...} dicts.
        response_schema: Pydantic .model_json_schema() dict. When provided,
                         structured output is requested via the best available
                         mechanism for the active provider.
        temperature:     Sampling temperature (ignored by providers that don't support it).
    """
    provider = settings.LLM_PROVIDER

    # ── Ollama ──────────────────────────────────────────────────────────────
    if provider == "ollama":
        import ollama
        ollama_client = ollama.Client(host=settings.OLLAMA_HOST)
        kwargs = {}
        if response_schema:
            kwargs["format"] = response_schema
        if temperature is not None:
            kwargs["options"] = {"temperature": temperature}
        response = ollama_client.chat(model=model, messages=messages, **kwargs)
        return response["message"]["content"]

    # ── Gemini ───────────────────────────────────────────────────────────────
    elif provider == "gemini":
        # Gemini role mapping: "system" must be passed via systemInstruction,
        # and only "user" / "model" roles are allowed in contents.
        system_parts = []
        contents = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append({"text": m["content"]})
            else:
                gemini_role = "model" if m["role"] == "assistant" else "user"
                contents.append({"role": gemini_role, "parts": [{"text": m["content"]}]})

        payload: dict = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        gen_config: dict = {"temperature": temperature}
        if response_schema:
            gen_config["responseMimeType"] = "application/json"
            gen_config["responseSchema"] = _sanitize_for_gemini(response_schema)
        payload["generationConfig"] = gen_config

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        resp = requests.post(url, params={"key": settings.GEMINI_API_KEY}, json=payload)
        if not resp.ok:
            log.error("Gemini API error %d: %s", resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()
        return (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )

    # ── OpenRouter ───────────────────────────────────────────────────────────
    elif provider == "openrouter":
        msgs = list(messages)
        if response_schema:
            # Inject schema instruction into the system message
            if msgs and msgs[0]["role"] == "system":
                msgs[0] = {**msgs[0], "content": msgs[0]["content"] + _json_schema_instruction(response_schema)}
            else:
                msgs.insert(0, {"role": "system", "content": _json_schema_instruction(response_schema)})

        payload: dict = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
        }
        if response_schema:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        return _strip_json_fences(resp.json()["choices"][0]["message"]["content"])

    # ── Groq ─────────────────────────────────────────────────────────────────
    elif provider == "groq":
        msgs = list(messages)
        if response_schema:
            if msgs and msgs[0]["role"] == "system":
                msgs[0] = {**msgs[0], "content": msgs[0]["content"] + _json_schema_instruction(response_schema)}
            else:
                msgs.insert(0, {"role": "system", "content": _json_schema_instruction(response_schema)})

        payload: dict = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
        }
        if response_schema:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        return _strip_json_fences(resp.json()["choices"][0]["message"]["content"])

    else:
        raise NotImplementedError(f"LLM provider '{provider}' not supported.")


# ============================================
# 4. RETRY DECORATOR
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
                    log.warning("[%s] Attempt %d/%d failed: %s", func.__name__, attempt, retries, e)
                    if attempt < retries:
                        time.sleep(delay)
            log.error("[%s] All %d attempts failed.", func.__name__, retries)
            raise last_exception
        return wrapper
    return decorator


# ============================================
# 5. STRUCTURED OUTPUT MODELS
# ============================================
class ColumnDetail(BaseModel):
    name: str = Field(description="The exact name of the column verbatim from the database schema.")
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
    table_name: str = Field(description="The exact name of the table verbatim from the database schema.")
    table_description: str = Field(
        description="A brief description of this table's role and purpose in answering the query."
    )
    columns: List[ColumnDetail] = Field(
        description="List of ALL columns belonging to this table, including data types and descriptions/enums."
    )
    joins: List[str] = Field(
        default_factory=list,
        description="Explicit JOIN conditions / relationships with other tables, e.g. ['products.brand_id = brands.id'].",
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
        description="One-sentence explanation of what the query does (for logging purposes only).",
    )


# ============================================
# 6. PROMPT BUILDERS
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
# 7. CORE PIPELINE FUNCTIONS
# ============================================
@retry_on_failure(retries=3, delay=2)
def get_sql_plan(user_query: str) -> SQLGenerationPlan:
    log.debug("Calling planner model: %s", PLANNER_MODEL)

    raw = chat(
        model=PLANNER_MODEL,
        messages=[
            {"role": "system", "content": build_planner_system_prompt()},
            {"role": "user", "content": f"User question: {user_query}\n\nProduce the JSON plan now."},
        ],
        response_schema=SQLGenerationPlan.model_json_schema(),
        temperature=0.0,
    )

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

    raw = chat(
        model=CODER_MODEL,
        messages=[
            {"role": "system", "content": build_coder_system_prompt(coder_schema_str)},
            {"role": "user", "content": user_content},
        ],
        response_schema=SQLQueryResponse.model_json_schema(),
        temperature=0.1,
    )

    log.debug("Coder raw response:\n%s", raw)
    result = SQLQueryResponse.model_validate_json(raw)
    log.info("Generated SQL explanation: %s", result.explanation)
    return result


# ============================================
# 8. EXECUTION PIPELINE WITH SELF-CORRECTION
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
            return {"status": "irrelevant", "reason": plan.rewritten_user_query}

        # ── Stage 2 & 3: Generation + Self-Correction loop ────────
        error_msg: Optional[str] = None

        for attempt in range(1, max_correction_attempts + 1):
            log.info("[Stage 2/3] Generating SQL (attempt %d/%d)...", attempt, max_correction_attempts)

            sql_response = generate_final_sql(user_query, plan, error_context=error_msg)
            formatted_sql = sqlparse.format(sql_response.sql_query, reindent=True, keyword_case="upper")

            log.info("[Stage 3/3] Executing SQL (attempt %d/%d):\n%s", attempt, max_correction_attempts, formatted_sql)

            try:
                query_results = execute_query(formatted_sql)
                log.info("✅ Query succeeded on attempt %d/%d", attempt, max_correction_attempts)
                log.debug("Result rows: %d", len(query_results) if isinstance(query_results, list) else -1)
                log.info("Result:\n%s", json.dumps(query_results, indent=2))
                return {
                    "status": "success",
                    "sql": formatted_sql,
                    "results": query_results,
                    "attempt": attempt,
                }

            except Exception as db_error:
                error_msg = str(db_error)
                first_line = error_msg.splitlines()[0] if error_msg else "Unknown DB error"
                log.warning("DB rejected query on attempt %d: %s", attempt, first_line)
                log.debug("Full DB error:\n%s", error_msg)
                if attempt < max_correction_attempts:
                    log.info("Sending error context back to LLM for self-correction...")

        log.error("⛔ PIPELINE FAILED — could not repair query after %d attempts.", max_correction_attempts)
        return {"status": "failed", "last_error": error_msg}

    except Exception as fatal:
        log.exception("⛔ FATAL pipeline error: %s", fatal)
        return {"status": "fatal_error", "error": str(fatal)}


# ============================================
# 9. TEST RUNNER
# ============================================
if __name__ == "__main__":
    practice_queries = [
        # "show me the top 3 most expensive Black shoes for men",
        # "show price and shoe name of all males shoes",
        "Show me all 'men' products from 'Nike' that are in the 'Running' category, including their price and primary image path.",
        "What is the weather like in New York right now?",  # Irrelevant query
    ]

    if isinstance(SCHEMA_RAW, dict) and "error" in SCHEMA_RAW:
        log.critical("Schema load failed — aborting. Error: %s", SCHEMA_RAW["error"])
    else:
        for query in practice_queries:
            result = run_safe_pipeline(query)
            log.info("Pipeline result status: %s\n", result.get("status"))