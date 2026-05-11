"""Quick test for memory JSON-RPC handlers."""
import json
import subprocess
import sys

reqs = [
    {"id": "a1", "method": "memory.add", "params": {"content": "Always use Result type", "type": "constraint", "priority": "project"}},
    {"id": "s1", "method": "memory.search", "params": {"query": "Result", "top_k": 3}},
    {"id": "c1", "method": "memory.constraints", "params": {}},
]
input_text = "\n".join(json.dumps(r, ensure_ascii=False) for r in reqs) + "\n"

proc = subprocess.run(
    [sys.executable, "-m", "evocli_soul.main"],
    input=input_text,
    capture_output=True, text=True, timeout=10, encoding="utf-8",
)
print("=== Results ===")
for line in proc.stdout.strip().splitlines():
    try:
        msg = json.loads(line)
        if msg.get("id"):
            print(f"  {msg['id']}: {json.dumps(msg.get('result'), ensure_ascii=False, indent=2)}")
    except json.JSONDecodeError:
        pass

# Check all passed
ids_seen = set()
for line in proc.stdout.strip().splitlines():
    try:
        msg = json.loads(line)
        if msg.get("id") and msg.get("result") is not None:
            ids_seen.add(msg["id"])
    except json.JSONDecodeError:
        pass

expected = {"a1", "s1", "c1"}
if ids_seen >= expected:
    print("\nALL MEMORY RPC TESTS PASSED")
else:
    print(f"\nFAILED: missing responses for {expected - ids_seen}")
    sys.exit(1)
