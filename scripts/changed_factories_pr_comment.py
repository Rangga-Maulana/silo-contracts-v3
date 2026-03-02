#!/usr/bin/env python3
"""
Detect changed deployment files (for observed contracts) between two git refs and
optionally output a PR comment body.

Used by CI to post a single (editable) comment on PRs when any observed contract
deployments change. Only contracts listed in OBSERVED_CONTRACTS are considered;
edit that list to control which deployments trigger the notification.

Usage:
  # List changed observed contract names (one per line)
  python3 scripts/changed_factories_pr_comment.py --base origin/master --head HEAD

  # Output full markdown comment body to a file for sticky-pull-request-comment
  python3 scripts/changed_factories_pr_comment.py --base origin/master --head HEAD --format comment > comment.md

  # In CI: base = github.event.pull_request.base.sha, head = github.sha
  python3 scripts/changed_factories_pr_comment.py --base $BASE_SHA --head $HEAD_SHA --format comment
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Deployment roots we consider
DEPLOYMENT_ROOTS = (
    "silo-core/deployments/",
    "silo-vaults/deployments/",
    "silo-oracles/deployments/",
)

# Contract names (Solidity filenames without .sol) whose deployment changes we notify about.
# Edit this list to add or remove observed contracts.
OBSERVED_CONTRACTS = (
    # silo-core
    "SiloFactory",
    "SiloHookV2",
    "SiloHookV3",
    "DynamicKinkModelFactory",
    # "InterestRateModelV2Factory",
    "SiloIncentivesControllerFactory",
    # silo-vaults
    "SiloVaultsFactory",
    "IdleVaultsFactory",
    # "SiloIncentivesControllerCLFactory",
    # silo-oracles
    "ManageableOracleFactory",
    "OracleScalerFactory",
    "ChainlinkV3OracleFactory",
    "DIAOracleFactory",
    "ERC4626OracleFactory",
    "ERC4626OracleWithUnderlyingFactory",
    "ERC4626OracleHardcodeQuoteFactory",
    "PTLinearOracleFactory",
    "PythAggregatorFactory",
)

# CC usernames for the PR comment
CC_USERS = ["siros-ena", "tyko0x", "yvesfracari", "jean-neiverth"]


def is_observed_deployment_path(relpath: str) -> bool:
    """True if path is under a deployment root and contract name is in OBSERVED_CONTRACTS."""
    if not any(relpath.startswith(root) for root in DEPLOYMENT_ROOTS):
        return False
    name = Path(relpath).name
    if not name.endswith(".sol.json"):
        return False
    contract_name = Path(relpath).stem.removesuffix(".sol")
    return contract_name in OBSERVED_CONTRACTS


def contract_name_from_path(relpath: str) -> str:
    """e.g. silo-core/deployments/arbitrum_one/SiloFactory.sol.json -> SiloFactory"""
    return Path(relpath).stem.removesuffix(".sol")


def get_changed_files(base: str, head: str, repo_root: Path) -> list[str]:
    """Return list of changed file paths (relative to repo root) between base and head."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {result.stderr}")
    return [p.strip() for p in result.stdout.strip().splitlines() if p.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List changed observed contract deployments (see OBSERVED_CONTRACTS) and optionally format as PR comment.",
    )
    parser.add_argument(
        "--base",
        required=True,
        help="Base git ref (e.g. origin/master or pull request base SHA).",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Head git ref (default: HEAD).",
    )
    parser.add_argument(
        "--format",
        choices=["names", "comment"],
        default="names",
        help="Output: 'names' = one contract name per line; 'comment' = full markdown comment body.",
    )
    parser.add_argument(
        "--cc",
        nargs="*",
        default=CC_USERS,
        help="GitHub usernames to CC in the comment (default: yvesfracari jean-neiverth).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    changed = get_changed_files(args.base, args.head, repo_root)
    observed_paths = [p for p in changed if is_observed_deployment_path(p)]
    contract_names = sorted({contract_name_from_path(p) for p in observed_paths})

    if args.format == "names":
        for name in contract_names:
            print(name)
        return 0

    # Format as PR comment body – only when there are changes; no comment otherwise
    if not contract_names:
        return 0
    body_lines = [
        "🏭 **Deployments**",
        "",
        "Changed observed deployments (contract names):",
        "",
    ]
    for name in contract_names:
        body_lines.append(f"- `{name}`")
    body_lines.append("")
    body_lines.append("⚠️ Do not copy or use these addresses until this PR is merged. This is a notification only; after merge, use the new deployment addresses.")
    body_lines.append("")
    if args.cc:
        body_lines.append("CC: " + " ".join(f"@{u}" for u in args.cc))

    print("\n".join(body_lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
