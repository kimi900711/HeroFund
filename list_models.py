import os
from google import genai

api_key = os.environ.get("GEMINI_API_KEY", "")
if api_key:
    client = genai.Client(api_key=api_key)
    for m in client.models.list():
        if "pro" in m.name.lower() or "flash" in m.name.lower():
            print(m.name)
else:
    print("No GEMINI_API_KEY")
