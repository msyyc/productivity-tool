#!/usr/bin/env python3
"""Find new Spector/spec case PRs and create Python test coverage issues.

This script recreates the disabled python-check-spec-tests GitHub Action as an
on-demand local workflow. It compares the spec package versions pinned by the
Python emitter against the most recently published npm package versions, finds
merged source PRs in that publish window that touched spec cases, creates issues
for missing test coverage, and prints a markdown summary.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


PACKAGE_JSON_URL = "https://raw.githubusercontent.com/microsoft/typespec/main/packages/http-client-python/package.json"
DEFAULT_SKILL_URL = "https://github.com/microsoft/typespec/blob/main/.github/skills/python-sdk-spector-mock-api-tests/SKILL.md"
DEFAULT_ISSUE_REPO = "microsoft/typespec"
DEFAULT_LABEL = "emitter:client:python"
DEFAULT_ASSIGNEE = "copilot-swe-agent[bot]"


@dataclass(frozen=True)
class PackageCheck:
    package_name: str
    repo: str
    specs_path: str


@dataclass(frozen=True)
class ReportRow:
    package_name: str
    source_pr_url: str
    action: str
    issue_or_reason: str


PACKAGE_CHECKS = [
    PackageCheck("@typespec/http-specs", "microsoft/typespec", "packages/http-specs/specs"),
    PackageCheck("@azure-tools/azure-http-specs", "Azure/typespec-azure", "packages/azure-http-specs/specs"),
]


def eprint(message: str) -> None:
    print(f"# {message}", file=sys.stderr)


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "find-new-spector-case"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_package_json(url: str) -> dict[str, Any]:
    data = fetch_json(url)
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected package.json payload from {url}")
    return data


def fetch_npm_time_data(package_name: str) -> dict[str, str]:
    npm_command = shutil.which("npm") or shutil.which("npm.cmd")
    npm_stderr = "npm was not found on PATH"
    if npm_command:
        proc = subprocess.run(
            [npm_command, "view", package_name, "time", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        npm_stderr = proc.stderr.strip()
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            if isinstance(data, dict):
                return {str(key): str(value) for key, value in data.items()}
            raise RuntimeError(f"Unexpected npm time data for {package_name}")

    eprint(f"npm view failed for {package_name}; trying the npm registry API")
    encoded_name = urllib.parse.quote(package_name, safe="")
    data = fetch_json(f"https://registry.npmjs.org/{encoded_name}")
    time_data = data.get("time")
    if not isinstance(time_data, dict):
        raise RuntimeError(f"Could not find npm time data for {package_name}. npm stderr: {npm_stderr}")
    return {str(key): str(value) for key, value in time_data.items()}


def latest_published_version(time_data: dict[str, str]) -> str | None:
    versions = [(version, timestamp) for version, timestamp in time_data.items() if version not in {"created", "modified"}]
    if not versions:
        return None
    versions.sort(key=lambda item: item[1])
    return versions[-1][0]


def run_gh(args: list[str], *, input_text: str | None = None) -> str:
    proc = subprocess.run(
        ["gh", *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        command = " ".join(["gh", *args])
        raise RuntimeError(f"{command} failed (exit {proc.returncode}):\n{proc.stderr.strip()}")
    return proc.stdout


def parse_paginated_json(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    if not text:
        return []
    return json.loads(text.replace("][", ","))


def list_merged_prs(repo: str, start_date: str, end_date: str, limit: int) -> list[dict[str, Any]]:
    output = run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "merged",
            "--search",
            f"merged:{start_date}..{end_date}",
            "--limit",
            str(limit),
            "--json",
            "number,title,url,mergedAt",
        ]
    )
    return json.loads(output)


def pr_touches_specs(repo: str, pr_number: int, specs_path: str) -> bool:
    output = run_gh(["api", "--paginate", f"repos/{repo}/pulls/{pr_number}/files?per_page=100"])
    files = parse_paginated_json(output)
    prefix = specs_path.rstrip("/") + "/"
    return any(str(file_info.get("filename", "")).startswith(prefix) for file_info in files)


def existing_issue_url(issue_repo: str, source_pr_url: str) -> str | None:
    output = run_gh(
        [
            "issue",
            "list",
            "--repo",
            issue_repo,
            "--state",
            "all",
            "--search",
            f"in:title {source_pr_url}",
            "--json",
            "title,url",
            "--limit",
            "100",
        ]
    )
    issues = json.loads(output)
    for issue in issues:
        if source_pr_url in issue.get("title", ""):
            return issue.get("url")
    return None


def create_issue(
    issue_repo: str,
    source_pr_url: str,
    skill_url: str,
    label: str,
    assignee: str,
    include_agent_assignment: bool,
) -> str:
    title = f"[python] add test case for {source_pr_url}"
    body = f"follow skill {skill_url} to write test case for {source_pr_url}"
    payload: dict[str, Any] = {
        "title": title,
        "body": body,
        "labels": [label],
        "assignees": [assignee],
    }
    if include_agent_assignment:
        payload["agent_assignment"] = {"target_repo": issue_repo, "base_branch": "main"}

    return run_gh(
        [
            "api",
            "--method",
            "POST",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
            f"/repos/{issue_repo}/issues",
            "--input",
            "-",
            "--jq",
            ".html_url",
        ],
        input_text=json.dumps(payload),
    ).strip()


def version_specifier_to_version(specifier: str) -> str:
    return specifier.strip().lstrip("^~=")


def check_package(
    package_check: PackageCheck,
    package_json: dict[str, Any],
    issue_repo: str,
    skill_url: str,
    label: str,
    assignee: str,
    limit: int,
    dry_run: bool,
    include_agent_assignment: bool,
) -> list[ReportRow]:
    eprint(f"Checking package: {package_check.package_name}")
    dev_dependencies = package_json.get("devDependencies", {})
    if not isinstance(dev_dependencies, dict):
        raise RuntimeError("package.json devDependencies is missing or invalid")

    pinned_specifier = dev_dependencies.get(package_check.package_name)
    if not pinned_specifier:
        return [ReportRow(package_check.package_name, "", "skipped", "package not found in devDependencies")]

    version_a = version_specifier_to_version(str(pinned_specifier))
    time_data = fetch_npm_time_data(package_check.package_name)
    version_b = latest_published_version(time_data)
    if not version_b:
        return [ReportRow(package_check.package_name, "", "skipped", "could not determine latest npm version")]

    date_a = time_data.get(version_a)
    date_b = time_data.get(version_b)
    if not date_a:
        return [ReportRow(package_check.package_name, "", "skipped", f"could not find publish date for pinned version {version_a}")]
    if not date_b:
        return [ReportRow(package_check.package_name, "", "skipped", f"could not find publish date for latest version {version_b}")]

    eprint(f"Pinned {version_a} published at {date_a}; latest {version_b} published at {date_b}")
    if date_b <= date_a:
        return [ReportRow(package_check.package_name, "", "up-to-date", f"pinned {version_a} is current enough")]

    start_date = date_a[:10]
    end_date = date_b[:10]
    merged_prs = list_merged_prs(package_check.repo, start_date, end_date, limit)
    eprint(f"Found {len(merged_prs)} merged PR(s) in {package_check.repo} between {start_date} and {end_date}")

    rows: list[ReportRow] = []
    for pr in merged_prs:
        pr_number = int(pr["number"])
        source_pr_url = str(pr["url"])
        if not pr_touches_specs(package_check.repo, pr_number, package_check.specs_path):
            continue

        issue_url = existing_issue_url(issue_repo, source_pr_url)
        if issue_url:
            rows.append(ReportRow(package_check.package_name, source_pr_url, "skipped existing", issue_url))
            eprint(f"Issue already exists for {source_pr_url}: {issue_url}")
            continue

        if dry_run:
            rows.append(ReportRow(package_check.package_name, source_pr_url, "would create", "dry-run"))
            eprint(f"Would create issue for {source_pr_url}")
            continue

        issue_url = create_issue(issue_repo, source_pr_url, skill_url, label, assignee, include_agent_assignment)
        rows.append(ReportRow(package_check.package_name, source_pr_url, "created", issue_url))
        eprint(f"Created issue for {source_pr_url}: {issue_url}")

    if not rows:
        rows.append(ReportRow(package_check.package_name, "", "skipped", f"no merged PRs touched {package_check.specs_path}"))
    return rows


def markdown_link(url: str) -> str:
    return f"[{url}]({url})" if url else ""


def build_report(rows: list[ReportRow]) -> str:
    created_count = sum(1 for row in rows if row.action == "created")
    existing_count = sum(1 for row in rows if row.action == "skipped existing")
    would_create_count = sum(1 for row in rows if row.action == "would create")

    lines = [
        "# New Python Spector Case Issues",
        "",
        f"Created: {created_count} issue(s)",
        f"Skipped existing: {existing_count} issue(s)",
    ]
    if would_create_count:
        lines.append(f"Would create: {would_create_count} issue(s)")
    lines.extend(
        [
            "",
            "| Package | Source PR | Action | Issue / Reason |",
            "| --- | --- | --- | --- |",
        ]
    )

    for row in rows:
        source_pr = markdown_link(row.source_pr_url)
        issue_or_reason = markdown_link(row.issue_or_reason) if row.issue_or_reason.startswith("http") else row.issue_or_reason
        lines.append(f"| {row.package_name} | {source_pr} | {row.action} | {issue_or_reason} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-json-url", default=PACKAGE_JSON_URL, help="Raw package.json URL to inspect")
    parser.add_argument("--issue-repo", default=DEFAULT_ISSUE_REPO, help="Repo where issues are created")
    parser.add_argument("--skill-url", default=DEFAULT_SKILL_URL, help="Skill URL to put in created issue bodies")
    parser.add_argument("--label", default=DEFAULT_LABEL, help="Issue label to apply")
    parser.add_argument("--assignee", default=DEFAULT_ASSIGNEE, help="Issue assignee")
    parser.add_argument("--limit", type=int, default=200, help="Maximum merged PRs to inspect per package")
    parser.add_argument("--dry-run", action="store_true", help="Report issues that would be created without creating them")
    parser.add_argument(
        "--no-agent-assignment",
        action="store_true",
        help="Do not include the GitHub Copilot agent_assignment payload when creating issues",
    )
    args = parser.parse_args()

    package_json = fetch_package_json(args.package_json_url)
    all_rows: list[ReportRow] = []
    for package_check in PACKAGE_CHECKS:
        all_rows.extend(
            check_package(
                package_check,
                package_json,
                args.issue_repo,
                args.skill_url,
                args.label,
                args.assignee,
                args.limit,
                args.dry_run,
                not args.no_agent_assignment,
            )
        )

    print(build_report(all_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())