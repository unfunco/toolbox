#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path

from update_actions_state import (
    load_action_names,
    load_state_entries,
    parse_state_entries,
    resolve_action_metadata_for_tag,
    serialize_state,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate state.json updates in a pull request."
    )
    parser.add_argument("--actions-file", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument(
        "--base-ref",
        required=True,
        help="Git revision for the pull request base, preferably the event base SHA.",
    )
    return parser.parse_args()


def git_stdout(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], check=False, capture_output=True, text=True
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise SystemExit(message or f"git {' '.join(args)} failed")

    return completed.stdout


def changed_files(base_ref: str) -> list[str]:
    output = git_stdout("diff", "--name-only", f"{base_ref}...HEAD")
    return [line for line in output.splitlines() if line]


def load_base_entries(base_ref: str, state_file: str) -> dict[str, dict[str, str]]:
    completed = subprocess.run(
        ["git", "show", f"{base_ref}:{state_file}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return {}

    return parse_state_entries(completed.stdout)


def changed_action_names(
    previous_entries: dict[str, dict[str, str]],
    current_entries: dict[str, dict[str, str]],
) -> list[str]:
    action_names = set(previous_entries) | set(current_entries)
    return sorted(
        action_name
        for action_name in action_names
        if previous_entries.get(action_name) != current_entries.get(action_name)
    )


def main() -> int:
    args = parse_args()
    changed_paths = changed_files(args.base_ref)
    if args.state_file not in changed_paths:
        print("state.json was not changed in this pull request.")
        return 0

    actions_file = Path(args.actions_file)
    state_file = Path(args.state_file)

    allowed_actions = set(load_action_names(actions_file))
    current_entries = load_state_entries(state_file)

    unknown_actions = sorted(set(current_entries) - allowed_actions)
    if unknown_actions:
        raise SystemExit(
            "state.json contains actions that are not present in actions.txt: "
            + ", ".join(unknown_actions)
        )

    serialized_state = serialize_state(current_entries)
    actual_state = state_file.read_text()
    if actual_state != serialized_state:
        raise SystemExit(
            "state.json must use the canonical sorted JSON format produced by the updater."
        )

    base_entries = load_base_entries(args.base_ref, args.state_file)
    changed_actions = changed_action_names(base_entries, current_entries)
    if not changed_actions:
        print("state.json only changed formatting, and the canonical format is valid.")
        return 0

    for action_name in changed_actions:
        current_entry = current_entries.get(action_name)
        if current_entry is None:
            if action_name in allowed_actions:
                raise SystemExit(
                    f"state.json removed {action_name}, but it is still present in actions.txt."
                )

            print(f"Validated removal of {action_name}.")
            continue

        print(f"Validating {action_name}@{current_entry['tag']}...")
        expected_entry = resolve_action_metadata_for_tag(
            action_name, current_entry["tag"]
        )

        if current_entry != expected_entry:
            raise SystemExit(
                f"state.json entry for {action_name} does not match GitHub metadata for "
                f"tag {current_entry['tag']}. Expected sha={expected_entry['sha']} and "
                f"published_at={expected_entry['published_at']}, got "
                f"sha={current_entry['sha']} and "
                f"published_at={current_entry['published_at']}."
            )

    print(f"Validated {len(changed_actions)} state.json change(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
