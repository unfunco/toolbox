#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path

from update_pins import (
    load_action_sources,
    load_pin_entries,
    parse_pin_entries,
    resolve_action_metadata,
    serialize_pins,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate pins data updates in a pull request."
    )
    parser.add_argument("--actions-file", required=True)
    parser.add_argument("--pins-file", required=True)
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


def base_path_candidates(path: str) -> list[str]:
    candidates = [path]
    if path == "pins.json":
        candidates.append("_data/pins.json")
    return candidates


def load_base_pin_entries(base_ref: str, pins_file: str) -> dict[str, dict[str, str]]:
    for candidate in base_path_candidates(pins_file):
        completed = subprocess.run(
            ["git", "show", f"{base_ref}:{candidate}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return parse_pin_entries(completed.stdout)

    return {}


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
    if args.pins_file not in changed_paths:
        print(f"{args.pins_file} was not changed in this pull request.")
        return 0

    actions_file = Path(args.actions_file)
    pins_file = Path(args.pins_file)

    action_sources = load_action_sources(actions_file)
    allowed_actions = {action_source.action for action_source in action_sources}
    ref_overrides = {
        action_source.action: action_source.ref_override
        for action_source in action_sources
        if action_source.ref_override is not None
    }
    current_entries = load_pin_entries(pins_file)

    unknown_actions = sorted(set(current_entries) - allowed_actions)
    if unknown_actions:
        raise SystemExit(
            f"{args.pins_file} contains actions that are not present in "
            f"{args.actions_file}: "
            + ", ".join(unknown_actions)
        )

    serialized_pins = serialize_pins(current_entries)
    actual_pins = pins_file.read_text()
    if actual_pins != serialized_pins:
        raise SystemExit(
            f"{args.pins_file} must use the canonical sorted JSON format produced "
            "by the updater."
        )

    base_entries = load_base_pin_entries(args.base_ref, args.pins_file)
    changed_actions = changed_action_names(base_entries, current_entries)
    if not changed_actions:
        print(
            f"{args.pins_file} only changed formatting, and the canonical format is valid."
        )
        return 0

    for action_name in changed_actions:
        current_entry = current_entries.get(action_name)
        if current_entry is None:
            if action_name in allowed_actions:
                raise SystemExit(
                    f"{args.pins_file} removed {action_name}, but it is still present "
                    f"in {args.actions_file}."
                )

            print(f"Validated removal of {action_name}.")
            continue

        print(f"Validating {action_name}@{current_entry['tag']}...")
        ref_override = ref_overrides.get(action_name)
        expected_entry = resolve_action_metadata(action_name, ref_override)

        if current_entry != expected_entry:
            raise SystemExit(
                f"{args.pins_file} entry for {action_name} does not match the updater output. "
                f"Expected tag={expected_entry['tag']} sha={expected_entry['sha']} and "
                f"published_at={expected_entry['published_at']}, got tag={current_entry['tag']} "
                f"sha={current_entry['sha']} and published_at={current_entry['published_at']}."
            )

    print(f"Validated {len(changed_actions)} {args.pins_file} change(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
