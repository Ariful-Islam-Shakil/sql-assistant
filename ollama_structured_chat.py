import requests
from pydantic import BaseModel, Field
from typing import List
import json

# -----------------------------
# Configuration
# -----------------------------
MODEL_NAME = "llama3.1:8b"
OLLAMA_URL = "http://localhost:11434/api/chat"

# -----------------------------
# Pydantic Schema
# -----------------------------
class StructuredResponse(BaseModel):
    answer: str
    key_points: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

# -----------------------------
# Chat Memory
# -----------------------------
messages = [
    {
        "role": "system",
        "content": (
            "You are a helpful AI assistant. "
            "Always respond in STRICT JSON format like this:\n"
            "{"
            "\"answer\": string, "
            "\"key_points\": [string], "
            "\"confidence\": float between 0 and 1"
            "}"
        )
    }
]

print(f"\nRunning {MODEL_NAME}")
print("Type 'exit' to stop.\n")

# -----------------------------
# Chat Loop
# -----------------------------
while True:
    user_input = input("You: ").strip()

    if user_input.lower() in ["exit", "quit", "bye"]:
        print("\nStopping model...")
        break

    messages.append({
        "role": "user",
        "content": user_input
    })

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()

        data = response.json()
        raw_output = data["message"]["content"]

        # -----------------------------
        # Parse JSON safely
        # -----------------------------
        try:
            structured_data = StructuredResponse.model_validate_json(raw_output)
        except Exception as e:
            print("\n⚠️ Model did not return valid JSON.")
            print("Raw output:\n", raw_output)
            continue

        # -----------------------------
        # Print structured output
        # -----------------------------
        print("\nAssistant Response")
        print("Answer:", structured_data.answer)
        print("Key Points:", structured_data.key_points)
        print("Confidence:", structured_data.confidence, "\n")

        # Save memory (store raw JSON)
        messages.append({
            "role": "assistant",
            "content": structured_data.model_dump_json()
        })

    except requests.exceptions.RequestException as e:
        print(f"\nError: {e}\n")