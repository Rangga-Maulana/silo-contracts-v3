#!/usr/bin/env python3
"""
Merge per-chain verification JSON artifacts into a single PR comment.

Used by CI when verification runs in separate jobs per chain. Each job uploads
a JSON artifact; this script merges them and optionally with the existing
PR comment (for re-run of failed jobs).

Usage:
  # Merge artifacts from directory, output to stdout
  python3 scripts/merge_verification_reports.py --artifacts-dir ./artifacts

  # Merge with existing PR comment (fetch via gh CLI)
  python3 scripts/merge_verification_reports.py --artifacts-dir ./artifacts --pr-comment-from-gh

  # Output to file
  python3 scripts/merge_verification_reports.py --artifacts-dir ./artifacts -o report.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# Must match output from check_deployments_verified_on_explorer.py (avalanche has 2 explorers)
SECTION_ORDER = [
    "Arbitrum",
    "Avalanche (routescan)",
    "Avalanche (etherscan)",
    "Base",
    "BNB",
    "Injective",
    "Mainnet",
    "Optimism",
    "OKX",
    "Sonic",
]

# Block explorer address URL (append address). display_label -> base URL.
EXPLORER_ADDRESS_URL: dict[str, str] = {
    "Arbitrum": "https://arbiscan.io/address/",
    "Avalanche (routescan)": "https://avalanche.routescan.io/address/",
    "Avalanche (etherscan)": "https://snowtrace.io/address/",
    "Base": "https://basescan.org/address/",
    "BNB": "https://bscscan.com/address/",
    "Injective": "https://blockscout.injective.network/address/",
    "Mainnet": "https://etherscan.io/address/",
    "Optimism": "https://optimistic.etherscan.io/address/",
    "OKX": "https://www.oklink.com/x-layer/address/",
    "Sonic": "https://sonicscan.org/address/",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Merge verification JSON artifacts into PR comment.")
    p.add_argument(
        "--artifacts-dir",
        required=True,
        help="Directory containing verification_<chain>.json files.",
    )
    p.add_argument(
        "--pr-comment-from-gh",
        action="store_true",
        help="Fetch existing PR comment via gh CLI and merge (for re-run of failed jobs).",
    )
    p.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Write output to file (default: stdout).",
    )
    return p.parse_args()


def load_artifacts(artifacts_dir: Path) -> dict[str, dict]:
    """Load all verification_*.json files (searches recursively). Returns {display_label: section_data}."""
    result: dict[str, dict] = {}
    for jf in artifacts_dir.glob("**/verification_*.json"):
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sections = data.get("sections", [])
        for s in sections:
            label = s.get("display_label")
            if label:
                result[label] = s
    return result


def parse_existing_comment(body: str) -> dict[str, dict]:
    """
    Parse existing PR comment markdown to extract per-section data.
    Returns {display_label: section_data} where section_data has at least
    display_label for re-merge; we store the raw markdown for display.
    """
    result: dict[str, dict] = {}
    # Match ### Section ... until next ### or end
    pattern = re.compile(r"^### (.+?)$\s*\n(.*?)(?=^### |\Z)", re.MULTILINE | re.DOTALL)
    for m in pattern.finditer(body):
        label = m.group(1).strip()
        content = m.group(2).strip()
        result[label] = {"display_label": label, "_raw": content}
    return result


def fetch_pr_comment() -> str | None:
    """Fetch existing sticky comment body via gh CLI. Returns None if not found."""
    import os

    try:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        event_path = os.environ.get("GITHUB_EVENT_PATH", "")
        if not repo:
            return None

        pr_num = None
        if event_path and Path(event_path).exists():
            event = json.loads(Path(event_path).read_text())
            pr_num = event.get("pull_request", {}).get("number")
        if pr_num is None:
            return None

        out = subprocess.run(
            ["gh", "api", f"repos/{repo}/issues/{pr_num}/comments"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode != 0:
            return None

        comments = json.loads(out.stdout)
        for c in comments:
            body = c.get("body", "")
            if "## Deployment verification on block explorers" in body or "deployment-verification" in body:
                body = re.sub(r"<!-- UNVERIFIED_CONTRACTS_REPORT -->\s*", "", body)
                body = re.sub(r"\s*<!-- /UNVERIFIED_CONTRACTS_REPORT -->", "", body)
                return body.strip()
    except Exception:
        pass
    return None


def _format_address_link(display_label: str, address: str) -> str:
    """Format address as markdown link to block explorer, or plain text if no URL."""
    base_url = EXPLORER_ADDRESS_URL.get(display_label)
    if base_url and address:
        return f"[`{address}`]({base_url}{address})"
    return f"`{address}`"


def section_to_markdown(s: dict) -> str:
    """Convert section data to markdown. When all verified, returns single line only."""
    label = s.get("display_label", "Unknown")
    config_error = s.get("config_error")
    nv = s.get("not_verified", 0)
    fe = s.get("fetch_errors", 0)
    verified = s.get("verified", 0)

    if config_error is None and nv == 0 and fe == 0:
        return f"**{label}: all {verified} contracts verified.**"

    lines = [f"### {label}", ""]
    if config_error:
        lines.append(f"⚠️ **Could not check:** {config_error}")
    else:
        lines.append(f"- **Verified:** {verified}")
        lines.append(f"- **Not verified:** {nv}")
        lines.append(f"- **Errors (could not check):** {fe}")
        lines.append("")
        unverified = s.get("unverified", [])
        errors_list = s.get("errors", [])
        if unverified:
            lines.append("**Unverified contracts:**")
            lines.append("")
            for u in unverified:
                path_display = u.get("source_path") or f"{u.get('component', '')}/{u.get('contract_name', '')}"
                addr = u.get("address", "")
                addr_link = _format_address_link(label, addr)
                lines.append(f"- `{path_display}` {addr_link}")
            lines.append("")
        if errors_list:
            lines.append("**Errors (could not check):**")
            lines.append("")
            for u in errors_list:
                path_display = u.get("source_path") or f"{u.get('component', '')}/{u.get('contract_name', '')}"
                addr = u.get("address", "")
                addr_link = _format_address_link(label, addr)
                lines.append(f"- `{path_display}` {addr_link}")
            lines.append("")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    artifacts_dir = Path(args.artifacts_dir)
    if not artifacts_dir.exists():
        print("Artifacts directory does not exist.", file=sys.stderr)
        return 1

    # Start with existing comment sections (for re-run)
    merged: dict[str, dict] = {}
    existing_body: str | None = None
    if args.pr_comment_from_gh:
        existing_body = fetch_pr_comment()
        if existing_body:
            merged = parse_existing_comment(existing_body)

    # Override with new artifacts
    artifacts = load_artifacts(artifacts_dir)
    for label, data in artifacts.items():
        if "_raw" not in data:
            merged[label] = data

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # If we have existing body but no sections, use it as-is when no artifacts
    if not merged and existing_body and not artifacts:
        content = existing_body
        if not content.strip().startswith("##"):
            content = "## Deployment verification on block explorers\n\n" + content
        body = (
            "<!-- UNVERIFIED_CONTRACTS_REPORT -->\n"
            f"{timestamp}\n\n"
            f"{content}\n"
            "<!-- /UNVERIFIED_CONTRACTS_REPORT -->"
        )
        if args.output:
            Path(args.output).write_text(body, encoding="utf-8")
        else:
            print(body)
        return 0

    if not merged:
        content = (
            f"{timestamp}\n\n"
            "## Deployment verification on block explorers\n\n"
            "No verification results (no artifacts and no existing comment)."
        )
    else:
        ordered_labels = [x for x in SECTION_ORDER if x in merged]
        for label in merged:
            if label not in ordered_labels:
                ordered_labels.append(label)

        all_verified = True
        parts = []
        for label in ordered_labels:
            data = merged[label]
            if "_raw" in data:
                parts.append(f"### {label}\n\n{data['_raw']}")
                all_verified = False
            else:
                config_error = data.get("config_error")
                nv = data.get("not_verified", 0)
                fe = data.get("fetch_errors", 0)
                if config_error or nv > 0 or fe > 0:
                    all_verified = False
                parts.append(section_to_markdown(data))

        expected_count = len(SECTION_ORDER)
        if all_verified and len(ordered_labels) >= expected_count:
            content = (
                f"{timestamp}\n\n"
                "## Deployment verification on block explorers\n\n"
                "All deployment contracts are verified on block explorers."
            )
        else:
            content = (
                f"{timestamp}\n\n"
                "## Deployment verification on block explorers\n\n"
                + "\n".join(parts).rstrip()
            )

    body = (
        "<!-- UNVERIFIED_CONTRACTS_REPORT -->\n"
        f"{content}\n"
        "<!-- /UNVERIFIED_CONTRACTS_REPORT -->"
    )

    if args.output:
        Path(args.output).write_text(body, encoding="utf-8")
    else:
        print(body)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
