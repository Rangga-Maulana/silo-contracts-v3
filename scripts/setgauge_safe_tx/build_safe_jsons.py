#!/usr/bin/env python3
"""
Build Safe (Transaction Builder) JSON batches for `setGauge` calls.

Inputs:
- ./setgauge_data.json: parsed data from PR #1902 comments (Mainnet + Avalanche).
- RPC URLs from environment: RPC_MAINNET, RPC_AVALANCHE.

What the script does:
1. For every chain reads its calls list.
2. Calls `owner()` on every distinct hook over RPC.
3. Groups calls by (chainId, hook owner) -> each group becomes one Safe batch JSON
   that the hook owner multisig can import in Safe Transaction Builder.

Output JSON layout matches the Transaction Builder schema. Each transaction includes
a partial ABI (`contractMethod` + `contractInputsValues`) so the Safe UI shows the
human-readable function name (`setGauge`) and named arguments (`_gauge`, `_shareToken`)
instead of opaque calldata.

Output files are written to ./out/ as:
  setGauge_<ChainName>_<OwnerShort>.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_FILE = SCRIPT_DIR / "setgauge_data.json"
OUT_DIR = SCRIPT_DIR / "out"

OWNER_SELECTOR = "0x8da5cb5b"               # bytes4(keccak256("owner()"))
CONFIGURED_GAUGES_SELECTOR = "0xa37d9411"   # bytes4(keccak256("configuredGauges(address)"))

SET_GAUGE_ABI: dict[str, Any] = {
    "inputs": [
        {"internalType": "contract ISiloIncentivesController", "name": "_gauge", "type": "address"},
        {"internalType": "contract IShareToken", "name": "_shareToken", "type": "address"},
    ],
    "name": "setGauge",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function",
}

REMOVE_GAUGE_ABI: dict[str, Any] = {
    "inputs": [
        {"internalType": "contract IShareToken", "name": "_shareToken", "type": "address"},
    ],
    "name": "removeGauge",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function",
}


def rpc_request(rpc_url: str, method: str, params: list[Any], *, timeout: int = 30) -> dict[str, Any]:
    """Minimal stdlib JSON-RPC client. Raises RuntimeError on failure."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    req = Request(
        rpc_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        raise RuntimeError(f"http_error status={e.code} reason={e.reason}") from e
    except URLError as e:
        raise RuntimeError(f"url_error reason={e.reason}") from e

    if "error" in body and body["error"] is not None:
        raise RuntimeError(f"rpc_error {body['error']}")
    return body


def _decode_address_word(raw_hex: str, *, what: str, ctx: str) -> str:
    if not raw_hex or raw_hex == "0x":
        raise RuntimeError(f"empty {what} return for {ctx}")
    word = raw_hex[2:].rjust(64, "0")
    if len(word) != 64:
        raise RuntimeError(f"unexpected {what} return for {ctx}: {raw_hex}")
    return ("0x" + word[-40:]).lower()


def eth_call_owner(rpc_url: str, contract: str) -> str:
    """Call `owner()` on the given contract and return the address (lowercased)."""
    body = rpc_request(rpc_url, "eth_call", [{"to": contract, "data": OWNER_SELECTOR}, "latest"])
    return _decode_address_word(body["result"], what="owner()", ctx=contract)


def eth_call_configured_gauge(rpc_url: str, hook: str, share_token: str) -> str:
    """Call `configuredGauges(_shareToken)` on the hook. Returns lowercased address (0x000…0 if unset)."""
    addr_no0x = share_token.lower().removeprefix("0x").rjust(40, "0")
    data = CONFIGURED_GAUGES_SELECTOR + addr_no0x.rjust(64, "0")
    body = rpc_request(rpc_url, "eth_call", [{"to": hook, "data": data}, "latest"])
    return _decode_address_word(body["result"], what="configuredGauges()", ctx=f"{hook}/{share_token}")


def is_zero_address(addr: str) -> bool:
    return int(addr, 16) == 0


def short(addr: str) -> str:
    return addr[:6] + addr[-4:]


def build_set_gauge_tx(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "to": call["hook"],
        "value": "0",
        "data": None,
        "contractMethod": SET_GAUGE_ABI,
        "contractInputsValues": {
            "_gauge": call["gauge"],
            "_shareToken": call["shareToken"],
        },
    }


def build_remove_gauge_tx(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "to": call["hook"],
        "value": "0",
        "data": None,
        "contractMethod": REMOVE_GAUGE_ABI,
        "contractInputsValues": {
            "_shareToken": call["shareToken"],
        },
    }


def build_batch(
    *,
    chain_name: str,
    chain_id: int,
    owner: str,
    transactions: list[dict[str, Any]],
    description_lines: list[str],
) -> dict[str, Any]:
    return {
        "version": "1.0",
        "chainId": str(chain_id),
        "createdAt": int(time.time() * 1000),
        "meta": {
            "name": f"setGauge batch on {chain_name}",
            "description": "\n".join(description_lines),
            "txBuilderVersion": "1.17.0",
            "createdFromSafeAddress": owner,
            "createdFromOwnerAddress": "",
            "checksum": "",
        },
        "transactions": transactions,
    }


