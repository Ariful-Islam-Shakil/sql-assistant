import json
import requests
from tools import search_papers, get_weather, web_search

MODEL_NAME = "llama3.1:8b"
OLLAMA_URL = "http://localhost:11434/api/chat"

# Mapping tool names to actual functions
TOOLS = {
    "search_papers": search_papers,
    "get_weather": get_weather,
    "web_search": web_search
}

# Native Ollama tool definitions
TOOLS_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "search_papers",
            "description": "Search for academic papers on ArXiv",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic to search for"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 3
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "The city name"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web using DuckDuckGo",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    }
]

SYSTEM_PROMPT = (
    "You are a helpful AI assistant with access to tools. "
    "Use tools when necessary to answer user questions accurately. "
    "If a tool result provides sufficient information, provide a natural language response based on that result."
)

messages = [
    {"role": "system", "content": SYSTEM_PROMPT}
]


def call_llm():
    """Calls Ollama API with tools and current message history."""
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "tools": TOOLS_DEFINITION,
        "stream": False
    }
    response = requests.post(OLLAMA_URL, json=payload)
    response.raise_for_status()
    return response.json()["message"]


def serialize_tool_result(result):
    """Recursively converts tool results (including Pydantic models) to serializable dicts."""
    if isinstance(result, list):
        return [serialize_tool_result(item) for item in result]
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "dict"):
        return result.dict()
    if isinstance(result, dict):
        return {k: serialize_tool_result(v) for k, v in result.items()}
    return result


print(f"--- Running Ollama Agent ({MODEL_NAME}) ---")
print("Type 'exit' to stop.\n")

while True:
    user_input = input("You: ").strip()

    if not user_input:
        continue

    if user_input.lower() in ["exit", "quit"]:
        break

    messages.append({"role": "user", "content": user_input})

    # Agent Loop (handles multiple tool calls in sequence if needed)
    while True:
        try:
            response_message = call_llm()
            messages.append(response_message)

            # Check if the model wants to call a tool
            if "tool_calls" in response_message and response_message["tool_calls"]:
                for tool_call in response_message["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    args = tool_call["function"]["arguments"]

                    print(f"\n🔧 Calling Tool: {tool_name} with args: {args}")

                    if tool_name in TOOLS:
                        try:
                            result = TOOLS[tool_name](**args)
                            serialized_result = serialize_tool_result(result)
                            
                            tool_msg = {
                                "role": "tool",
                                "content": json.dumps(serialized_result),
                            }
                            
                            # Standard OpenAI-compatible fields
                            if "id" in tool_call:
                                tool_msg["tool_call_id"] = tool_call["id"]
                            
                            # Ollama sometimes uses 'name' or 'tool_name'
                            tool_msg["name"] = tool_name
                            
                            messages.append(tool_msg)
                        except Exception as e:
                            print(f"❌ Error executing tool '{tool_name}': {e}")
                            messages.append({
                                "role": "tool",
                                "content": f"Error: {str(e)}",
                                "tool_call_id": tool_call.get("id"),
                                "name": tool_name
                            })
                    else:
                        print(f"⚠️ Unknown tool: {tool_name}")
                        messages.append({
                            "role": "tool",
                            "content": f"Error: Tool '{tool_name}' not found.",
                            "tool_call_id": tool_call.get("id"),
                            "name": tool_name
                        })
                
                # After tool calls are handled, loop back to LLM to process results
                continue
            
            else:
                # Final response from model
                assistant_text = response_message.get("content", "")
                if assistant_text:
                    print(f"\nAssistant: {assistant_text}\n")
                break

        except Exception as e:
            print(f"\n❌ Error calling LLM: {e}")
            break