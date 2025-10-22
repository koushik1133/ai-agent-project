import os
import json
import google.generativeai as genai
from supabase import create_client
from dotenv import load_dotenv

# ------------------------------
# Load environment and configure
# ------------------------------
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials missing in environment.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------------------
# Gemini helper
# ------------------------------
def call_gemini(prompt: str):
    """
    Ask Gemini to return strict JSON. No regex. No cleanup.
    If the model doesn't return JSON, raise a clear error.
    """
    model = genai.GenerativeModel(
        "gemini-2.0-flash",
        generation_config={
            # Force JSON output
            "response_mime_type": "application/json",
            # Make it more deterministic
            "temperature": 0.1,
            "top_p": 0.0,
        },
    )
    resp = model.generate_content(prompt)

    # The SDK usually gives .text as a JSON string when response_mime_type is set
    payload = (resp.text or "").strip()
    if not payload:
        raise ValueError("Gemini returned empty response (expected JSON).")

    try:
        return json.loads(payload)
    except json.JSONDecodeError as e:
        # Surface the raw text to debug prompt issues quickly
        raise ValueError(f"Gemini did not return valid JSON. Raw: {payload[:200]} ... Error: {e}")

# ------------------------------
# Column discovery
# ------------------------------
def get_table_columns_safe(table_name: str):
    """Safely fetch column names from the get_table_columns RPC."""
    try:
        print(f"Fetching columns for table: {table_name}")
        res = supabase.rpc("get_table_columns", {"p_table": table_name}).execute()
        return [r["column_name"] for r in res.data] if res.data else []
    except Exception as e:
        print(f"Schema fetch error for {table_name}: {e}")
        return []

# ------------------------------
# Filtering tools (select + eq/match)
# ------------------------------
def apply_eq_filter(query, key, value):
    print(f"Applying eq filter: {key} = {value}")
    return query.eq(key, value)

def apply_match_filter(query, conditions):
    print(f"Applying match filter for: {conditions}")
    return query.match(conditions)

def apply_select_filter(table_name: str, columns=None):
    """Builds base select query."""
    if columns and isinstance(columns, list):
        column_str = ", ".join(columns)
    elif isinstance(columns, str):
        column_str = columns
    else:
        column_str = "*"
    print(f"Selecting columns: {column_str}")
    return supabase.table(table_name).select(column_str)

def build_filtered_query(table_name: str, conditions: dict = None, columns=None):
    """Combine select() and equality filters."""
    query = apply_select_filter(table_name, columns)
    if not conditions:
        print("No conditions — selecting all rows.")
        return query
    if len(conditions) == 1:
        key, val = next(iter(conditions.items()))
        return apply_eq_filter(query, key, val)
    return apply_match_filter(query, conditions)

# ------------------------------
# Main Root Agent
# ------------------------------
def root_agent(user_prompt: str):
    """
    Dynamically interprets user intent, builds JSON query via Gemini,
    and executes Supabase CRUD operations.
    """
    try:
        # Step 1 – Identify table name
        table_prompt = (
            "Respond ONLY with valid JSON.\n"
            "Extract the table name from the user request.\n"
            "Format: {\"table\": \"<table_name>\"}\n\n"
            f"User request: {user_prompt}"
        )
        table_json = call_gemini(table_prompt)
        table_name = table_json.get("table")

        if not table_name:
            return {"error": True, "message": "Could not extract table name."}

        # Step 2 – Fetch schema
        columns = get_table_columns_safe(table_name)
        if not columns:
            return {"error": True, "message": f"No columns found for table '{table_name}'."}

        # Step 3 – Ask Gemini for structured Supabase JSON
        query_prompt = (
            "You are a Supabase Root Agent. Output only valid JSON.\n"
            "Available actions: insert, read, update, delete.\n"
            f"Table name: {table_name}\n"
            f"Columns: {columns}\n\n"
            "Examples:\n"
            f'User: Get the id of Alice in table {table_name}\n'
            f'→ {{"action": "read", "table": "{table_name}", "columns": ["id"], "conditions": {{"name": "Alice"}}}}\n'
            'User: Get all records from employees\n'
            '→ {"action": "read", "table": "employees"}\n'
            f'User request: {user_prompt}'
        )
        # query_response = call_gemini(query_prompt)
        parsed = call_gemini(query_prompt)

        print("Parsed Gemini output:", parsed)

        # Step 4 – Execute - TODO
        action = parsed.get("action")
        data = parsed.get("data") or parsed.get("values")
        conditions = parsed.get("conditions")
        select_columns = parsed.get("columns")

        if not action:
            return {"error": True, "message": "Missing action in Gemini output."}

        # Filter data against schema
        if data:
            if isinstance(data, list):
                data = [{k: v for k, v in row.items() if k in columns} for row in data]
            else:
                data = {k: v for k, v in data.items() if k in columns}

        # CRUD logic
        if action == "insert":
            # TODO Insert
            rows = data if isinstance(data, list) else [data]
            result = supabase.table(table_name).insert(rows).execute()        
            return {"message": f" inserted {len(rows)} rows into the table {table_name}"}
            
        elif action == "read":
            # TODO Select
            query = build_filtered_query(table_name, conditions, select_columns)
            result = query.execute()
            return {"message": f"inserted"}

            

        # elif action == "update":
        #     # TODO Update
    

        # elif action == "delete":
        #     # TODO Delete

        else:
            return {"error": True, "message": f"Unsupported action: {action}"}

    except json.JSONDecodeError as e:
        return {"error": True, "message": f"Gemini returned invalid JSON: {e}"}
    except Exception as e:
        print("Execution error:", e)
        return {"error": True, "message": f"Execution error: {str(e)}"}