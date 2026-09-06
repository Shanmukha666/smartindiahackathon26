"""Minimal post-deploy contract check. Set SMOKE_BASE_URL and optional SMOKE_BEARER_TOKEN."""
import os
import sys

import httpx

base_url = os.environ["SMOKE_BASE_URL"].rstrip("/")
headers = {"Authorization": f"Bearer {os.environ['SMOKE_BEARER_TOKEN']}"} if os.getenv("SMOKE_BEARER_TOKEN") else {}
checks = [
    ("GET", "/health", None, {200}),
    ("GET", "/ready", None, {200}),
    ("POST", "/classify/next", {"session_id": "smoke", "trail": [], "answer_index": None}, {200}),
    ("POST", "/retrieve", {"query": "Section 3(p)", "jurisdiction": "IN"}, {200, 503}),
    ("POST", "/ask", {"query": "Section 3(p)", "jurisdiction": "IN", "session_id": "smoke"}, {200, 503}),
    ("POST", "/escalate", {"session_id": "smoke", "question": "smoke", "reason": "deployment-smoke"}, {200, 401}),
]
with httpx.Client(timeout=20, follow_redirects=False) as client:
    for method, path, payload, expected in checks:
        response = client.request(method, f"{base_url}{path}", json=payload, headers=headers)
        if response.status_code not in expected:
            print(f"{path}: expected {sorted(expected)}, got {response.status_code}", file=sys.stderr)
            raise SystemExit(1)
        print(f"{path}: {response.status_code}")
