import requests
import json
import os

BASE_URL = "http://127.0.0.1:8000/api/v1"
USERNAME = "admin"
PASSWORD = "admin123"

def main():
    print("=== OmniForge RAG Engine Client Demo ===")
    
    # ---------------------------------------------------------
    # 1. Authenticate & Get Token
    # ---------------------------------------------------------
    print("\n1. Authenticating...")
    auth_response = requests.post(
        f"{BASE_URL}/auth/token",
        json={"username": USERNAME, "password": PASSWORD}
    )
    if not auth_response.ok:
        print(f"Auth failed: {auth_response.text}")
        return
        
    token = auth_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✓ Successfully authenticated (Token acquired)")

    # ---------------------------------------------------------
    # 2. Create a Conversation Session
    # ---------------------------------------------------------
    print("\n2. Creating conversation session...")
    session_response = requests.post(f"{BASE_URL}/session", headers=headers)
    session_response.raise_for_status()
    session_id = session_response.json()["session_id"]
    print(f"✓ Session created: {session_id}")

    # ---------------------------------------------------------
    # 3. Ingest a Document
    # ---------------------------------------------------------
    print("\n3. Ingesting a sample document...")
    # Create some dummy content representing a document
    sample_text = (
        "The OmniForge Ultra RAG system uses FastEmbed with the BAAI/bge-small-en-v1.5 "
        "model to generate 384-dimensional dense embeddings locally. "
        "For generation and query rewriting, it relies on Cohere's command-a-03-2025 model. "
        "Sessions are managed in memory with a TTL of 3600 seconds."
    ).encode('utf-8')
    
    # Multipart form data structure for requests
    files = {
        "file": ("architecture_doc.txt", sample_text, "text/plain")
    }
    data = {
        "department": "engineering"
    }
    
    ingest_response = requests.post(f"{BASE_URL}/ingest", headers=headers, files=files, data=data)
    ingest_response.raise_for_status()
    print(f"✓ Document ingested: {ingest_response.json()['chunks_ingested']} chunks generated.")

    # ---------------------------------------------------------
    # 4. Perform Initial RAG Query
    # ---------------------------------------------------------
    print("\n4. Performing Initial RAG Query...")
    query_payload = {
        "query": "What embedding model is used and what is its dimension size?",
        "session_id": session_id,
        "filters": {"department": "engineering"}
    }
    
    query_response = requests.post(f"{BASE_URL}/query", headers=headers, json=query_payload)
    if not query_response.ok:
        print(f"Query failed with 500. Server says: {query_response.text}")
    query_response.raise_for_status()
    query_data = query_response.json()
    
    print(f"\n[USER]: {query_payload['query']}")
    print(f"[ASSISTANT]: {query_data['answer']}")
    print(f"[METRICS]: Latency: {query_data['latency_ms']}ms | Sources used: {len(query_data['source_documents'])}")

    # ---------------------------------------------------------
    # 5. Perform Follow-up Query (Tests Memory/History)
    # ---------------------------------------------------------
    print("\n5. Performing Follow-up Query (Testing Session Memory)...")
    follow_up_payload = {
        "query": "And what model does it use for generation?",
        "session_id": session_id,
        "filters": {"department": "engineering"}
    }
    
    query_response_2 = requests.post(f"{BASE_URL}/query", headers=headers, json=follow_up_payload)
    query_response_2.raise_for_status()
    query_data_2 = query_response_2.json()
    
    print(f"\n[USER]: {follow_up_payload['query']}")
    print(f"[ASSISTANT]: {query_data_2['answer']}")
    print(f"[METRICS]: Session turns: {query_data_2['usage']['session_turns']}")

    # ---------------------------------------------------------
    # 6. Clear Session History
    # ---------------------------------------------------------
    print("\n6. Clearing session history...")
    delete_response = requests.delete(f"{BASE_URL}/session/{session_id}", headers=headers)
    delete_response.raise_for_status()
    print("✓ Session cleared successfully.")

if __name__ == "__main__":
    # Ensure requests is installed
    try:
        import requests
    except ImportError:
        print("The 'requests' library is required. Please run: pip install requests")
        exit(1)
        
    main()
