import urllib.request
import json
import time

BASE_URL = "http://localhost:8000/api/v1"
TENANT_ID = "tenant-123"

def run_test_query(query_text: str):
    print(f"\n[TESTING] Query: '{query_text}'")
    payload = json.dumps({
        "query_text": query_text,
        "tenant_id": TENANT_ID,
        "vertical": "auto"
    }).encode()
    
    req = urllib.request.Request(
        f"{BASE_URL}/query",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    
    try:
        t0 = time.time()
        resp = urllib.request.urlopen(req, timeout=30)
        duration = time.time() - t0
        qresult = json.loads(resp.read().decode())
        print(f"[OK] Response received in {duration:.2f}s!")
        print("Answer Summary:", qresult.get("answer", "")[:120] + "...")
        print("Confidence:", qresult.get("confidence", "N/A"))
        print("Chunks Used count:", len(qresult.get("chunks_used", [])))
    except urllib.error.HTTPError as e:
        print(f"[FAIL] HTTP Error {e.code}: {e.read().decode('utf-8', errors='replace')}")
    except Exception as ex:
        print(f"[FAIL] Exception: {ex}")

if __name__ == "__main__":
    # Test 1: Academic / Research topic
    run_test_query("What is the title of the research paper about urban mobility and traffic congestion?")
    
    # Test 2: Legal contract topic
    run_test_query("What are the confidentiality and intellectual property clauses in the NDA contract?")
