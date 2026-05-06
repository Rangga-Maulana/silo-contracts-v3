from __future__ import annotations

import json
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"
CHAIN_TO_MULTICALL3: dict[str, str] = {
    "xdc": "0x0B1795ccA8E4eC4df02346a082df54D437F8D9aF",
}
AGGREGATE3_SELECTOR = "0x82ad56cb"


def multicall_address_for_chain(chain: str) -> str:
    return CHAIN_TO_MULTICALL3.get(chain, DEFAULT_MULTICALL3)


def format_rpc_error(err: Any) -> str:
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


def rpc_request(
    rpc_url: str,
    method: str,
    params: list[Any],
    *,
    timeout: int = 30,
    request_id: int = 1,
) -> tuple[dict[str, Any] | None, str | None]:
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    try:
        req = Request(
            rpc_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        status = getattr(e, "code", "unknown")
        return None, f"http_error status={status} reason={e.reason}"
    except URLError as e:
        return None, f"url_error reason={e.reason}"
    except socket.timeout:
        return None, f"timeout_error timeout={timeout}s method={method}"
    except TimeoutError:
        return None, f"timeout_error timeout={timeout}s method={method}"
    except (OSError, json.JSONDecodeError, KeyError) as e:
        return None, f"transport_or_decode_error {e}"
    return body, None


def rpc_preflight(rpc_url: str, *, timeout: int = 20) -> str | None:
    """
    Single RPC health check for a script run.
    Returns None when RPC is healthy, otherwise an error string.
    """
    body, err = rpc_request(rpc_url, "eth_chainId", [], timeout=timeout)
    if err:
        return err
    if body is None:
        return "empty_response"
    if body.get("error"):
        return f"rpc_error {format_rpc_error(body.get('error'))}"
    result = body.get("result")
    if not (isinstance(result, str) and result.startswith("0x")):
        return f"invalid_chain_id_response {result}"
    return None


def rpc_batch_request(
    rpc_url: str,
    calls: list[tuple[int, str, list[Any]]],
    *,
    timeout: int = 45,
) -> tuple[dict[int, dict[str, Any]], str | None]:
    payload = [
        {"jsonrpc": "2.0", "id": call_id, "method": method, "params": params}
        for call_id, method, params in calls
    ]
    try:
        req = Request(
            rpc_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        status = getattr(e, "code", "unknown")
        return {}, f"http_error status={status} reason={e.reason}"
    except URLError as e:
        return {}, f"url_error reason={e.reason}"
    except socket.timeout:
        return {}, f"timeout_error timeout={timeout}s batch_size={len(calls)}"
    except TimeoutError:
        return {}, f"timeout_error timeout={timeout}s batch_size={len(calls)}"
    except (OSError, json.JSONDecodeError, KeyError) as e:
        return {}, f"transport_or_decode_error {e}"

    if not isinstance(body, list):
        return {}, "invalid_batch_response expected_list"

    by_id: dict[int, dict[str, Any]] = {}
    for entry in body:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if isinstance(entry_id, int):
            by_id[entry_id] = entry
    return by_id, None


def _enc_uint256(v: int) -> str:
    return hex(v)[2:].zfill(64)


def _enc_address(addr: str) -> str:
    a = addr.lower()
    if a.startswith("0x"):
        a = a[2:]
    return ("0" * 24) + a.zfill(40)


def _enc_bool(v: bool) -> str:
    return ("0" * 63) + ("1" if v else "0")


def _enc_bytes(hex_data: str) -> str:
    h = hex_data[2:] if hex_data.startswith("0x") else hex_data
    h = h.lower()
    pad = (64 - (len(h) % 64)) % 64
    return _enc_uint256(len(h) // 2) + h + ("0" * pad)


def _encode_aggregate3_calls(calls: list[tuple[str, bool, str]]) -> str:
    """
    Encode aggregate3((address,bool,bytes)[]) args (without selector).
    """
    encoded_elems: list[str] = []
    for target, allow_failure, call_data in calls:
        head = _enc_address(target) + _enc_bool(allow_failure) + _enc_uint256(96)
        tail = _enc_bytes(call_data)
        encoded_elems.append(head + tail)

    # For dynamic array of dynamic tuples, array body is:
    # [length][offset_0..offset_n-1][elem_0][elem_1]...
    n = len(encoded_elems)
    # Offsets are relative to the start of array elements area (right after length word).
    head_size = 32 * n  # bytes: offsets area only
    offsets: list[str] = []
    cursor = head_size
    for elem in encoded_elems:
        offsets.append(_enc_uint256(cursor))
        cursor += len(elem) // 2

    array_body = _enc_uint256(n) + "".join(offsets) + "".join(encoded_elems)
    return _enc_uint256(32) + array_body


def _decode_aggregate3_results(result_hex: str) -> list[tuple[bool, str | None]]:
    h = result_hex[2:] if result_hex.startswith("0x") else result_hex
    if len(h) < 128:
        return []
    try:
        arr_offset = int(h[0:64], 16) * 2
        n = int(h[arr_offset : arr_offset + 64], 16)
    except ValueError:
        return []

    out: list[tuple[bool, str | None]] = []
    # array layout: [length][offset_0..offset_n-1][elem_0..elem_n-1]
    offsets_start = arr_offset + 64
    for i in range(n):
        off_pos = offsets_start + i * 64
        if off_pos + 64 > len(h):
            out.append((False, None))
            continue
        try:
            elem_rel_off_bytes = int(h[off_pos : off_pos + 64], 16)
        except ValueError:
            out.append((False, None))
            continue
        # Offsets are relative to the start of elements area (right after length).
        elem_start = offsets_start + (elem_rel_off_bytes * 2)
        if elem_start + 128 > len(h):
            out.append((False, None))
            continue

        success_word = h[elem_start : elem_start + 64]
        success = int(success_word, 16) != 0
        offset_word = h[elem_start + 64 : elem_start + 128]
        try:
            bytes_off = int(offset_word, 16) * 2
        except ValueError:
            out.append((False, None))
            continue
        bytes_len_pos = elem_start + bytes_off
        if bytes_len_pos + 64 > len(h):
            out.append((success, None))
            continue
        try:
            bytes_len = int(h[bytes_len_pos : bytes_len_pos + 64], 16)
        except ValueError:
            out.append((success, None))
            continue
        bytes_data_start = bytes_len_pos + 64
        bytes_data_end = bytes_data_start + bytes_len * 2
        if bytes_data_end > len(h):
            out.append((success, None))
            continue
        out_data = "0x" + h[bytes_data_start:bytes_data_end]
        out.append((success, out_data))
    return out


def multicall_eth_calls(
    chain: str,
    rpc_url: str,
    calls: list[tuple[str, str]],
    *,
    timeout: int = 120,
) -> tuple[list[tuple[str | None, str | None]], str | None]:
    """
    Execute many eth_call operations via Multicall3 aggregate3 in one request.
    Returns [(result_hex_or_none, error_or_none), ...], global_error.
    """
    if not calls:
        return [], None

    mc_addr = multicall_address_for_chain(chain)
    arg_data = _encode_aggregate3_calls([(to, True, data) for to, data in calls])
    calldata = AGGREGATE3_SELECTOR + arg_data
    body, req_err = rpc_request(
        rpc_url,
        "eth_call",
        [{"to": mc_addr, "data": calldata}, "latest"],
        timeout=timeout,
    )
    if req_err:
        return [], f"multicall_transport_error {req_err}"
    if body is None:
        return [], "multicall_transport_error empty_response"
    if body.get("error"):
        return [], f"multicall_rpc_error {format_rpc_error(body.get('error'))}"

    raw_result = (body.get("result") or "").strip()
    if not raw_result or raw_result == "0x":
        return [], "multicall_empty_result"

    decoded = _decode_aggregate3_results(raw_result)
    if len(decoded) != len(calls):
        return [], f"multicall_decode_mismatch expected={len(calls)} got={len(decoded)}"

    results: list[tuple[str | None, str | None]] = []
    for ok, value in decoded:
        if ok:
            results.append((value, None))
        else:
            results.append((None, "subcall_failed"))
    return results, None

