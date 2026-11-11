import os
from dotenv import load_dotenv
from google import genai

# Load variables from .env
load_dotenv()

# Get Gemini API key
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ GEMINI_API_KEY was not found.")
    exit()

print("✅ API key loaded successfully.")
print("API key length:", len(api_key))

try:
    # Create Gemini client
    client = genai.Client(api_key=api_key)

    print("🔄 Connecting to Gemini...")

    # Test Gemini
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents="Hello Gemini! Please reply with: Gemini API connection successful."
    )

    print("\n✅ Gemini API connection successful!")
    print("\nGemini response:")
    print(response.text)

except Exception as e:
    print("\n❌ Gemini API test failed.")
    print("\nError:")
    print(type(e).__name__)
    print(e)