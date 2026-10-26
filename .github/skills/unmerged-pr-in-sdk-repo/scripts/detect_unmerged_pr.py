#!/usr/bin/env python3
"""Report open, non-draft AutoPR management SDK PRs that need action.

GitHub data, including base-branch CODEOWNERS and team membership, is read
through gh. No local SDK checkout is needed and no GitHub data is modified.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, quote, urlparse

TITLE_PREFIX = "[AutoPR azure-mgmt-"
SDK_NAME_RE = re.compile(r"^\[AutoPR\s+(azure-mgmt-[^\]]+)\]")
VERSION_ADD_RE = re.compile(r'^\+\s*VERSION\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
CHANGELOG_HEADING_RE = re.compile(r"^##\s+([0-9][^\s(]*)", re.MULTILINE)
RELEASE_PLAN_LABEL_RE = re.compile(
    r"(?:\*\*)?release plan(?:[ \t]+link)?(?:\*\*)?[ \t]*[:：-](?:\*\*)?[ \t]*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
RELEASE_PLAN_SECTION_RE = re.compile(
    r"^#{1,6}[ \t]+release plan[ \t]*\r?\n(.*?)(?=\r?\n#{1,6}[ \t]+|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
RELEASE_PLAN_TABLE_RE = re.compile(
    r"^[ \t]*\|[ \t]*(?:\*\*)?release plan(?:[ \t]+link)?(?:\*\*)?[ \t]*\|([^\r\n|]*)",
    re.IGNORECASE | re.MULTILINE,
)
HTTP_LINK_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)|(https?://[^\s<>]+)", re.IGNORECASE)


class GhError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str):
        self.stderr = stderr
        super().__init__(f"gh {' '.join(args)} failed (exit {returncode}):\n{stderr.strip()}")


@dataclass(frozen=True)
class OwnerRule:
    pattern: re.Pattern[str]
    owners: tuple[str, ...]


@dataclass(frozen=True)
class ActionPR:
    number: int
    url: str
    sdk_name: str
    version: str
    created: str
    needs_label: bool
    owners: tuple[str, ...]
    approval: dict | None
    newer_commits: bool
    release_plan: str | None
    ownership_issues: tuple[str, ...] = ()


def run_gh(args: list[str]) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise GhError(args, proc.returncode, proc.stderr)
    return proc.stdout


def api_pages(endpoint: str) -> list[dict]:
    pages = json.loads(run_gh(["api", "--paginate", "--slurp", endpoint]))
    return [item for page in pages for item in page]


def list_autopr_prs(repo: str, limit: int) -> list[dict]:
    prs = json.loads(
        run_gh(
            [
                "pr", "list", "--repo", repo, "--search", "AutoPR azure-mgmt in:title",
                "--state", "open", "--json", "number,title,url,createdAt,isDraft",
                "--limit", str(limit),
            ]
        )
    )
    if len(prs) >= limit:
        print(f"# WARNING: listing reached --limit {limit}; increase it for a complete scan.", file=sys.stderr)
    return [pr for pr in prs if pr["title"].startswith(TITLE_PREFIX) and not pr["isDraft"]]


def sdk_name_from_title(title: str) -> str | None:
    match = SDK_NAME_RE.match(title)
    return match.group(1) if match else None


def sdk_files(files: list[dict], sdk_name: str) -> list[dict]:
    return [
        file for file in files
        if any(sdk_name in file.get(key, "").split("/") for key in ("filename", "previous_filename"))
    ]


def sdk_version(files: list[dict]) -> str | None:
    for file in files:
        if file["filename"].endswith("/_version.py"):
            match = VERSION_ADD_RE.search(file.get("patch", ""))
            if match:
                return match.group(1)
    for file in files:
        if file["filename"].endswith("/CHANGELOG.md"):
            added = "\n".join(line[1:] for line in file.get("patch", "").splitlines() if line.startswith("+"))
            match = CHANGELOG_HEADING_RE.search(added)
            if match:
                return match.group(1)
    return None


def codeowners_pattern(pattern: str) -> re.Pattern[str]:
    rooted = pattern.startswith("/")
    pattern = pattern.lstrip("/")
    directory = pattern.endswith("/")
    pattern = pattern.rstrip("/")
    prefix = "^" if rooted or "/" in pattern else r"(?:^|/)"
    parts = pattern.split("/")
    translated = ""
    for index, part in enumerate(parts):
        if part == "**":
            translated += ".*" if index == len(parts) - 1 else "(?:[^/]+/)*"
            continue
        translated += "".join("[^/]*" if char == "*" else "[^/]" if char == "?" else re.escape(char)
                              for char in part)
        if index < len(parts) - 1:
            translated += "/"
    return re.compile(prefix + translated + ("/" if directory else r"(?:/|$)"))


def parse_codeowners(text: str) -> list[OwnerRule]:
    rules = []
    for line in text.splitlines():
        tokens = line.split("#", 1)[0].split()
        if not tokens or tokens[0].startswith("!") or any(char in tokens[0] for char in "[]\\"):
            continue
        rules.append(OwnerRule(codeowners_pattern(tokens[0]), tuple(tokens[1:])))
    return rules


def load_codeowners(repo: str, base_sha: str) -> list[OwnerRule]:
    for path in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        try:
            content = json.loads(run_gh(["api", f"repos/{repo}/contents/{path}?ref={quote(base_sha, safe='')}"]))
        except GhError as error:
            if "HTTP 404" not in error.stderr:
                raise
            continue
        if content.get("encoding") != "base64":
            raise RuntimeError(f"Cannot decode {path} at {base_sha}: expected base64 file content.")
        rules = parse_codeowners(base64.b64decode(content["content"]).decode("utf-8"))
        if not rules:
            raise RuntimeError(f"No usable ownership rules in {path} at {base_sha}.")
        return rules
    raise RuntimeError(f"No CODEOWNERS file found in {repo} at base commit {base_sha}.")


def owners_for_files(files: list[dict], rules: list[OwnerRule]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    owners: set[str] = set()
    issues = []
    if not files:
        issues.append("No changed SDK package files found; cannot determine CODEOWNERS.")
    for file in files:
        path = file["filename"]
        # A deleted or renamed file is reviewed using its path on the base branch.
        if file.get("status") == "renamed":
            path = file["previous_filename"]
        matched = ()
        for rule in rules:
            if rule.pattern.search(path):
                matched = rule.owners
        owners.update(matched)
        if not matched:
            issues.append(f"No CODEOWNERS configured for {path}.")
    return tuple(sorted(owners, key=str.casefold)), tuple(dict.fromkeys(issues))


def resolve_maintainers(
    owners: tuple[str, ...], team_cache: dict[str, tuple[set[str], str | None]]
) -> tuple[set[str], tuple[str, ...]]:
    maintainers = set()
    issues = []
    for owner in owners:
        if not owner.startswith("@"):
            issues.append(f"Cannot resolve CODEOWNERS entry {owner} to a GitHub login.")
        elif "/" not in owner:
            maintainers.add(owner[1:].casefold())
        else:
            if owner not in team_cache:
                org, team = owner[1:].split("/", 1)
                try:
                    members = api_pages(f"orgs/{org}/teams/{team}/members?per_page=100")
                except GhError as error:
                    team_cache[owner] = (set(), f"Cannot read members of {owner}: {error}")
                else:
                    team_cache[owner] = ({member["login"].casefold() for member in members}, None)
            members, issue = team_cache[owner]
            maintainers.update(members)
            if issue:
                issues.append(issue)
    return maintainers, tuple(issues)


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def latest_maintainer_approval(reviews: list[dict], maintainers: set[str]) -> dict | None:
    latest = {}
    for review in sorted(
        (review for review in reviews if review.get("submitted_at")),
        key=lambda review: (timestamp(review["submitted_at"]), review["id"]),
    ):
        login = (review.get("user") or {}).get("login", "").casefold()
        if login in maintainers and review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[login] = review
    approvals = [review for review in latest.values() if review["state"] == "APPROVED"]
    return max(approvals, key=lambda review: timestamp(review["submitted_at"])) if approvals else None


def has_newer_commits(commits: list[dict], approval: dict, head_sha: str) -> bool:
    if approval.get("commit_id") and approval["commit_id"] != head_sha:
        return True
    approved_at = timestamp(approval["submitted_at"])
    return any(timestamp(commit["commit"]["committer"]["date"]) > approved_at for commit in commits)


def first_http_link(text: str) -> str | None:
    match = LINK_RE.search(text)
    return (match.group(1) or match.group(2)).rstrip(".,);]") if match else None


def extract_release_plan(body: str) -> str | None:
    for match in RELEASE_PLAN_TABLE_RE.finditer(body):
        link = first_http_link(match.group(1))
        if link:
            return link
    for match in RELEASE_PLAN_LABEL_RE.finditer(body):
        link = first_http_link(match.group(1))
        if link:
            return link
    for match in RELEASE_PLAN_SECTION_RE.finditer(body):
        link = first_http_link(match.group(1))
        if link:
            return link
    for match in HTTP_LINK_RE.finditer(body):
        link = match.group(0).rstrip(".,);]")
        query = parse_qs(urlparse(link).query)
        if any(value.isdigit() for key in ("releaseplan", "releasePlan") for value in query.get(key, [])):
            return link
    return None


def build_report(repo: str, rows: list[ActionPR]) -> str:
    rows = sorted(rows, key=lambda row: timestamp(row.created), reverse=True)
    sections = (
        (
            "1. Add `mgmt-review-needed`",
            "Add this label manually to trigger Copilot review.",
            [row for row in rows if row.needs_label],
        ),
        (
            "2. SDK maintainer review needed",
            "A maintainer configured in CODEOWNERS needs to review and approve. "
            "Resolve any ownership-verification warnings before deciding that approval is missing.",
            [row for row in rows if row.approval is None or row.ownership_issues],
        ),
        (
            "3. SDK maintainer re-review needed",
            "New commits were found after SDK-maintainer approval; review the updated PR again.",
            [row for row in rows if row.newer_commits],
        ),
        (
            "4. Release plan needs checking",
            "Check the PR description. If the release plan is missing, contact the service team to create "
            "and link one. If a link is already present, update this skill to recognize it.",
            [row for row in rows if row.release_plan is None],
        ),
    )
    output = []
    for title, hint, entries in sections:
        if not entries:
            continue
        output.extend([f"## {title}", "", hint, ""])
        for row in entries:
            item = f"- [{repo}#{row.number}]({row.url}) - `{row.sdk_name}` `{row.version}`"
            if title.startswith("2."):
                if row.ownership_issues:
                    item += " - approval verification incomplete; check warnings."
                else:
                    item += " - no SDK-maintainer approval."
                if row.owners:
                    item += f" Maintainers: {', '.join(row.owners)}."
            elif title.startswith("3."):
                assert row.approval is not None
                item += (
                    f" - approved by @{row.approval['user']['login']} "
                    f"on {row.approval['submitted_at'][:10]}; newer commits require re-review."
                )
            elif title.startswith("4."):
                item += " - no release-plan link detected."
            output.append(item)
            for issue in row.ownership_issues if title.startswith("2.") else ():
                output.append(f"  Ownership warning: {' '.join(issue.split())}")
        output.append("")
    return "\n".join(output).strip() if output else "No PRs need action."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="Azure/azure-sdk-for-python")
    parser.add_argument("--exclude-version", default="1.0.0b1")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")

    prs = list_autopr_prs(args.repo, args.limit)
    print(f"# Found {len(prs)} open, non-draft AutoPR management SDK PRs.", file=sys.stderr)
    rows = []
    ownership_cache: dict[str, list[OwnerRule]] = {}
    team_cache: dict[str, tuple[set[str], str | None]] = {}
    for pr in prs:
        name = sdk_name_from_title(pr["title"])
        if not name:
            continue
        number = pr["number"]
        endpoint = f"repos/{args.repo}/pulls/{number}"
        details = json.loads(run_gh(["api", endpoint]))
        if details["draft"] or details["state"] != "open":
            continue
        files = sdk_files(api_pages(f"{endpoint}/files?per_page=100"), name)
        version = sdk_version(files)
        if version == args.exclude_version:
            print(f"# PR {number} {name}: version {version} excluded.", file=sys.stderr)
            continue
        if version is None:
            print(f"# WARNING: PR {number} {name}: SDK version could not be determined.", file=sys.stderr)
        base_sha = details["base"]["sha"]
        if base_sha not in ownership_cache:
            ownership_cache[base_sha] = load_codeowners(args.repo, base_sha)
        owners, issues = owners_for_files(files, ownership_cache[base_sha])
        maintainers, resolution_issues = resolve_maintainers(owners, team_cache)
        reviews = api_pages(f"{endpoint}/reviews?per_page=100")
        approval = latest_maintainer_approval(reviews, maintainers)
        newer = False
        if approval:
            commits = api_pages(f"{endpoint}/commits?per_page=100")
            newer = has_newer_commits(commits, approval, details["head"]["sha"])
        row = ActionPR(
            number=number, url=pr["url"], sdk_name=name, version=version or "unknown",
            created=pr["createdAt"],
            needs_label=not any(label["name"].casefold() == "mgmt-review-needed" for label in details["labels"]),
            owners=owners, approval=approval, newer_commits=newer,
            release_plan=extract_release_plan(details.get("body") or ""),
            ownership_issues=issues + resolution_issues,
        )
        rows.append(row)
        print(f"# PR {number} {name}: checked.", file=sys.stderr)
    print(build_report(args.repo, rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
