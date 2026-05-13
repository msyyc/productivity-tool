"""Find api-version for an Azure SDK Python package.

Usage:
    python find_api_version.py <package-name> <version>

<version> may be:
    - an explicit version string like "1.0.0b1" or "1.2.3"
    - "latest" / "latest-stable" -> latest stable release on PyPI
    - "latest-preview" / "preview" -> latest preview (pre-release) on PyPI

Outputs a `=== SUMMARY ===` block at the end with:
    - api_versions (comma separated, or "NOT_FOUND")
    - source_dir (extracted package source folder, for `code <path>`)
    - readme_paths (one per line, or "NOT_FOUND")
    - readme_urls (folder-level GitHub URLs, one per line)

The whole flow is run in-process to be as fast as possible.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from urllib.request import urlopen

SPEC_REPO_LOCAL = Path("C:/dev/azure-rest-api-specs")
SPEC_REPO_REMOTE = "https://github.com/Azure/azure-rest-api-specs/tree/main"
TEMP_ROOT = Path("temp")


def log(msg: str) -> None:
    print(msg, flush=True)


def resolve_version(package: str, version: str) -> str:
    """Resolve `latest` / `latest-preview` against PyPI; otherwise return as-is."""
    v = version.lower().strip()
    if v not in {"latest", "latest-stable", "stable", "latest-preview", "preview"}:
        return version
    want_preview = v in {"latest-preview", "preview"}
    log(f"Querying PyPI for {package} ({'latest preview' if want_preview else 'latest stable'})...")
    with urlopen(f"https://pypi.org/pypi/{package}/json", timeout=30) as r:
        data = json.loads(r.read())
    releases = data.get("releases", {})
    # Sort by upload time descending using the first file's upload_time per version.
    candidates = []
    for ver, files in releases.items():
        if not files:
            continue
        is_pre = bool(re.search(r"[a-zA-Z]", ver))  # 1.0.0b1, 1.0.0rc1, 1.0.0a1, etc.
        if want_preview and not is_pre:
            continue
        if not want_preview and is_pre:
            continue
        upload = files[0].get("upload_time_iso_8601") or files[0].get("upload_time") or ""
        candidates.append((upload, ver))
    if not candidates:
        raise SystemExit(f"No matching {'preview' if want_preview else 'stable'} version on PyPI for {package}")
    candidates.sort(reverse=True)
    resolved = candidates[0][1]
    log(f"Resolved version: {resolved}")
    return resolved


def pip_download(package: str, version: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    log(f"Downloading {package}=={version} into {dest}...")
    cmd = [
        sys.executable, "-m", "pip", "download",
        f"{package}=={version}",
        "--no-deps", "--no-binary=:none:",
        "--dest", str(dest),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # Retry allowing wheels (some packages publish only wheels).
        cmd = [
            sys.executable, "-m", "pip", "download",
            f"{package}=={version}",
            "--no-deps",
            "--dest", str(dest),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            log(res.stdout)
            log(res.stderr)
            raise SystemExit(f"pip download failed for {package}=={version}")
    files = list(dest.iterdir())
    if not files:
        raise SystemExit("pip download produced no files")
    # Prefer sdist over wheel for clean source layout.
    sdist = next((f for f in files if f.suffix in {".gz", ".zip"} and f.name.endswith((".tar.gz", ".zip"))), None)
    return sdist or files[0]


def extract(archive: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    log(f"Extracting {archive.name}...")
    if archive.name.endswith(".tar.gz") or archive.name.endswith(".tgz"):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest)
    elif archive.suffix == ".zip" or archive.name.endswith(".whl"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    else:
        raise SystemExit(f"Unknown archive type: {archive}")
    # Find the top-level extracted folder for sdist; for wheel the package folder is the SDK name.
    children = [p for p in dest.iterdir() if p.is_dir()]
    if not children:
        return dest
    return children[0]


def find_api_versions(source_root: Path) -> tuple[set[str], Path | None]:
    """Scan _configuration.py and *_client.py for api_version strings.

    Returns (api_versions, deepest_package_dir_used_for_code_command).
    """
    versions: set[str] = set()
    skip = re.compile(r"[\\/](tests|samples|build|dist|\.tox|\.eggs)[\\/]", re.IGNORECASE)

    # Primary scan targets per spec.
    primary: list[Path] = []
    primary += list(source_root.rglob("_configuration.py"))
    primary += list(source_root.rglob("*_client.py"))
    primary = [c for c in primary if not skip.search(str(c))]

    # Match a date-like api-version literal anywhere on a line that mentions api_version/api-version.
    date_pat = re.compile(r"""["'](\d{4}-\d{2}-\d{2}(?:-preview)?)["']""")

    def scan(path: Path) -> set[str]:
        out: set[str] = set()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return out
        for line in text.splitlines():
            low = line.lower()
            if "api_version" in low or "api-version" in low:
                out |= set(date_pat.findall(line))
        return out

    for f in primary:
        versions |= scan(f)

    # Fallback: multiapi-style packages keep api-version in operation files instead.
    if not versions:
        for f in source_root.rglob("*.py"):
            if skip.search(str(f)):
                continue
            versions |= scan(f)

    # Choose source dir for `code` command: prefer the dir containing a _configuration.py.
    src_dir: Path | None = None
    cfg = next((c for c in primary if c.name == "_configuration.py"), None)
    if cfg:
        src_dir = cfg.parent
    return versions, src_dir or source_root


def search_readmes(package: str) -> list[Path]:
    matches: list[Path] = []
    if not SPEC_REPO_LOCAL.exists():
        log(f"WARNING: spec repo not found at {SPEC_REPO_LOCAL}")
        return matches
    spec_dir = SPEC_REPO_LOCAL / "specification"
    root = spec_dir if spec_dir.exists() else SPEC_REPO_LOCAL
    log(f"Searching readme.python.md under {root}...")
    for readme in root.rglob("readme.python.md"):
        try:
            text = readme.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if package in text:
            matches.append(readme)
    return matches


def to_remote_folder_url(local_readme: Path) -> str:
    rel = local_readme.relative_to(SPEC_REPO_LOCAL).as_posix()
    folder = rel.rsplit("/", 1)[0]  # drop "readme.python.md"
    return f"{SPEC_REPO_REMOTE}/{folder}"


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python find_api_version.py <package-name> <version>")
        return 2
    package = sys.argv[1].strip()
    version = sys.argv[2].strip()

    resolved_version = resolve_version(package, version)

    work_root = TEMP_ROOT / f"{package}-{resolved_version}"
    if work_root.exists():
        shutil.rmtree(work_root, ignore_errors=True)
    download_dir = work_root / "download"
    extract_dir = work_root / "extracted"

    archive = pip_download(package, resolved_version, download_dir)
    src_root = extract(archive, extract_dir)

    api_versions, code_dir = find_api_versions(src_root)
    readmes = search_readmes(package)

    print()
    print("=== SUMMARY ===")
    print(f"package: {package}")
    print(f"version: {resolved_version}")
    if api_versions:
        print(f"api_versions: {','.join(sorted(api_versions))}")
    else:
        print("api_versions: NOT_FOUND")
    print(f"source_dir: {code_dir.resolve()}")
    if readmes:
        print("readme_paths:")
        for r in readmes:
            print(f"  - {r}")
        print("readme_urls:")
        for r in readmes:
            print(f"  - {to_remote_folder_url(r)}")
    else:
        print("readme_paths: NOT_FOUND")
        print("readme_urls: NOT_FOUND")
    print("=== END SUMMARY ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
