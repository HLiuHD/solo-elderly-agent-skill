#!/usr/bin/env python3
"""pre_llm script: inject mock latest_health if payload is missing it."""

from __future__ import annotations
import json, sys, random

def main():
    raw = json.loads(sys.stdin.read())
    payload = raw.get("payload", {})
    latest = payload.get("latest_health")
    if not isinstance(latest, dict) or not any(v for v in latest.values() if v):
        payload["latest_health"] = {
            "blood_pressure": f"{random.randint(118, 135)}/{random.randint(75, 88)}",
            "heart_rate": str(random.randint(68, 82)),
            "blood_oxygen": f"{random.randint(96, 99)}",
            "blood_glucose": f"{round(random.uniform(4.8, 6.2), 1)}",
            "steps_today": f"{random.randint(3500, 9500):,}",
        }
    raw["payload"] = payload
    print(json.dumps(raw, ensure_ascii=False))

if __name__ == "__main__":
    main()
