"""Regenerate a Python Azure Mgmt SDK package from swagger and open a PR.

End-to-end orchestrator. Any failure raises and exits with non-zero status.

Usage:
    python regen_sdk.py <sdk-name> <tag> [--work-dir C:/dev]

Example:
    python regen_sdk.py azure-mgmt-frontdoor package-2024-05
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path


VERSION_RE = re.compile(r'^(VERSION\s*[:=]\s*["\'])([^"\']+)(["\'])', re.MULTILINE)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def run(cmd, cwd: Path, env=None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and raise on failure with full output context."""
    printable = cmd if isinstance(cmd, str) else " ".join(str(c) for c in cmd)
    print(f"$ ({cwd}) {printable}", flush=True)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        shell=isinstance(cmd, str),
    )
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed (exit {proc.returncode}): {printable}")
    return proc


# ---------------------------------------------------------------------------
# step 1: pre-flight checks
# ---------------------------------------------------------------------------


def check_repos(work_dir: Path) -> tuple[Path, Path]:
    spec_repo = work_dir / "azure-rest-api-specs"
    sdk_repo = work_dir / "azure-sdk-for-python"
    if not spec_repo.is_dir():
        raise FileNotFoundError(f"spec repo not found: {spec_repo}")
    if not sdk_repo.is_dir():
        raise FileNotFoundError(f"SDK repo not found: {sdk_repo}")
    return spec_repo, sdk_repo


def check_venv(sdk_repo: Path) -> Path:
    venv = sdk_repo / ".venv"
    if not venv.is_dir():
        raise FileNotFoundError(f".venv not found under {sdk_repo}")
    return venv


# ---------------------------------------------------------------------------
# step 2: find readme.md
# ---------------------------------------------------------------------------


def find_readme(spec_repo: Path, sdk_name: str) -> str:
    spec_root = spec_repo / "specification"
    if not spec_root.is_dir():
        raise FileNotFoundError(f"specification folder not found: {spec_root}")

    matches: list[Path] = []
    for python_md in spec_root.rglob("readme.python.md"):
        try:
            text = python_md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if sdk_name in text:
            readme = python_md.with_name("readme.md")
            if readme.is_file():
                matches.append(readme)

    if not matches:
        raise LookupError(f"No readme.python.md referencing '{sdk_name}' under {spec_root}")
    if len(matches) > 1:
        joined = "\n".join(f"  - {m}" for m in matches)
        raise LookupError(f"Multiple readme.python.md match '{sdk_name}':\n{joined}")

    rel = matches[0].resolve().relative_to(spec_repo.resolve()).as_posix()
    return rel


# ---------------------------------------------------------------------------
# step 3: clean + sync repo
# ---------------------------------------------------------------------------


def clean_and_sync(repo: Path) -> str:
    subprocess.run(["git", "reset", "HEAD"], cwd=str(repo), check=False)
    subprocess.run(["git", "clean", "-fd"], cwd=str(repo), check=False)
    subprocess.run(["git", "checkout", "."], cwd=str(repo), check=False)
    run(["git", "fetch", "origin", "main"], repo)
    run(["git", "checkout", "origin/main"], repo)
    run(["git", "pull", "origin", "main"], repo)
    return run(["git", "rev-parse", "HEAD"], repo).stdout.strip()


# ---------------------------------------------------------------------------
# step 4: write generator input json
# ---------------------------------------------------------------------------


def write_input_json(venv: Path, head_sha: str, tag: str, readme_path: str, release_type: str) -> Path:
    payload = {
        "specFolder": "../azure-rest-api-specs",
        "headSha": head_sha,
        "runMode": "release",
        "repoHttpsUrl": "https://github.com/Azure/azure-rest-api-specs",
        "python_tag": tag,
        "sdkReleaseType": release_type,
        "enableChangelog": False,
        "relatedReadmeMdFiles": [readme_path],
    }
    target = venv / "generate_input_swagger.json"
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# step 5: install tooling + run generator inside the venv
# ---------------------------------------------------------------------------