def main() -> int:
    if not DATA_FILE.exists():
        print(f"ERROR: {DATA_FILE} not found", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(exist_ok=True)

    data = json.loads(DATA_FILE.read_text())

    summary: list[str] = []
    summary.append("Safe Transaction Builder batches for `setGauge` (PR #1902)")
    summary.append("")

    for chain in data["chains"]:
        chain_name: str = chain["name"]
        chain_id: int = chain["chainId"]
        rpc_env: str = chain["rpcEnv"]
        rpc_url = os.environ.get(rpc_env)
        if not rpc_url:
            print(f"ERROR: env var {rpc_env} is not set", file=sys.stderr)
            return 1

        print(f"\n=== {chain_name} (chainId={chain_id}) ===")
        print(f"RPC: {rpc_url}")

        calls: list[dict[str, Any]] = chain["calls"]
        unique_hooks = sorted({c["hook"] for c in calls}, key=str.lower)

        hook_owner: dict[str, str] = {}
        for hook in unique_hooks:
            try:
                owner = eth_call_owner(rpc_url, hook)
            except Exception as e:
                print(f"ERROR: failed to read owner() of {hook} via {rpc_env}: {e}", file=sys.stderr)
                return 2
            hook_owner[hook] = owner
            print(f"  hook {hook} -> owner {owner}")

        # Check existing gauge for each (hook, shareToken) pair so we can prepend removeGauge() if needed.
        # NOTE: we look at on-chain state at "latest". If multiple share tokens in this batch already have
        # gauges, every one of them gets a removeGauge() inserted right before its setGauge().
        for c in calls:
            try:
                existing = eth_call_configured_gauge(rpc_url, c["hook"], c["shareToken"])
            except Exception as e:
                print(
                    f"ERROR: failed to read configuredGauges({c['shareToken']}) on {c['hook']} via {rpc_env}: {e}",
                    file=sys.stderr,
                )
                return 2
            c["_existingGauge"] = existing
            if not is_zero_address(existing):
                print(
                    f"  EXISTING gauge on hook {c['hook']} for shareToken {c['shareToken']}: {existing} "
                    f"(silo {c['siloId']}) -> will prepend removeGauge()"
                )

        owners_set = sorted(set(hook_owner.values()))
        print(f"Distinct hook owners on {chain_name}: {len(owners_set)}")
        for o in owners_set:
            hooks_for_owner = [h for h, ow in hook_owner.items() if ow == o]
            print(f"  owner {o} controls {len(hooks_for_owner)} hook(s): {hooks_for_owner}")

        for owner in owners_set:
            owner_calls = [c for c in calls if hook_owner[c["hook"]] == owner]
            transactions: list[dict[str, Any]] = []
            remove_count = 0
            for c in owner_calls:
                if not is_zero_address(c["_existingGauge"]):
                    transactions.append(build_remove_gauge_tx(c))
                    remove_count += 1
                transactions.append(build_set_gauge_tx(c))

            description_lines = [
                f"Source: PR https://github.com/silo-finance/silo-contracts-v3/pull/1902",
                f"Chain: {chain_name} (id {chain_id})",
                f"Hook owner (Safe): {owner}",
                f"Total tx: {len(transactions)} ({remove_count} removeGauge + {len(owner_calls)} setGauge)",
                "",
                "Calls:",
            ]
            for c in owner_calls:
                if not is_zero_address(c["_existingGauge"]):
                    description_lines.append(
                        f"- silo {c['siloId']} | hook {c['hook']} | "
                        f"removeGauge({c['shareToken']})  [existing gauge: {c['_existingGauge']}]"
                    )
                description_lines.append(
                    f"- silo {c['siloId']} | hook {c['hook']} | "
                    f"setGauge({c['gauge']}, {c['shareToken']}) [{c['shareTokenKind']}]"
                )

            batch = build_batch(
                chain_name=chain_name,
                chain_id=chain_id,
                owner=owner,
                transactions=transactions,
                description_lines=description_lines,
            )

            owner_short = short(owner)
            out_file = OUT_DIR / f"setGauge_{chain_name}_{owner_short}.json"
            out_file.write_text(json.dumps(batch, indent=2) + "\n")
            print(
                f"  -> wrote {out_file.relative_to(SCRIPT_DIR)} "
                f"({len(transactions)} tx, of which {remove_count} removeGauge)"
            )

            summary.append(
                f"- {chain_name} | owner {owner} | {len(transactions)} tx "
                f"({remove_count} removeGauge + {len(owner_calls)} setGauge) | file: {out_file.name}"
            )

    print("\n" + "\n".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
