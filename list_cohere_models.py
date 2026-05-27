import asyncio
import os
import cohere
from dotenv import load_dotenv

async def main():
    load_dotenv()
    api_key = os.getenv("COHERE_API_KEY")
    if not api_key:
        print("COHERE_API_KEY is not set in .env")
        return
        
    client = cohere.AsyncClient(api_key=api_key)
    print("Fetching available models from Cohere...")
    try:
        response = await client.models.list()
        print("\nAvailable Models:")
        for model in response.models:
            # Filter for models that support chat/generation
            if "chat" in model.endpoints or "generate" in model.endpoints:
                print(f"- {model.name} (Endpoints: {model.endpoints})")
    except Exception as e:
        print(f"Error fetching models: {e}")

if __name__ == "__main__":
    asyncio.run(main())