def venv_bin(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts"
    return venv / "bin"


def venv_env(venv: Path) -> dict:
    env = os.environ.copy()
    bin_dir = venv_bin(venv)
    env["VIRTUAL_ENV"] = str(venv)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env.pop("PYTHONHOME", None)
    return env


def install_and_generate(sdk_repo: Path, venv: Path, input_json: Path) -> Path:
    env = venv_env(venv)
    pip = venv_bin(venv) / ("pip.exe" if os.name == "nt" else "pip")
    sdk_generator = venv_bin(venv) / ("sdk_generator.exe" if os.name == "nt" else "sdk_generator")

    run([str(pip), "install", "-e", "eng/tools/azure-sdk-tools[ghtools]"], sdk_repo, env=env)

    output_json = venv / "generate_output.json"
    # use forward-slash relative paths so the generator's downstream calls behave consistently
    run(
        [str(sdk_generator), ".venv/generate_input_swagger.json", ".venv/generate_output.json"],
        sdk_repo,
        env=env,
    )
    return output_json


# ---------------------------------------------------------------------------
# step 6: bump version + rewrite CHANGELOG
# ---------------------------------------------------------------------------


def locate_package(sdk_repo: Path, sdk_name: str) -> Path:
    candidates = list(sdk_repo.glob(f"sdk/*/{sdk_name}"))
    if not candidates:
        raise LookupError(f"Package folder not found: {sdk_repo}/sdk/*/{sdk_name}")
    if len(candidates) > 1:
        raise LookupError(f"Multiple package folders match {sdk_name}: {candidates}")
    return candidates[0]


def find_version_file(pkg_dir: Path) -> Path:
    matches = sorted(pkg_dir.rglob("_version.py"), key=lambda p: len(p.parts))
    if not matches:
        raise LookupError(f"_version.py not found under {pkg_dir}")
    return matches[0]


def decrement_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"Unexpected version format: {version!r} (need A.B.C)")
    major, minor, patch = parts
    if patch != "0":
        raise ValueError(f"Expected patch == 0 in version {version!r}")
    minor_int = int(minor)
    if minor_int <= 0:
        raise ValueError(f"Cannot decrement minor in version {version!r}")
    return f"{major}.{minor_int - 1}.1"


def bump_version_file(version_file: Path) -> tuple[str, str]:
    text = version_file.read_text(encoding="utf-8")
    m = VERSION_RE.search(text)
    if not m:
        raise LookupError(f"VERSION assignment not found in {version_file}")
    old = m.group(2)
    new = decrement_version(old)
    new_text = VERSION_RE.sub(rf"\g<1>{new}\g<3>", text, count=1)
    version_file.write_text(new_text, encoding="utf-8")
    return old, new


def ensure_aiohttp_in_dev_requirements(pkg_dir: Path) -> bool:
    """Ensure `aiohttp` is listed in `<pkg_dir>/dev_requirements.txt`. Append it
    if missing. Returns True if the file was modified."""
    dev_req = pkg_dir / "dev_requirements.txt"
    if not dev_req.is_file():
        dev_req.write_text("aiohttp\n", encoding="utf-8")
        return True
    text = dev_req.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # strip version specifiers / extras / markers
        name = re.split(r"[<>=!~;\[\s]", line, 1)[0].strip().lower()
        if name == "aiohttp":
            return False
    if text and not text.endswith("\n"):
        text += "\n"
    text += "aiohttp\n"
    dev_req.write_text(text, encoding="utf-8")
    return True


def rewrite_changelog(changelog: Path, new_version: str) -> None:
    """Keep the date in the topmost `## <version> (<date>)` heading; replace the
    version with `new_version` and replace the section body with the regen note."""
    text = changelog.read_text(encoding="utf-8")
    lines = text.splitlines()

    first_idx = second_idx = None
    for i, line in enumerate(lines):
        if line.startswith("## "):
            if first_idx is None:
                first_idx = i
            else:
                second_idx = i
                break

    if first_idx is None:
        raise LookupError(f"No '## ' section found in {changelog}")

    old_header = lines[first_idx]
    m = re.match(r"^##\s+\S+(\s*\(.*\))?\s*$", old_header)
    if not m:
        raise LookupError(f"Unexpected CHANGELOG heading format: {old_header!r}")
    date_part = m.group(1) or ""
    new_header = f"## {new_version}{date_part}"

    body = [
        "",
        "### Other Changes",
        "",
        "  - Regenerated with latest code generator tool",
        "",
    ]
    tail = lines[second_idx:] if second_idx is not None else []
    new_lines = lines[:first_idx] + [new_header] + body + tail
    changelog.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# step 7: branch, push, open PR
