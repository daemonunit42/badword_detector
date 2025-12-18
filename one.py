import os, requests, sys, json
from dotenv import load_dotenv

# Load .env file
load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")

WARNINGS_FILE = "warnings.json"

def load_warnings():
    if not os.path.exists(WARNINGS_FILE):
        return {}
    with open(WARNINGS_FILE, "r") as f:
        return json.load(f)

def save_warnings(data):
    with open(WARNINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def moderate_message(message):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a moderation bot that detects abusive, hateful, sexual, or offensive language. "
                    "Reply strictly in JSON only: {\"bad\": true/false, \"reason\": \"...\"}"
                )
            },
            {"role": "user", "content": message}
        ]
    }

    response = requests.post(url, headers=headers, json=payload)
    data = response.json()

    try:
        content = data["choices"][0]["message"]["content"].strip()
        return json.loads(content)
    except Exception as e:
        return {"bad": False, "reason": f"Parsing error: {e}"}

# ======================
# MAIN CONVERSATION LOOP
# ======================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python one.py <username>")
        sys.exit(1)

    username = sys.argv[1]
    warnings = load_warnings()

    if username not in warnings:
        warnings[username] = 0

    print(f"\n🤖 Moderation bot started for user: {username}")
    print("Type 'exit' or 'quit' to stop\n")

    while True:
        msg = input(f"{username}: ")

        if msg.lower() in ["exit", "quit"]:
            print("👋 Conversation ended.")
            break

        result = moderate_message(msg)

        if result["bad"]:
            warnings[username] += 1

            if warnings[username] == 1:
                print(f"⚠️ Bot: Warning 1 — {result['reason']}")
            elif warnings[username] == 2:
                print(f"⚠️ Bot: Warning 2 — {result['reason']}")
            elif warnings[username] >= 3:
                print(f"⛔ Bot: You are BANNED! Reason: {result['reason']}")
                warnings[username] = 3
                break
        else:
            print("✅ Bot: Message is clean")

        save_warnings(warnings)
