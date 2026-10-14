import json
import requests

base_url = "http://127.0.0.1:8000"

# 1. Health check
h = requests.get(f"{base_url}/api/health").json()
print("HEALTH STATUS:", h["status"], "Model:", h["slm_model"]["provider"])

# 2. Misleading ads inquiry (Graph mode)
res1 = requests.post(f"{base_url}/api/chat", json={
    "question": "What can the Central Authority do about a misleading advertisement?",
    "mode": "graph",
    "top_k": 3,
}).json()
print("\n=== 1. GRAPH MODE (Misleading Ads) ===")
print("Answer:", res1.get("answer", "")[:140] + "...")
print("Audited Claims:", len(res1.get("claims", [])))
for c in res1.get("claims", [])[:2]:
    print(f"  [{c['verification_status']}] {c['claim_id']}: {c['text'][:70]}... (Strength: {c['evidence_strength_score']}/100 - {c['evidence_label']})")
    print(f"    Citation: {c['citation']} | Quote: \"{c['supporting_quote'][:50]}...\"")

# 3. Defect testing inquiry (Vector mode)
res2 = requests.post(f"{base_url}/api/chat", json={
    "question": "What procedure applies when testing goods for a defect?",
    "mode": "vector",
    "top_k": 3,
}).json()
print("\n=== 2. VECTOR MODE (Defect Testing) ===")
print("Answer:", res2.get("answer", "")[:140] + "...")
print("Audited Claims:", len(res2.get("claims", [])))
for c in res2.get("claims", [])[:2]:
    print(f"  [{c['verification_status']}] {c['claim_id']}: {c['text'][:70]}... (Strength: {c['evidence_strength_score']}/100 - {c['evidence_label']})")

# 4. Appeals route inquiry (Keyword mode)
res3 = requests.post(f"{base_url}/api/chat", json={
    "question": "Where can a consumer appeal a District Commission order under Section 41?",
    "mode": "keyword",
    "top_k": 3,
}).json()
print("\n=== 3. KEYWORD MODE (Section 41 Appeals) ===")
print("Answer:", res3.get("answer", "")[:140] + "...")
print("Audited Claims:", len(res3.get("claims", [])))
for c in res3.get("claims", [])[:2]:
    print(f"  [{c['verification_status']}] {c['claim_id']}: {c['text'][:70]}... (Strength: {c['evidence_strength_score']}/100 - {c['evidence_label']})")

# 5. Abstention query (Unanswerable topic)
res4 = requests.post(f"{base_url}/api/chat", json={
    "question": "What is the speed limit on Interstate 95 in the United States?",
    "mode": "keyword",
    "top_k": 3,
}).json()
print("\n=== 4. STATUTORY ABSTENTION TEST ===")
print("Insufficient evidence:", res4.get("insufficient_evidence"))
print("Answer:", res4.get("answer"))
print("Claims count:", len(res4.get("claims", [])))
