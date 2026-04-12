#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional

from update_pins import (
    ActionSource,
    GitHubApiError,
    GitHubNotFoundError,
    github_get_json,
    load_action_sources,
    parse_action_sources,
    repo_for_action,
    resolve_commit_for_ref,
    serialize_action_sources,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate actions source updates in a pull request."
    )
    parser.add_argument("--actions-file", required=True)
    parser.add_argument(
        "--base-ref",
        required=True,
        help="Git revision for the pull request base, preferably the event base SHA.",
    )
    return parser.parse_args()


def base_path_candidates(path: str) -> list[str]:
    candidates = [path]
    if path == "actions.csv":
        candidates.extend(["actions.txt", "pins/actions.csv", "pins/actions.txt"])
    return candidates


def load_base_action_sources(base_ref: str, actions_file: str) -> list[ActionSource]:
    for candidate in base_path_candidates(actions_file):
        completed = subprocess.run(
            ["git", "show", f"{base_ref}:{candidate}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return parse_action_sources(
                completed.stdout,
                source_name=f"{base_ref}:{candidate}",
                legacy_format=candidate.endswith(".txt"),
            )

    return []


def source_map(action_sources: list[ActionSource]) -> dict[str, ActionSource]:
    return {action_source.action: action_source for action_source in action_sources}


def github_path_exists(path: str) -> bool:
    try:
        github_get_json(path)
        return True
    except GitHubNotFoundError:
        return False


def subpath_for_action(action_name: str) -> Optional[str]:
    parts = action_name.split("/", 2)
    if len(parts) < 3:
        return None
    return parts[2]


def validate_action_exists(action_name: str) -> None:
    repo = repo_for_action(action_name)
    try:
        github_get_json(f"/repos/{repo}")
    except GitHubNotFoundError:
        raise SystemExit(f"Repository does not exist or is not accessible: {repo}")

    subpath = subpath_for_action(action_name)
    if subpath is not None:
        if github_path_exists(f"/repos/{repo}/contents/{subpath}/action.yml") or github_path_exists(
            f"/repos/{repo}/contents/{subpath}/action.yaml"
        ):
            print(f"Verified GitHub Action: {action_name}")
            return

        raise SystemExit(
            f"{action_name} does not appear to be a GitHub Action "
            f"(missing {subpath}/action.yml or {subpath}/action.yaml)."
        )

    if (
        github_path_exists(f"/repos/{repo}/contents/action.yml")
        or github_path_exists(f"/repos/{repo}/contents/action.yaml")
        or github_path_exists(f"/repos/{repo}/contents/Dockerfile")
    ):
        print(f"Verified GitHub Action repository: {action_name}")
        return

    raise SystemExit(
        f"{action_name} does not appear to be a GitHub Action "
        "(missing root action.yml, action.yaml, or Dockerfile)."
    )


def validate_source_entry(action_source: ActionSource) -> None:
    validate_action_exists(action_source.action)

    if action_source.ref_override is None:
        return

    try:
        resolve_commit_for_ref(action_source.action, action_source.ref_override)
    except GitHubApiError as exc:
        raise SystemExit(str(exc))

    print(
        f"Verified ref override for "
        f"{action_source.action}@{action_source.ref_override}"
    )


def main() -> int:
    args = parse_args()
    actions_file = Path(args.actions_file)

    current_action_sources = load_action_sources(actions_file)
    canonical_source = serialize_action_sources(current_action_sources)
    actual_source = actions_file.read_text()
    if actual_source != canonical_source:
        raise SystemExit(
            f"{args.actions_file} must use the canonical sorted CSV format."
        )

    base_action_sources = load_base_action_sources(args.base_ref, args.actions_file)
    current_by_action = source_map(current_action_sources)
    base_by_action = source_map(base_action_sources)

    changed_actions = sorted(set(base_by_action) | set(current_by_action))
    validated_count = 0
    for action_name in changed_actions:
        current_action_source = current_by_action.get(action_name)
        if current_action_source == base_by_action.get(action_name):
            continue

        if current_action_source is None:
            print(f"Validated removal of {action_name}.")
            continue

        validate_source_entry(current_action_source)
        validated_count += 1

    print(f"Validated {validated_count} new or updated action source entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
