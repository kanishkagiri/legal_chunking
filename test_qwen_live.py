import json
import requests

base_url = "http://127.0.0.1:8000"

# Check Health
health = requests.get(f"{base_url}/api/health").json()
print("HEALTH:", health["status"])
print("CONNECTED SLM:", health["slm_model"])

# Send inquiry to Qwen 2.5 3B
resp = requests.post(
    f"{base_url}/api/chat",
    json={
        "question": "What can the Central Authority do about a misleading advertisement?",
        "mode": "keyword",
        "top_k": 2,
    },
    timeout=180.0,
).json()

print("\n=== LIVE GENERATION FROM QWEN 2.5 3B ===")
print("Answer:", resp.get("answer"))
print("\nAudited Claims:")
for c in resp.get("claims", []):
    print(f"[{c.get('verification_status')}] {c.get('claim_id')}: {c.get('text')}")
    print(f"  Supporting Quote: \"{c.get('supporting_quote')}\"")
    print(f"  Evidence Strength: {c.get('evidence_strength_score')}/100 ({c.get('evidence_label')})")
    print(f"  Citation: {c.get('citation')}")
