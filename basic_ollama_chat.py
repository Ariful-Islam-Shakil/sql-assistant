import requests
import json

# -----------------------------
# Configuration
# -----------------------------
MODEL_NAME = "llama3.1:8b"
OLLAMA_URL = "http://localhost:11434/api/chat"

# -----------------------------
# Chat Memory
# -----------------------------
messages = [
    {
        "role": "system",
        "content": (
            "You are a helpful AI assistant."
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

    # Exit condition
    if user_input.lower() in ["exit", "quit", "bye"]:
        print("\nStopping model...")
        break

    # Save user message to memory
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
        response = requests.post(
            OLLAMA_URL,
            json=payload
        )

        response.raise_for_status()

        data = response.json()

        assistant_message = data["message"]["content"]

        print(f"\nAssistant: {assistant_message}\n")

        # Save assistant response to memory
        messages.append({
            "role": "assistant",
            "content": assistant_message
        })

    except requests.exceptions.RequestException as e:
        print(f"\nError: {e}\n")