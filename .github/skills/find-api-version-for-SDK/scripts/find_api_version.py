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

SPEC_REPO_REMOTE = "https://github.com/Azure/azure-rest-api-specs/tree/main"


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file."""
    env_vars: dict[str, str] = {}
    try:
        with env_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip().strip("\"'")
    except OSError:
        pass
    return env_vars


def _resolve_repo_paths() -> tuple[Path, Path]:
    """Resolve (spec_repo, sdk_repo) local paths.

    Order:
      1. `.env` at the productivity-tool repo root with `LOCAL_AZURE_SPEC_REPO`
         and/or `LOCAL_AZURE_SDK_REPO`.
      2. Default to `C:/dev/azure-rest-api-specs` and `C:/dev/azure-sdk-for-python`.
    """
    # scripts → find-api-version-for-SDK → skills → .github → repo root
    repo_root = Path(__file__).resolve().parents[4]
    env_vars = _read_env_file(repo_root / ".env") if (repo_root / ".env").is_file() else {}
    spec_val = env_vars.get("LOCAL_AZURE_SPEC_REPO")
    sdk_val = env_vars.get("LOCAL_AZURE_SDK_REPO")
    spec_repo = Path(spec_val) if spec_val else Path("C:/dev/azure-rest-api-specs")
    sdk_repo = Path(sdk_val) if sdk_val else Path("C:/dev/azure-sdk-for-python")
    return spec_repo, sdk_repo


SPEC_REPO_LOCAL, SDK_REPO_LOCAL = _resolve_repo_paths()
TEMP_ROOT = Path("temp")


def log(msg: str) -> None:
    print(msg, flush=True)


def _fetch_pypi_json(package: str) -> dict:
    with urlopen(f"https://pypi.org/pypi/{package}/json", timeout=30) as r:
        return json.loads(r.read())


def resolve_version(package: str, version: str, pypi_data: dict | None = None) -> str:
    """Resolve `latest` / `latest-preview` against PyPI; otherwise return as-is."""
    v = version.lower().strip()
    if v not in {"latest", "latest-stable", "stable", "latest-preview", "preview"}:
        return version
    want_preview = v in {"latest-preview", "preview"}
    log(f"Querying PyPI for {package} ({'latest preview' if want_preview else 'latest stable'})...")
    data = pypi_data if pypi_data is not None else _fetch_pypi_json(package)
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


def download_sdist(package: str, version: str, dest: Path, pypi_data: dict | None = None) -> Path:
    """Download the sdist (.tar.gz / .zip) for the given version directly from PyPI.

    Bypasses `pip download` entirely to avoid PEP 517 metadata preparation overhead
    (which spins up an isolated build env even with --no-deps).
    """
    dest.mkdir(parents=True, exist_ok=True)
    data = pypi_data if pypi_data is not None else _fetch_pypi_json(package)
    files = data.get("releases", {}).get(version)
    if not files:
        raise SystemExit(f"Version {version} not found on PyPI for {package}")
    sdist_meta = next(
        (
            f
            for f in files
            if f.get("packagetype") == "sdist" or f.get("filename", "").endswith((".tar.gz", ".tgz", ".zip"))
        ),
        None,
    )
    if not sdist_meta:
        raise SystemExit(f"No sdist (.tar.gz/.zip) published on PyPI for {package}=={version}.")
    url = sdist_meta["url"]
    out = dest / sdist_meta["filename"]
    log(f"Downloading sdist {sdist_meta['filename']} from PyPI...")
    with urlopen(url, timeout=60) as r, open(out, "wb") as fh:
        shutil.copyfileobj(r, fh)
    return out


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


def _sync_spec_repo() -> None:
    """Reset and fast-forward the local spec repo to origin/main before searching."""
    cmd = (
        "git reset HEAD && git checkout . && git clean -fd && "
        "git fetch origin main && git checkout origin/main && git pull origin main"
    )
    log(f"$ ({SPEC_REPO_LOCAL}) {cmd}")
    proc = subprocess.run(
        cmd,
        cwd=str(SPEC_REPO_LOCAL),
        capture_output=True,
        text=True,
        shell=True,
    )
    if proc.stdout:
        log(proc.stdout.rstrip())
    if proc.returncode != 0:
        log(f"WARNING: spec repo sync failed (exit {proc.returncode})")
        if proc.stderr:
            log(proc.stderr.rstrip())


def search_readmes(package: str) -> list[Path]:
    matches: list[Path] = []
    if not SPEC_REPO_LOCAL.exists():
        log(f"WARNING: spec repo not found at {SPEC_REPO_LOCAL}")
        return matches
    _sync_spec_repo()
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


def check_deprecation(package: str) -> tuple[str, str | None, str | None, str | None]:
    """Locate the local SDK package and return its README/CHANGELOG for agent judgement.

    The script intentionally does NOT perform keyword-based deprecation detection
    (keyword matching produced too many false positives, e.g. "credentials are
    no longer supported" in a generic CHANGELOG line). Instead, it surfaces the
    raw README.md content and the latest CHANGELOG.md section so the calling
    agent can read them and decide.

    Returns a 4-tuple ``(status, readme_text, latest_changelog_section, sdk_repo_url)``:
        - status:
            * ``"needs_judgement"``  files were found; agent should inspect the
              README/CHANGELOG blocks emitted in the summary.
            * ``"files_missing"``    package dir, README.md or CHANGELOG.md not found.
        - readme_text: full README.md contents, or ``None``.
        - latest_changelog_section: the first version section of CHANGELOG.md
          (heading line plus body up to the next heading), or ``None``.
        - sdk_repo_url: GitHub URL of the package folder under
          ``Azure/azure-sdk-for-python/tree/main/sdk/<service>/<package>``, or
          ``None`` when the local package folder could not be located.
    """
    sdk_dir = SDK_REPO_LOCAL / "sdk"
    if not sdk_dir.exists():
        log(f"WARNING: SDK repo not found at {SDK_REPO_LOCAL}")
        return "files_missing", None, None, None
    # Package folder lives at sdk/<service>/<package>/.
    candidates = list(sdk_dir.glob(f"*/{package}"))
    if not candidates:
        return "files_missing", None, None, None
    pkg_dir = candidates[0]
    sdk_repo_url = (
        "https://github.com/Azure/azure-sdk-for-python/tree/main/" f"sdk/{pkg_dir.parent.name}/{pkg_dir.name}"
    )
    readme = pkg_dir / "README.md"
    changelog = pkg_dir / "CHANGELOG.md"
    if not readme.exists() or not changelog.exists():
        return "files_missing", None, None, sdk_repo_url

    try:
        readme_text = readme.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        readme_text = ""
    try:
        changelog_text = changelog.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        changelog_text = ""

    # Extract the latest section of CHANGELOG.md: from the first version heading
    # (## ...) up to the next heading at the same level, or EOF.
    latest_section: str | None = None
    m = re.search(r"^##\s+.+?(?=^##\s+|\Z)", changelog_text, re.MULTILINE | re.DOTALL)
    if m:
        latest_section = m.group(0).rstrip()

    return "needs_judgement", readme_text or None, latest_section, sdk_repo_url


def parse_meta_json(source_root: Path) -> tuple[str | None, str | None]:
    """Look for _meta.json in extracted sources and extract old readme link + autorest tag.

    Returns (readme_url, tag) where each is None if missing.
    """
    meta_path = next(source_root.rglob("_meta.json"), None)
    if not meta_path:
        return None, None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None, None

    commit = meta.get("commit")
    readme = meta.get("readme")
    readme_url: str | None = None
    if commit and readme:
        # readme value is like "specification/<svc>/resource-manager/readme.md".
        readme_clean = readme.replace("\\", "/").lstrip("/")
        readme_url = f"https://github.com/Azure/azure-rest-api-specs/blob/{commit}/{readme_clean}"

    tag: str | None = None
    autorest_cmd = meta.get("autorest_command") or ""
    m = re.search(r"--tag[=\s]+([^\s\"']+)", autorest_cmd)
    if m:
        tag = m.group(1)

    return readme_url, tag


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python find_api_version.py <package-name> <version>")
        return 2
    package = sys.argv[1].strip()
    version = sys.argv[2].strip()

    # Fetch PyPI metadata once and reuse for both version resolution and sdist URL.
    pypi_data = _fetch_pypi_json(package)
    resolved_version = resolve_version(package, version, pypi_data=pypi_data)

    work_root = TEMP_ROOT / f"{package}-{resolved_version}"
    if work_root.exists():
        shutil.rmtree(work_root, ignore_errors=True)
    download_dir = work_root / "download"
    extract_dir = work_root / "extracted"

    archive = download_sdist(package, resolved_version, download_dir, pypi_data=pypi_data)
    src_root = extract(archive, extract_dir)

    api_versions, _ = find_api_versions(src_root)
    # Per skill spec: source_dir is the top-level extracted folder (sdist root),
    # not the deep azure/mgmt/<svc> package directory.
    code_dir = src_root
    readmes = search_readmes(package)
    old_readme_link, old_tag = parse_meta_json(src_root)
    deprecation_status, readme_text, latest_changelog, sdk_repo_url = check_deprecation(package)

    print()
    print("=== SUMMARY ===")
    print(f"package: {package}")
    print(f"version: {resolved_version}")
    print(f"pypi_history_url: https://pypi.org/project/{package}/#history")
    if deprecation_status == "files_missing":
        print("deprecation: WARNING: README.md/CHANGELOG.md not found !!!")
    else:
        print("deprecation: NEEDS_JUDGEMENT")
    print(f"sdk_repo_url: {sdk_repo_url if sdk_repo_url else 'NOT_FOUND'}")
    if api_versions:
        print(f"api_versions: {','.join(sorted(api_versions))}")
    else:
        print("api_versions: NOT_FOUND")
    print(f"source_dir: {code_dir.resolve()}")
    print(f"old readme link: {old_readme_link if old_readme_link else 'not found'}")
    print(f"old tag: {old_tag if old_tag else 'not found'}")
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
    # Always emit the SDK repo README and the latest CHANGELOG section (when
    # available) so the agent can do an additional deprecation/maintenance
    # judgement beyond the keyword-based check above.
    if readme_text is not None:
        print("--- BEGIN SDK README.md ---")
        print(readme_text.rstrip())
        print("--- END SDK README.md ---")
    else:
        print("sdk_readme: NOT_AVAILABLE")
    if latest_changelog is not None:
        print("--- BEGIN SDK CHANGELOG.md (latest section) ---")
        print(latest_changelog)
        print("--- END SDK CHANGELOG.md (latest section) ---")
    else:
        print("sdk_changelog_latest: NOT_AVAILABLE")
    print("=== END SUMMARY ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
