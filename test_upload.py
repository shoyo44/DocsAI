"""
Test script: Upload Research_Paper_1.pdf and then query it.
"""
import urllib.request
import json

PDF_PATH = r"d:\Projects\DocsAI\Research_Paper_1.pdf"
BASE_URL = "http://localhost:8000/api/v1"
TENANT_ID = "test"
VERTICAL = "university"

# ─── 1. Upload ────────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1: Uploading Research_Paper_1.pdf ...")
print("=" * 60)

url = f"{BASE_URL}/upload?tenant_id={TENANT_ID}&vertical={VERTICAL}&doc_name=Research_Paper_1&version=1.0"

with open(PDF_PATH, "rb") as f:
    data = f.read()

boundary = "----DocAIBoundary7865"
body = (
    f"--{boundary}\r\n".encode()
    + b'Content-Disposition: form-data; name="file"; filename="Research_Paper_1.pdf"\r\n'
    + b"Content-Type: application/pdf\r\n\r\n"
    + data
    + f"\r\n--{boundary}--\r\n".encode()
)

req = urllib.request.Request(url, data=body)
req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

try:
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read().decode())
    print("[OK] Upload SUCCESS!")
    print(json.dumps(result, indent=2))
    doc_id = result.get("doc_id")
except urllib.error.HTTPError as e:
    err = e.read().decode("utf-8", errors="replace")
    print(f"[FAIL] Upload FAILED (HTTP {e.code}): {err}")
    doc_id = None
except Exception as ex:
    print(f"[FAIL] Upload ERROR: {ex}")
    doc_id = None

# ─── 2. List Documents ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 2: Listing documents for tenant ...")
print("=" * 60)
try:
    resp2 = urllib.request.urlopen(f"{BASE_URL}/documents?tenant_id={TENANT_ID}", timeout=10)
    docs = json.loads(resp2.read().decode())
    print(json.dumps(docs, indent=2))
except Exception as ex:
    print(f"[FAIL] List docs ERROR: {ex}")

# ─── 3. Query ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 3: Querying the uploaded document ...")
print("=" * 60)
query_payload = json.dumps({
    "query_text": "What is the main contribution of this research paper?",
    "tenant_id": TENANT_ID,
    "vertical": VERTICAL,
}).encode()

req3 = urllib.request.Request(
    f"{BASE_URL}/query",
    data=query_payload,
    headers={"Content-Type": "application/json"}
)
try:
    resp3 = urllib.request.urlopen(req3, timeout=60)
    qresult = json.loads(resp3.read().decode())
    print("[OK] Query SUCCESS!")
    print("Answer:", qresult.get("answer", "N/A"))
    print("Confidence:", qresult.get("confidence", "N/A"))
    print("Chunks used:", len(qresult.get("chunks_used", [])))
except urllib.error.HTTPError as e:
    print(f"[FAIL] Query FAILED (HTTP {e.code}): {e.read().decode('utf-8', errors='replace')}")
except Exception as ex:
    print(f"[FAIL] Query ERROR: {ex}")

print("\n" + "=" * 60)
print("DONE.")
print("=" * 60)
