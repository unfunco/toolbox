#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SEMVER_TAG_RE = re.compile(
    r"^v?(?P<major>\d+)"
    r"(?:\.(?P<minor>\d+))?"
    r"(?:\.(?P<patch>\d+))?"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)


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
        "User-Agent": "github-toolbox-pins-updater",
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


def resolve_commit_for_ref(action_name: str, ref_name: str) -> dict:
    encoded_ref = urllib.parse.quote(ref_name, safe="")
    return github_get_json(f"/repos/{action_name}/commits/{encoded_ref}")


def release_for_tag(action_name: str, tag_name: str) -> dict | None:
    encoded_tag = urllib.parse.quote(tag_name, safe="")
    try:
        return github_get_json(f"/repos/{action_name}/releases/tags/{encoded_tag}")
    except GitHubNotFoundError:
        return None


def build_action_metadata(
    action_name: str, tag_name: str, commit: dict, published_at: str
) -> dict[str, str]:
    return {
        "action": action_name,
        "tag": tag_name,
        "sha": commit["sha"],
        "published_at": published_at,
    }


def resolve_action_metadata_for_tag(
    action_name: str, tag_name: str, release: dict | None = None
) -> dict[str, str]:
    commit = resolve_commit_for_ref(action_name, tag_name)
    if release is None:
        release = release_for_tag(action_name, tag_name)

    published_at = commit["commit"]["committer"]["date"]
    if release is not None:
        published_at = (
            release.get("published_at")
            or release.get("created_at")
            or commit["commit"]["committer"]["date"]
        )

    return build_action_metadata(action_name, tag_name, commit, published_at)


def resolve_action_metadata(action_name: str) -> dict[str, str]:
    try:
        latest_release = github_get_json(f"/repos/{action_name}/releases/latest")
        return resolve_action_metadata_for_tag(
            action_name, latest_release["tag_name"], release=latest_release
        )
    except GitHubNotFoundError:
        tags = github_get_json(f"/repos/{action_name}/tags?per_page=100")
        if not tags:
            raise GitHubApiError(
                f"{action_name} has no published releases or tags to pin."
            ) from None

        return resolve_action_metadata_for_tag(action_name, choose_best_tag(tags))


def load_action_names(actions_file: Path) -> list[str]:
    actions = [
        line.strip() for line in actions_file.read_text().splitlines() if line.strip()
    ]
    return actions


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

    all_actions = load_action_names(actions_file)
    selected_actions = [
        action_name
        for action_name in all_actions
        if shard_for(action_name) == args.shard
    ]

    print(
        f"Selected {len(selected_actions)} action(s) for shard {args.shard}: "
        + (", ".join(selected_actions) if selected_actions else "(none)")
    )

    current_entries = load_pin_entries(pins_file)
    for action_name in selected_actions:
        print(f"Resolving latest metadata for {action_name}...")
        current_entries[action_name] = resolve_action_metadata(action_name)

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
