#!/usr/bin/env python3
"""
CI script: check that every deployed contract (core, oracle, vaults) that uses
OpenZeppelin Access Control has the DEFAULT_ADMIN_ROLE holder equal to DAO from
common/addresses for that chain.

Uses deployment ABI to decide: only contracts whose ABI has getRoleMemberCount(bytes32)
and getRoleMember(bytes32,uint256) are checked. Then eth_call getRoleMemberCount(DEFAULT_ADMIN_ROLE)
and getRoleMember(DEFAULT_ADMIN_ROLE, 0). If admin != DAO -> FAIL.

Output and behaviour mirror check_deployments_owner_is_dao.py: one line per
contract ([ ok ] / [skip] / [FAIL]), no summary, exit 1 if any FAIL.

Usage:

  python3 scripts/check_deployments_admin_is_dao.py --chain arbitrum_one
  python3 scripts/check_deployments_admin_is_dao.py --chain mainnet --components core,oracle
  python3 scripts/check_deployments_admin_is_dao.py --chain arbitrum_one --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# OpenZeppelin AccessControl: DEFAULT_ADMIN_ROLE = bytes32(0)
DEFAULT_ADMIN_ROLE_HEX = "0" * 64

# getRoleMemberCount(bytes32) selector
GET_ROLE_MEMBER_COUNT_SELECTOR = "0xca15c873"
# getRoleMember(bytes32,uint256) selector
GET_ROLE_MEMBER_SELECTOR = "0x9010d07c"
# EIP-1967 slots
EIP1967_IMPLEMENTATION_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_ADMIN_SLOT = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
EIP1967_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"

COMPONENT_PATHS = {
    "core": "silo-core/deployments",
    "oracle": "silo-oracles/deployments",
    "vaults": "silo-vaults/deployments",
}

CONTRACTS_EXCLUDED: set[str] = {"Tower"}

CHAIN_TO_RPC_ENV: dict[str, str] = {
    "arbitrum_one": "RPC_ARBITRUM",
    "avalanche": "RPC_AVALANCHE",
    "base": "RPC_BASE",
    "bnb": "RPC_BNB",
    "injective": "RPC_INJECTIVE",
    "ink": "RPC_INK",
    "mainnet": "RPC_MAINNET",
    "mantle": "RPC_MANTLE",
    "megaeth": "RPC_MEGAETH",
    "okx": "RPC_OKX",
    "optimism": "RPC_OPTIMISM",
    "sonic": "RPC_SONIC",
    "xdc": "RPC_XDC",
}

# Chain folder name -> display name for summary lists
CHAIN_DISPLAY_NAMES: dict[str, str] = {
    "arbitrum_one": "Arbitrum",
    "avalanche": "Avalanche",
    "base": "Base",
    "bnb": "BNB",
    "injective": "Injective",
    "ink": "Ink",
    "mainnet": "Mainnet",
    "mantle": "Mantle",
    "megaeth": "MegaETH",
    "okx": "OKX",
    "optimism": "Optimism",
    "sonic": "Sonic",
    "xdc": "XDC",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Check that deployment admins (DEFAULT_ADMIN_ROLE) are DAO (for CI, run per chain)."
    )
    p.add_argument("--chain", required=True, help="Chain name (e.g. arbitrum_one, mainnet).")
    p.add_argument("--rpc-url", default=None, help="RPC URL. If not set, uses env from CHAIN_TO_RPC_ENV.")
    p.add_argument("--components", default="core,oracle,vaults", help="Comma-separated: core, oracle, vaults.")
    p.add_argument("--dry-run", action="store_true", help="Only list contracts, do not call RPC.")
    p.add_argument(
        "--no-fail",
        action="store_true",
        help="Always return exit code 0 (useful when aggregating results in a separate CI job).",
    )
    p.add_argument(
        "--output-json-file",
        metavar="PATH",
        help="Write machine-readable summary JSON to PATH.",
    )
    return p.parse_args()


def _write_json_report(
    path: str,
    *,
    check_type: str,
    chain: str,
    chain_label: str,
    skipped: int,
    ok: int,
    fail: int,
    failed_contracts: list[tuple[str, str, str]],
    error: str | None = None,
) -> None:
    data: dict[str, Any] = {
        "check_type": check_type,
        "chain": chain,
        "chain_label": chain_label,
        "summary": {"skipped": skipped, "ok": ok, "fail": fail},
        "has_failure": bool(fail > 0 or error),
        "failed_contracts": [
            {"component": component, "contract_name": contract_name, "address": address}
            for component, contract_name, address in failed_contracts
        ],
        "pending_owner_contracts": [],
        "error": error,
    }
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_common_addresses(repo_root: Path, chain: str) -> dict[str, str]:
    path = repo_root / "common" / "addresses" / f"{chain}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v.strip().lower() for k, v in data.items() if isinstance(v, str) and v.strip().startswith("0x")}


def get_dao_addresses(common_addresses: dict[str, str]) -> set[str]:
    """
    Return set of DAO addresses that are allowed to be DEFAULT_ADMIN_ROLE.
    Includes both current DAO and legacy DAO_OLD when present.
    """
    addrs: set[str] = set()
    dao = common_addresses.get("DAO")
    if dao:
        addrs.add(dao)
    dao_old = common_addresses.get("DAO_OLD")
    if dao_old:
        addrs.add(dao_old)
    return addrs


def abi_has_access_control_admin(abi: list | None) -> bool:
    """True if ABI has getRoleMemberCount(bytes32) and getRoleMember(bytes32,uint256) (AccessControlEnumerable)."""
    if not abi:
        return False
    has_count = has_member = False
    for item in abi:
        if not (isinstance(item, dict) and item.get("type") == "function"):
            continue
        name = item.get("name")
        ins = item.get("inputs") or []
        types = [inp.get("type") for inp in ins]
        if name == "getRoleMemberCount" and types == ["bytes32"]:
            has_count = True
        if name == "getRoleMember" and types == ["bytes32", "uint256"]:
            has_member = True
    return has_count and has_member


def collect_deployment_addresses(
    repo_root: Path, chain: str, components: list[str]
) -> list[tuple[str, str, str, list | None]]:
    """Returns list of (component, contract_name, address, abi). abi is from deployment JSON or None."""
    out: list[tuple[str, str, str, list | None]] = []
    for comp in components:
        base = repo_root / COMPONENT_PATHS[comp] / chain
        if not base.exists():
            continue
        for j in base.glob("*.json"):
            try:
                data = json.loads(j.read_text(encoding="utf-8"))
                addr = (data.get("address") or "").strip()
                if isinstance(addr, str) and addr.startswith("0x") and len(addr) >= 42:
                    name = j.stem
                    if name.endswith(".sol"):
                        name = name[:-4]
                    abi = data.get("abi")
                    if not isinstance(abi, list):
                        abi = None
                    out.append((comp, name, addr.lower(), abi))
            except (json.JSONDecodeError, OSError):
                continue
    return out


def _format_rpc_error(err: Any) -> str:
    """Format JSON-RPC error object into a concise, human-readable string."""
    if isinstance(err, dict):
        code = err.get("code")
        msg = err.get("message")
        data = err.get("data")
        parts: list[str] = []
        if code is not None:
            parts.append(f"code={code}")
        if msg:
            parts.append(f"message={msg}")
        if data is not None:
            data_str = str(data)
            if len(data_str) > 180:
                data_str = data_str[:177] + "..."
            parts.append(f"data={data_str}")
        return ", ".join(parts) if parts else str(err)
    return str(err)


def _rpc_request(rpc_url: str, method: str, params: list[Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Perform a JSON-RPC request and return (body, error_reason)."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    try:
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError, URLError

        req = Request(
            rpc_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        status = getattr(e, "code", "unknown")
        return None, f"http_error status={status} reason={e.reason}"
    except URLError as e:
        return None, f"url_error reason={e.reason}"
    except TimeoutError as e:
        return None, f"timeout_error {e}"
    except (OSError, json.JSONDecodeError, KeyError) as e:
        return None, f"transport_or_decode_error {e}"
    return body, None


def _eth_call(rpc_url: str, to: str, data: str) -> tuple[str | None, str | None]:
    to = to if to.startswith("0x") else "0x" + to
    body, req_err = _rpc_request(rpc_url, "eth_call", [{"to": to, "data": data}, "latest"])
    if req_err:
        return None, req_err
    if body is None:
        return None, "empty_response"
    if body.get("error"):
        return None, f"rpc_error {_format_rpc_error(body.get('error'))}"
    result = (body.get("result") or "").strip()
    if not result:
        return None, "empty_result"
    return result, None


def _extract_address_from_32byte_hex(value: str | None) -> str | None:
    """Extract address from 32-byte hex word (last 20 bytes)."""
    if not value or not isinstance(value, str):
        return None
    data = value.strip().lower()
    if not data.startswith("0x"):
        return None
    hex_part = data[2:]
    if len(hex_part) != 64:
        return None
    addr = "0x" + hex_part[-40:]
    if addr == "0x" + "0" * 40:
        return None
    return addr


def detect_proxy_info(rpc_url: str, contract_address: str) -> tuple[bool, str]:
    """
    Probe proxy-related storage slots (EIP-1967).
    Returns (is_proxy, details_string).
    """
    addr = contract_address if contract_address.startswith("0x") else "0x" + contract_address
    impl_body, impl_req_err = _rpc_request(rpc_url, "eth_getStorageAt", [addr, EIP1967_IMPLEMENTATION_SLOT, "latest"])
    if impl_req_err:
        return False, f"proxy_probe_failed ({impl_req_err})"
    if impl_body is None:
        return False, "proxy_probe_failed (empty_response)"
    if impl_body.get("error"):
        return False, f"proxy_probe_failed (rpc_error {_format_rpc_error(impl_body.get('error'))})"

    impl = _extract_address_from_32byte_hex(impl_body.get("result"))

    admin = None
    admin_body, admin_req_err = _rpc_request(rpc_url, "eth_getStorageAt", [addr, EIP1967_ADMIN_SLOT, "latest"])
    if not admin_req_err and admin_body and not admin_body.get("error"):
        admin = _extract_address_from_32byte_hex(admin_body.get("result"))

    beacon = None
    beacon_body, beacon_req_err = _rpc_request(rpc_url, "eth_getStorageAt", [addr, EIP1967_BEACON_SLOT, "latest"])
    if not beacon_req_err and beacon_body and not beacon_body.get("error"):
        beacon = _extract_address_from_32byte_hex(beacon_body.get("result"))

    if impl or beacon:
        return True, f"is_proxy implementation={impl or 'none'} admin={admin or 'none'} beacon={beacon or 'none'}"

    return False, "not_proxy_eip1967_slots_empty"


def eth_call_admin(rpc_url: str, contract_address: str) -> tuple[str | None, str | None]:
    """
    Get first DEFAULT_ADMIN_ROLE holder via getRoleMemberCount + getRoleMember.
    Returns (address, error_reason).
    address is lowercase when available, otherwise None.
    error_reason is present only when address is None.
    """
    # getRoleMemberCount(DEFAULT_ADMIN_ROLE): selector + bytes32(0)
    data_count = GET_ROLE_MEMBER_COUNT_SELECTOR + DEFAULT_ADMIN_ROLE_HEX
    result, call_err = _eth_call(rpc_url, contract_address, data_count)
    if result is None:
        return None, f"admin_count_call_failed ({call_err or 'unknown'})"
    # uint256: 32 bytes = 64 hex chars
    if len(result) < 64:
        return None, f"invalid_admin_count_result len={len(result)} value={result[:60]}"
    count_hex = result[-64:]
    try:
        count = int(count_hex, 16)
    except ValueError:
        return None, f"invalid_admin_count_hex {count_hex}"
    if count == 0:
        return None, "admin_role_empty_or_zero"
    # getRoleMember(DEFAULT_ADMIN_ROLE, 0): selector + role (32 bytes) + index (32 bytes = 0)
    data_member = GET_ROLE_MEMBER_SELECTOR + DEFAULT_ADMIN_ROLE_HEX + "0" * 64
    result, call_err = _eth_call(rpc_url, contract_address, data_member)
    if result is None:
        return None, f"admin_member_call_failed ({call_err or 'unknown'})"
    if len(result) < 64:
        return None, f"invalid_admin_member_result len={len(result)} value={result[:60]}"
    addr = "0x" + result[-40:].lower()
    if addr == "0x" + "0" * 40:
        return None, "admin_role_empty_or_zero"
    return addr, None


def main() -> int:
    args = parse_args()
    chain = args.chain.strip()
    components = [c.strip() for c in args.components.split(",") if c.strip()]
    for c in components:
        if c not in COMPONENT_PATHS:
            print(f"Unknown component: {c}. Allowed: {list(COMPONENT_PATHS.keys())}", file=sys.stderr)
            if args.output_json_file:
                _write_json_report(
                    args.output_json_file,
                    check_type="admin",
                    chain=chain,
                    chain_label=CHAIN_DISPLAY_NAMES.get(chain, chain),
                    skipped=0,
                    ok=0,
                    fail=1,
                    failed_contracts=[],
                    error=f"Unknown component: {c}",
                )
            return 2

    repo_root = Path(__file__).resolve().parents[1]
    common_addresses = load_common_addresses(repo_root, chain)
    dao_addresses = get_dao_addresses(common_addresses)
    if not dao_addresses:
        print(f"DAO/DAO_OLD not found in common/addresses/{chain}.json", file=sys.stderr)
        if args.output_json_file:
            _write_json_report(
                args.output_json_file,
                check_type="admin",
                chain=chain,
                chain_label=CHAIN_DISPLAY_NAMES.get(chain, chain),
                skipped=0,
                ok=0,
                fail=1,
                failed_contracts=[],
                error=f"DAO/DAO_OLD not found in common/addresses/{chain}.json",
            )
        return 2

    addr_to_key: dict[str, str] = {addr: key for key, addr in common_addresses.items()}

    rpc_env = CHAIN_TO_RPC_ENV.get(chain)
    rpc_url = args.rpc_url or (os.environ.get(rpc_env) if rpc_env else None)
    if not args.dry_run and not rpc_url:
        hint = rpc_env or f"RPC_<chain> (add {chain!r} to CHAIN_TO_RPC_ENV)"
        print(f"RPC URL not set. Use --rpc-url or set env {hint}", file=sys.stderr)
        if args.output_json_file:
            _write_json_report(
                args.output_json_file,
                check_type="admin",
                chain=chain,
                chain_label=CHAIN_DISPLAY_NAMES.get(chain, chain),
                skipped=0,
                ok=0,
                fail=1,
                failed_contracts=[],
                error=f"RPC URL not set. Use --rpc-url or set env {hint}",
            )
        return 2

    deployments = collect_deployment_addresses(repo_root, chain, components)
    if not deployments:
        print(f"No deployments found for chain={chain}, components={components}", file=sys.stderr)
        if args.output_json_file:
            _write_json_report(
                args.output_json_file,
                check_type="admin",
                chain=chain,
                chain_label=CHAIN_DISPLAY_NAMES.get(chain, chain),
                skipped=0,
                ok=0,
                fail=0,
                failed_contracts=[],
            )
        return 0

    deployments.sort(key=lambda x: (x[0], x[1]))  # alphabetical: component, then contract name

    has_failure = False
    skip_count = 0
    ok_count = 0
    fail_count = 0
    failed_contracts: list[tuple[str, str, str]] = []

    for component, contract_name, address, abi in deployments:
        if args.dry_run:
            print(f"[dry-run] {component} {contract_name} {address}")
            continue

        if contract_name in CONTRACTS_EXCLUDED:
            print(f"[skip] {component} {contract_name} excluded from check")
            skip_count += 1
            continue

        if not abi_has_access_control_admin(abi):
            print(f"[skip] {component} {contract_name} no AccessControl")
            skip_count += 1
            continue

        admin, admin_err = eth_call_admin(rpc_url, address)
        if admin is None:
            is_silo_hook = contract_name.startswith("SiloHook")
            if admin_err == "admin_role_empty_or_zero" and is_silo_hook:
                is_proxy, proxy_details = detect_proxy_info(rpc_url, address)
                if not is_proxy:
                    print(
                        f"[ ok ] {component} {contract_name} admin role is empty/zero "
                        "(allowed for non-proxy SiloHook implementation)"
                    )
                    print(f"       -> proxy_check: {proxy_details}")
                    ok_count += 1
                    continue
                print(
                    f"[FAIL] {component} {contract_name} admin check failed for {address} "
                    f"(ABI has AccessControlEnumerable; reason: admin_role_empty_or_zero; "
                    f"proxy_check: proxy; {proxy_details})"
                )
            else:
                print(
                    f"[FAIL] {component} {contract_name} admin check failed for {address} "
                    f"(ABI has AccessControlEnumerable; reason: {admin_err or 'unknown'})"
                )
            has_failure = True
            fail_count += 1
            failed_contracts.append((component, contract_name, address))
            continue

        if admin in dao_addresses:
            print(f"[ ok ] {component} {contract_name} admin is DAO (current or legacy)")
            ok_count += 1
            continue

        key = addr_to_key.get(admin)
        if key is None:
            print(
                f"[FAIL] {component} {contract_name} admin {admin} not in common/addresses/{chain}.json "
                "(expected DAO or DAO_OLD)"
            )
        else:
            print(f"[FAIL] {component} {contract_name} admin is {key} ({admin}), expected DAO or DAO_OLD")
        has_failure = True
        fail_count += 1
        failed_contracts.append((component, contract_name, address))

    if args.dry_run:
        print(f"Dry-run: would check {len(deployments)} deployments for chain={chain}.")
        if args.output_json_file:
            _write_json_report(
                args.output_json_file,
                check_type="admin",
                chain=chain,
                chain_label=CHAIN_DISPLAY_NAMES.get(chain, chain),
                skipped=skip_count,
                ok=ok_count,
                fail=fail_count,
                failed_contracts=failed_contracts,
            )
        return 0

    print(f"Summary: skipped={skip_count} ok={ok_count} fail={fail_count}")
    if failed_contracts:
        print("Contracts failing verification:")
        for component, contract_name, contract_address in failed_contracts:
            print(f"  - {component}/{contract_name} {contract_address}")

    if args.output_json_file:
        _write_json_report(
            args.output_json_file,
            check_type="admin",
            chain=chain,
            chain_label=CHAIN_DISPLAY_NAMES.get(chain, chain),
            skipped=skip_count,
            ok=ok_count,
            fail=fail_count,
            failed_contracts=failed_contracts,
        )

    return 1 if has_failure and not args.no_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
