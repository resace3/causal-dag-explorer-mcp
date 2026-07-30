"""Discover Home Assistant entities and suggest a `config.yaml` mapping.

Reads HOME_ASSISTANT_URL / HOME_ASSISTANT_TOKEN from the environment (or from
`.env`) and prints a grouped inventory of entities the timeline can use.
Credentials are never printed.

    python scripts/discover_home_assistant.py            # inventory
    python scripts/discover_home_assistant.py --yaml     # ready-to-paste config
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "server"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=False)

# device_class -> the timeline's entity group.
DEVICE_CLASS_GROUPS = {
    "illuminance": "illuminance",
    "temperature": "temperature",
    "humidity": "humidity",
    "motion": "motion",
    "occupancy": "motion",
    "presence": "presence",
}

MAX_PER_GROUP = 6


def classify(entity_id: str, attributes: dict) -> str | None:
    domain = entity_id.split(".", 1)[0]
    device_class = str(attributes.get("device_class") or "").lower()
    name = f"{entity_id} {attributes.get('friendly_name', '')}".lower()

    if domain == "person" or domain == "device_tracker":
        return "presence"
    if domain == "binary_sensor":
        if device_class in ("motion", "occupancy", "moving"):
            return "motion"
        if device_class == "presence":
            return "presence"
        if "bed" in name and ("occup" in name or "sleep" in name):
            return "sleep"
        return None
    if domain == "sensor":
        if device_class in DEVICE_CLASS_GROUPS:
            return DEVICE_CLASS_GROUPS[device_class]
        if "illuminance" in name or "lux" in name or "light_level" in name:
            return "illuminance"
        return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yaml", action="store_true", help="print a config.yaml fragment")
    parser.add_argument("--all", action="store_true", help="list every matching entity")
    args = parser.parse_args()

    url = os.environ.get("HOME_ASSISTANT_URL")
    token = os.environ.get("HOME_ASSISTANT_TOKEN")
    if not url or not token:
        print(
            "Set HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN (in .env or the "
            "environment) before running this script.",
            file=sys.stderr,
        )
        return 2

    try:
        response = httpx.get(
            f"{url.rstrip('/')}/api/states",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        print(f"Could not reach Home Assistant: {exc}", file=sys.stderr)
        return 1

    if response.status_code in (401, 403):
        print("Home Assistant rejected the token (HTTP %s)." % response.status_code, file=sys.stderr)
        return 1
    response.raise_for_status()

    states = response.json()
    groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for state in states:
        entity_id = state.get("entity_id", "")
        attributes = state.get("attributes") or {}
        group = classify(entity_id, attributes)
        if group is None:
            continue
        groups[group].append(
            (
                entity_id,
                str(attributes.get("friendly_name") or ""),
                f"{state.get('state')} {attributes.get('unit_of_measurement') or ''}".strip(),
            )
        )

    print(f"Home Assistant reported {len(states)} entities in total.\n")
    for group in ("presence", "motion", "temperature", "illuminance", "humidity", "sleep"):
        rows = sorted(groups.get(group, []))
        print(f"{group}: {len(rows)} entities")
        shown = rows if args.all else rows[:MAX_PER_GROUP]
        for entity_id, friendly, value in shown:
            print(f"    {entity_id:<52} {friendly:<34} = {value}")
        if len(rows) > len(shown):
            print(f"    … and {len(rows) - len(shown)} more (use --all)")
        print()

    if args.yaml:
        print("# ---- paste into config.yaml under home_assistant: ----")
        print("  entities:")
        for group in ("presence", "motion", "temperature", "illuminance", "humidity", "sleep"):
            rows = sorted(groups.get(group, []))[:MAX_PER_GROUP]
            print(f"    {group}:")
            if not rows:
                print("      []")
                continue
            for entity_id, _friendly, _value in rows:
                print(f"      - {entity_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
