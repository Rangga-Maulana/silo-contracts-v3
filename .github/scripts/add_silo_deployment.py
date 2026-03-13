#!/usr/bin/env python3
"""
Add a new Silo deployment entry to _siloDeployments.json.
Expects JSON config on stdin: {"chainName": "...", "deploymentKey": "...", "address": "0x..."}
"""
import json
import sys
from pathlib import Path

DEPLOYMENTS_FILE = Path(__file__).resolve().parents[2] / "silo-core" / "deploy" / "silo" / "_siloDeployments.json"


def main() -> None:
    try:
        config = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    chain_name = config.get("chainName")
    deployment_key = config.get("deploymentKey")
    address = config.get("address")

    if not chain_name or not deployment_key or not address:
        print("Missing required fields: chainName, deploymentKey, address", file=sys.stderr)
        sys.exit(1)

    # Normalize address
    addr = address.strip()
    if not addr.startswith("0x"):
        addr = "0x" + addr

    if len(addr) != 42 or not all(c in "0123456789abcdefABCDEFx" for c in addr):
        print(f"Invalid address: {address}", file=sys.stderr)
        sys.exit(1)

    addr = addr  # Keep as-is for checksum; JSON will store as provided

    if not DEPLOYMENTS_FILE.exists():
        print(f"File not found: {DEPLOYMENTS_FILE}", file=sys.stderr)
        sys.exit(1)

    with open(DEPLOYMENTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if chain_name not in data:
        data[chain_name] = {}

    if deployment_key in data[chain_name]:
        existing = data[chain_name][deployment_key]
        if existing.lower() == addr.lower():
            print(f"Entry already exists: {deployment_key} = {addr}")
            return
        print(f"Overwriting existing entry: {deployment_key} ({existing} -> {addr})", file=sys.stderr)

    data[chain_name][deployment_key] = addr

    # Sort chain sections and entries within each chain (alphabetically)
    sorted_data = {}
    for chain in sorted(data.keys()):
        sorted_data[chain] = dict(sorted(data[chain].items()))

    with open(DEPLOYMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Added {deployment_key} = {addr} to {chain_name}")


if __name__ == "__main__":
    main()