# ---------------------------------------------------------------------------


def push_and_create_pr(sdk_repo: Path, sdk_name: str) -> tuple[str, str]:
    if not run(["git", "status", "--porcelain"], sdk_repo).stdout.strip():
        raise RuntimeError("No changes to commit in SDK repo after regeneration.")

    branch = f"regen-{sdk_name}-{dt.date.today().isoformat()}"
    title = f"Regenerate {sdk_name} with latest code generator tool"

    run(["git", "checkout", "-B", branch], sdk_repo)
    run(["git", "add", "-A"], sdk_repo)
    run(["git", "commit", "-m", title], sdk_repo)
    run(["git", "push", "-u", "origin", branch, "--force"], sdk_repo)

    pr = run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            "Azure/azure-sdk-for-python",
            "--base",
            "main",
            "--head",
            branch,
            "--title",
            title,
            "--body",
            f"Regenerate `{sdk_name}` with latest code generator tool.",
        ],
        sdk_repo,
    )
    pr_url = (pr.stdout.strip().splitlines() or [""])[-1]
    return branch, pr_url


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdk_name", help="e.g. azure-mgmt-frontdoor")
    parser.add_argument("tag", help="swagger python_tag, e.g. package-2024-05")
    parser.add_argument(
        "--release-type",
        choices=["stable", "beta"],
        default="stable",
        help="sdkReleaseType value to write into generate_input_swagger.json (default: stable)",
    )
    parser.add_argument("--work-dir", default="C:/dev", type=Path)
    args = parser.parse_args()

    work = args.work_dir.resolve()
    sdk_name = args.sdk_name
    tag = args.tag
    release_type = args.release_type

    print(f"=== regen {sdk_name} (tag={tag}, release_type={release_type}) ===")

    # 1. pre-flight
    spec_repo, sdk_repo = check_repos(work)
    venv = check_venv(sdk_repo)

    # 2. find readme.md (before sync is fine; we re-find after sync for freshness)
    # 3. sync repos
    print("--- syncing azure-rest-api-specs ---")
    head_sha = clean_and_sync(spec_repo)
    print(f"head_sha={head_sha}")

    print("--- syncing azure-sdk-for-python ---")
    clean_and_sync(sdk_repo)

    # 2b. find readme.md against the freshly-synced spec repo
    readme_path = find_readme(spec_repo, sdk_name)
    print(f"readme_path={readme_path}")

    # 4. write input json
    input_json = write_input_json(venv, head_sha, tag, readme_path, release_type)
    print(f"wrote {input_json}")

    # 5. install tooling + run generator inside venv
    print("--- installing azure-sdk-tools[ghtools] in .venv ---")
    install_and_generate(sdk_repo, venv, input_json)

    # 6. bump version + rewrite changelog (skipped for beta releases)
    pkg_dir = locate_package(sdk_repo, sdk_name)
    if release_type == "beta":
        old = new = ""
        print("release_type=beta: skipping version bump and changelog rewrite")
    else:
        version_file = find_version_file(pkg_dir)
        changelog = pkg_dir / "CHANGELOG.md"
        if not changelog.is_file():
            raise FileNotFoundError(f"CHANGELOG.md not found at {changelog}")
        old, new = bump_version_file(version_file)
        rewrite_changelog(changelog, new)
        print(f"version: {old} -> {new}")

    # 6b. ensure aiohttp in dev_requirements.txt
    if ensure_aiohttp_in_dev_requirements(pkg_dir):
        print("added aiohttp to dev_requirements.txt")
    else:
        print("aiohttp already in dev_requirements.txt")

    # 7. push & create PR
    branch, pr_url = push_and_create_pr(sdk_repo, sdk_name)

    print()
    print("=== SESSION_STATE ===")
    print(f"sdk_name={sdk_name}")
    print(f"tag={tag}")
    print(f"head_sha={head_sha}")
    print(f"readme_path={readme_path}")
    print(f"pkg_dir={pkg_dir.as_posix()}")
    print(f"version_old={old}")
    print(f"version_new={new}")
    print(f"branch={branch}")
    print(f"pr_url={pr_url}")
    print("=== END_SESSION_STATE ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
