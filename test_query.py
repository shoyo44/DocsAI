import urllib.request
import json

BASE_URL = "http://localhost:8000/api/v1"
TENANT_ID = "test"
VERTICAL = "university"

query_payload = json.dumps({
    "query_text": "What is the title of this research paper?",
    "tenant_id": TENANT_ID,
    "vertical": VERTICAL,
}).encode()

req = urllib.request.Request(
    f"{BASE_URL}/query",
    data=query_payload,
    headers={"Content-Type": "application/json"}
)

try:
    resp = urllib.request.urlopen(req, timeout=60)
    qresult = json.loads(resp.read().decode())
    print("[OK] Query SUCCESS!")
    print("Answer:", qresult.get("answer", "N/A"))
    print("Confidence:", qresult.get("confidence", "N/A"))
    print("Chunks used:", len(qresult.get("chunks_used", [])))
except urllib.error.HTTPError as e:
    print(f"[FAIL] Query FAILED (HTTP {e.code}): {e.read().decode('utf-8', errors='replace')}")
except Exception as ex:
    print(f"[FAIL] Query ERROR: {ex}")
