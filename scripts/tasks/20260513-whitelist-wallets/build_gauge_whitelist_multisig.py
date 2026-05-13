#!/usr/bin/env python3
"""
Build Safe Transaction Builder bundles that grant ALLOWED_ROLE on hooks.

Source hooks:
- scripts/tasks/set-permissioned-liquidation/permissioned_liquidation_deploy_gauges_by_chain.json

Owner split:
- per chain + per owner (owner derived from hookOwner map in v3_markets_by_chain.json)

Role recipients (same for every chain):
- 0x1fF60e85852Ac73cd05B69A8B6641fc24A3FC011
- 0xC04f84A02cC65f14f4e8C982a7a467EE88c5311e
- 0xd3EC1026c9F911e201De4d52A667dC10bc3754d7

python3 scripts/tasks/20260513-whitelist-wallets/build_gauge_whitelist_multisig.py
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_DEPLOY_JSON = (
    REPO_ROOT / "scripts" / "tasks" / "set-permissioned-liquidation" / "permissioned_liquidation_deploy_gauges_by_chain.json"
)
DEFAULT_MARKETS_JSON = REPO_ROOT / "scripts" / "tasks" / "set-permissioned-liquidation" / "v3_markets_by_chain.json"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "out"
MIN_SILO_ID_FOR_HOOK_WHITELIST = 3000

ALLOWED_ROLE = "0xd5dc6b389d0dd5687ab5bd9338f760ebeaff2d2852a93a9a9ebaebbfefc763ac"
TARGET_ACCOUNTS = [
    "0x1fF60e85852Ac73cd05B69A8B6641fc24A3FC011",
    "0xC04f84A02cC65f14f4e8C982a7a467EE88c5311e",
    "0xd3EC1026c9F911e201De4d52A667dC10bc3754d7",
]

CHAIN_IDS: dict[str, int] = {
    "mainnet": 1,
    "optimism": 10,
    "bnb": 56,
    "xdc": 50,
    "arbitrum_one": 42161,
    "avalanche": 43114,
    "sonic": 146,
    "okx": 196,
    "base": 8453,
    "ink": 57073,
    "injective": 1776,
    "megaeth": 4326,
    "mantle": 5000,
}

GRANT_ROLE_ABI: dict[str, Any] = {
    "inputs": [
        {"internalType": "bytes32", "name": "role", "type": "bytes32"},
        {"internalType": "address", "name": "account", "type": "address"},
    ],
    "name": "grantRole",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build multisig bundles for hook whitelist grants.")
    parser.add_argument(
        "--deploy-json",
        type=Path,
        default=DEFAULT_DEPLOY_JSON,
        help=f"Input permissioned deployment JSON (default: {DEFAULT_DEPLOY_JSON})",
    )
    parser.add_argument(
        "--markets-json",
        type=Path,
        default=DEFAULT_MARKETS_JSON,
        help=f"Input markets JSON (hook -> hookOwner mapping) (default: {DEFAULT_MARKETS_JSON})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for generated bundles (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--chain",
        action="append",
        default=[],
        help="Optional chain filter (can be repeated).",
    )
    parser.add_argument(
        "--min-silo-id",
        type=int,
        default=MIN_SILO_ID_FOR_HOOK_WHITELIST,
        help=f"Include only records with id >= this value (default: {MIN_SILO_ID_FOR_HOOK_WHITELIST}).",
    )
    return parser.parse_args()


def is_address(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v.startswith("0x") or len(v) != 42:
        return False
    try:
        int(v[2:], 16)
    except ValueError:
        return False
    return True


def normalize_address(value: str) -> str:
    if not is_address(value):
        raise ValueError(f"Invalid address: {value!r}")
    return value.strip().lower()


def short(addr: str) -> str:
    return f"{addr[:6]}{addr[-4:]}"


def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_markets_hook_owners(path: Path) -> dict[str, dict[str, str]]:
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError("markets JSON root must be object")
    out: dict[str, dict[str, str]] = {}
    for chain, markets in data.items():
        if not isinstance(chain, str) or not isinstance(markets, list):
            continue
        chain_map: dict[str, str] = {}
        for market in markets:
            if not isinstance(market, dict):
                continue
            hook = market.get("hook")
            owner = market.get("hookOwner")
            if isinstance(hook, str) and isinstance(owner, str) and is_address(hook) and is_address(owner):
                chain_map[normalize_address(hook)] = normalize_address(owner)
        out[chain] = chain_map
    return out


def load_deploy_records(path: Path) -> dict[str, list[dict[str, Any]]]:
    raw = load_json(path)
    if not isinstance(raw, dict):
        raise ValueError("deploy JSON root must be object")
    source = raw.get("byChain") if isinstance(raw.get("byChain"), dict) else raw
    out: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(source, dict):
        return out
    for chain, records in source.items():
        if isinstance(chain, str) and isinstance(records, list):
            out[chain] = [r for r in records if isinstance(r, dict)]
    return out


def build_grant_role_tx(target_hook: str, account: str) -> dict[str, Any]:
    return {
        "to": target_hook,
        "value": "0",
        "data": None,
        "contractMethod": GRANT_ROLE_ABI,
        "contractInputsValues": {
            "role": ALLOWED_ROLE,
            "account": account,
        },
    }


def build_batch(
    *,
    chain: str,
    chain_id: int,
    owner: str,
    hooks: list[str],
    accounts: list[str],
    transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    description = "\n".join(
        [
            f"Hook whitelist grants on {chain}",
            f"Hook owner (Safe): {owner}",
            f"Hooks: {len(hooks)}",
            f"Accounts per hook: {len(accounts)}",
            f"Transactions: {len(transactions)}",
            "",
            "Accounts:",
            *[f"- {a}" for a in accounts],
        ]
    )
    return {
        "version": "1.0",
        "chainId": str(chain_id),
        "createdAt": int(time.time() * 1000),
        "meta": {
            "name": f"Hook White List - {chain}",
            "description": description,
            "txBuilderVersion": "1.17.0",
            "createdFromSafeAddress": owner,
            "createdFromOwnerAddress": "",
            "checksum": "",
        },
        "transactions": transactions,
    }


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for old_file in args.output_dir.glob("Hook White List - *.json"):
        old_file.unlink()

    target_accounts = [normalize_address(a) for a in TARGET_ACCOUNTS]
    hook_owner_by_chain = load_markets_hook_owners(args.markets_json)
    deploy_records_by_chain = load_deploy_records(args.deploy_json)

    chain_filter = {c.strip().lower() for c in args.chain if c.strip()} if args.chain else set()
    validation_errors: list[str] = []
    generated = 0

    for chain, records in sorted(deploy_records_by_chain.items(), key=lambda x: x[0]):
        if chain_filter and chain.lower() not in chain_filter:
            continue

        chain_id = CHAIN_IDS.get(chain)
        if chain_id is None:
            validation_errors.append(f"{chain}: unknown chain id")
            continue

        hook_owner_map = hook_owner_by_chain.get(chain, {})
        if not hook_owner_map:
            validation_errors.append(f"{chain}: missing hookOwner mapping in markets JSON")
            continue

        hooks_by_owner: dict[str, set[str]] = {}
        for rec in records:
            entries = rec.get("entries")
            market_id = rec.get("id")
            if not isinstance(market_id, int) or market_id < args.min_silo_id:
                continue
            if not isinstance(entries, list):
                validation_errors.append(f"{chain} id={market_id}: missing entries")
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    validation_errors.append(f"{chain} id={market_id}: invalid entry")
                    continue
                hook = entry.get("hook")
                gauge = entry.get("gauge")
                if not isinstance(hook, str) or not is_address(hook):
                    validation_errors.append(f"{chain} id={market_id}: invalid hook")
                    continue
                if not isinstance(gauge, str) or not is_address(gauge):
                    validation_errors.append(f"{chain} id={market_id}: invalid gauge")
                    continue
                hook_n = normalize_address(hook)
                owner = hook_owner_map.get(hook_n)
                if not owner:
                    validation_errors.append(f"{chain} id={market_id}: missing hookOwner for hook {hook_n}")
                    continue
                hooks_by_owner.setdefault(owner, set()).add(hook_n)

        if not hooks_by_owner:
            validation_errors.append(f"{chain}: no valid hooks")
            continue

        for owner, hooks_set in sorted(hooks_by_owner.items(), key=lambda x: x[0]):
            hooks = sorted(hooks_set, key=str.lower)
            txs: list[dict[str, Any]] = []
            for hook in hooks:
                for account in target_accounts:
                    txs.append(build_grant_role_tx(hook, account))

            batch = build_batch(
                chain=chain,
                chain_id=chain_id,
                owner=owner,
                hooks=hooks,
                accounts=target_accounts,
                transactions=txs,
            )

            if len(hooks_by_owner) == 1:
                filename = f"Hook White List - {chain}.json"
            else:
                filename = f"Hook White List - {chain} - {short(owner)}.json"
            out_path = args.output_dir / filename
            out_path.write_text(json.dumps(batch, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            print(
                f"[ok] {chain} owner={owner} hooks={len(hooks)} accounts={len(target_accounts)} "
                f"tx={len(txs)} -> {out_path.name}"
            )
            generated += 1

    if validation_errors:
        print("[FAIL] Validation errors:")
        for err in validation_errors:
            print(f"  - {err}")
        print(f"Generated files before failure: {generated}")
        return 1

    print(f"Generated files: {generated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
