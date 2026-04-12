#!/usr/bin/env python3

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ACTION_NAME_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")
REF_OVERRIDE_RE = re.compile(r"^[^,\s]+$")
SEMVER_TAG_RE = re.compile(
    r"^v?(?P<major>\d+)"
    r"(?:\.(?P<minor>\d+))?"
    r"(?:\.(?P<patch>\d+))?"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)


@dataclass(frozen=True)
class ActionSource:
    action: str
    ref_override: Optional[str] = None


class GitHubApiError(RuntimeError):
    pass


class GitHubNotFoundError(GitHubApiError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh a deterministic 1/24th shard of pins metadata."
    )
    parser.add_argument("--actions-file", required=True)
    parser.add_argument("--pins-file", required=True)
    parser.add_argument("--shard", required=True, type=int)
    return parser.parse_args()


def api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-actions-pins-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def github_api_url(path: str) -> str:
    api_root = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    return f"{api_root}/{path.lstrip('/')}"


def github_get_json(path: str):
    request = urllib.request.Request(github_api_url(path), headers=api_headers())

    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace").strip()
        if exc.code == 404:
            raise GitHubNotFoundError(path) from exc

        raise GitHubApiError(
            f"GitHub API request failed for {path}: HTTP {exc.code} {response_body}"
        ) from exc


def shard_for(action_name: str) -> int:
    return int(hashlib.sha256(action_name.encode("utf-8")).hexdigest(), 16) % 24


def semver_sort_key(tag_name: str):
    match = SEMVER_TAG_RE.fullmatch(tag_name)
    if match is None:
        return None

    prerelease = match.group("prerelease")
    return (
        int(match.group("major")),
        int(match.group("minor") or 0),
        int(match.group("patch") or 0),
        1 if prerelease is None else 0,
        prerelease or "",
    )


def choose_best_tag(tags: list[dict]) -> str:
    semver_candidates: list[tuple[tuple, str]] = []
    for tag in tags:
        tag_name = tag["name"]
        sort_key = semver_sort_key(tag_name)
        if sort_key is not None:
            semver_candidates.append((sort_key, tag_name))

    if semver_candidates:
        semver_candidates.sort(reverse=True)
        return semver_candidates[0][1]

    return tags[0]["name"]


def repo_for_action(action_name: str) -> str:
    parts = action_name.split("/", 2)
    if len(parts) < 2:
        raise GitHubApiError(f"Invalid action name: {action_name!r}")
    return f"{parts[0]}/{parts[1]}"


def resolve_commit_for_ref(action_name: str, ref_name: str) -> dict:
    encoded_ref = urllib.parse.quote(ref_name, safe="")
    try:
        return github_get_json(f"/repos/{repo_for_action(action_name)}/commits/{encoded_ref}")
    except GitHubNotFoundError:
        raise GitHubApiError(
            f"{action_name}@{ref_name} does not exist or is not accessible."
        ) from None


def release_for_tag(action_name: str, tag_name: str) -> Optional[dict]:
    encoded_tag = urllib.parse.quote(tag_name, safe="")
    try:
        return github_get_json(f"/repos/{repo_for_action(action_name)}/releases/tags/{encoded_tag}")
    except GitHubNotFoundError:
        return None


def build_action_metadata(
    action_name: str, ref_name: str, commit: dict, published_at: str
) -> dict[str, str]:
    return {
        "action": action_name,
        "tag": ref_name,
        "sha": commit["sha"],
        "published_at": published_at,
    }


def resolve_action_metadata_for_ref(
    action_name: str, ref_name: str, release: Optional[dict] = None
) -> dict[str, str]:
    commit = resolve_commit_for_ref(action_name, ref_name)
    if release is None:
        release = release_for_tag(action_name, ref_name)

    published_at = commit["commit"]["committer"]["date"]
    if release is not None:
        published_at = (
            release.get("published_at")
            or release.get("created_at")
            or commit["commit"]["committer"]["date"]
        )

    return build_action_metadata(action_name, ref_name, commit, published_at)


def resolve_action_metadata_for_tag(
    action_name: str, tag_name: str, release: Optional[dict] = None
) -> dict[str, str]:
    return resolve_action_metadata_for_ref(action_name, tag_name, release=release)


def resolve_action_metadata(
    action_name: str, ref_override: Optional[str] = None
) -> dict[str, str]:
    if ref_override is not None:
        return resolve_action_metadata_for_ref(action_name, ref_override)

    repo = repo_for_action(action_name)
    try:
        latest_release = github_get_json(f"/repos/{repo}/releases/latest")
        return resolve_action_metadata_for_ref(
            action_name, latest_release["tag_name"], release=latest_release
        )
    except GitHubNotFoundError:
        tags = github_get_json(f"/repos/{repo}/tags?per_page=100")
        if not tags:
            raise GitHubApiError(
                f"{action_name} has no published releases or tags to pin."
            ) from None

        return resolve_action_metadata_for_ref(action_name, choose_best_tag(tags))


