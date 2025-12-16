import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
# If user didn't update .env yet or renamed it back? The user logs implied they changed variable name in python but did they change .env?
# The user request said "api klíč je v .env".
# The user edit to server.py changed the variable to GOOGLE_API_KEY.
if not api_key:
    # Try the old name just in case
    api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("No API key found in .env")
    exit(1)

genai.configure(api_key=api_key)

print(f"Using API Key: {api_key[:5]}...")

print("Listing supported generation models:")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
except Exception as e:
    print(f"Error listing models: {e}")