def parse_action_sources(
    raw_text: str, source_name: str = "<actions file>", legacy_format: bool = False
) -> list[ActionSource]:
    action_sources: list[ActionSource] = []
    seen_actions: set[str] = set()

    if legacy_format:
        for row_number, raw_line in enumerate(raw_text.splitlines(), start=1):
            if not raw_line:
                continue

            line = raw_line.strip()
            if raw_line != line:
                raise SystemExit(
                    f"{source_name}:{row_number} must not include leading or trailing whitespace."
                )

            if ACTION_NAME_RE.fullmatch(line) is None:
                raise SystemExit(
                    f"{source_name}:{row_number} must match org/repo or org/repo/subpath."
                )

            if line in seen_actions:
                raise SystemExit(f"{source_name}:{row_number} duplicates {line}.")

            seen_actions.add(line)
            action_sources.append(ActionSource(action=line))

        return action_sources

    reader = csv.reader(io.StringIO(raw_text))
    for row_number, row in enumerate(reader, start=1):
        if not row or row == [""]:
            continue

        if len(row) > 2:
            raise SystemExit(
                f"{source_name}:{row_number} must contain action[,ref_override]."
            )

        raw_action = row[0]
        if raw_action != raw_action.strip():
            raise SystemExit(
                f"{source_name}:{row_number} action must not include surrounding whitespace."
            )

        action_name = raw_action.strip()
        if not action_name:
            raise SystemExit(f"{source_name}:{row_number} is missing an action name.")

        if ACTION_NAME_RE.fullmatch(action_name) is None:
            raise SystemExit(
                f"{source_name}:{row_number} action must match org/repo or org/repo/subpath."
            )

        ref_override = None
        if len(row) == 2:
            raw_ref_override = row[1]
            if raw_ref_override != raw_ref_override.strip():
                raise SystemExit(
                    f"{source_name}:{row_number} ref override must not include surrounding whitespace."
                )

            ref_override = raw_ref_override.strip() or None
            if (
                ref_override is not None
                and REF_OVERRIDE_RE.fullmatch(ref_override) is None
            ):
                raise SystemExit(
                    f"{source_name}:{row_number} ref override contains invalid characters."
                )

        if action_name in seen_actions:
            raise SystemExit(f"{source_name}:{row_number} duplicates {action_name}.")

        seen_actions.add(action_name)
        action_sources.append(
            ActionSource(action=action_name, ref_override=ref_override)
        )

    return action_sources


def load_action_sources(actions_file: Path) -> list[ActionSource]:
    return parse_action_sources(
        actions_file.read_text(),
        source_name=str(actions_file),
        legacy_format=actions_file.suffix == ".txt",
    )


def load_action_names(actions_file: Path) -> list[str]:
    return [action_source.action for action_source in load_action_sources(actions_file)]


def serialize_action_sources(action_sources: list[ActionSource]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    for action_source in sorted(action_sources, key=lambda source: source.action):
        row = [action_source.action]
        if action_source.ref_override is not None:
            row.append(action_source.ref_override)
        writer.writerow(row)

    return output.getvalue()


def parse_pin_entries(raw_text: str) -> dict[str, dict[str, str]]:
    raw_text = raw_text.strip()
    if not raw_text:
        return {}

    raw_state = json.loads(raw_text)
    if raw_state == {}:
        return {}

    entries = raw_state.get("actions")
    if not isinstance(entries, list):
        raise SystemExit("Pins data must contain an object with an 'actions' array.")

    by_action: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("Each pins data entry must be an object.")

        action_name = entry.get("action")
        if not isinstance(action_name, str) or not action_name:
            raise SystemExit("Each pins data entry must include a non-empty 'action'.")

        by_action[action_name] = {
            "action": action_name,
            "tag": str(entry.get("tag", "")),
            "sha": str(entry.get("sha", "")),
            "published_at": str(entry.get("published_at", "")),
        }

    return by_action


def load_pin_entries(pins_file: Path) -> dict[str, dict[str, str]]:
    if not pins_file.exists():
        return {}

    return parse_pin_entries(pins_file.read_text())


def serialize_pins(entries_by_action: dict[str, dict[str, str]]) -> str:
    ordered_entries = [
        entries_by_action[action] for action in sorted(entries_by_action)
    ]
    return json.dumps({"actions": ordered_entries}, indent=2) + "\n"


def main() -> int:
    args = parse_args()

    if args.shard < 0 or args.shard > 23:
        raise SystemExit("--shard must be between 0 and 23.")

    actions_file = Path(args.actions_file)
    pins_file = Path(args.pins_file)

    all_action_sources = load_action_sources(actions_file)
    selected_actions = [
        action_source
        for action_source in all_action_sources
        if shard_for(action_source.action) == args.shard
    ]

    print(
        f"Selected {len(selected_actions)} action(s) for shard {args.shard}: "
        + (
            ", ".join(action_source.action for action_source in selected_actions)
            if selected_actions
            else "(none)"
        )
    )

    current_entries = load_pin_entries(pins_file)
    for action_source in selected_actions:
        if action_source.ref_override is None:
            print(f"Resolving latest metadata for {action_source.action}...")
        else:
            print(
                f"Resolving metadata for "
                f"{action_source.action}@{action_source.ref_override}..."
            )

        current_entries[action_source.action] = resolve_action_metadata(
            action_source.action, action_source.ref_override
        )

    original_text = pins_file.read_text() if pins_file.exists() else ""
    next_text = serialize_pins(current_entries)
    pins_file.write_text(next_text)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as output:
            print(f"selected_count={len(selected_actions)}", file=output)
            print(
                f"changed={'true' if next_text != original_text else 'false'}",
                file=output,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
