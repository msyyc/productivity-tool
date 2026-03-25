"""
Run live tests for an Azure SDK for Python management package.

This script is part of the create-sdk-release-pr skill and implements Step 7:
locate the SDK package directory in a worktree, copy and transform generated
tests, set up a virtual environment, install dependencies, run pytest, and
format the output.

Usage:
    # Phase 1 — prepare tests only (copy/transform, then stop for review):
    python run_live_tests.py <package-name> --worktree-dir <path> --work-dir <path> --prepare-only

    # Phase 2 — full run (venv setup, install deps, pytest, format):
    python run_live_tests.py <package-name> --worktree-dir <path> --work-dir <path>

Example:
    python run_live_tests.py azure-mgmt-containerregistry --worktree-dir C:/dev/worktrees/sdk-azure-mgmt-containerregistry --work-dir C:/dev
    python run_live_tests.py azure-mgmt-containerregistry --worktree-dir C:/dev/worktrees/sdk-azure-mgmt-containerregistry --work-dir C:/dev --prepare-only
"""

import argparse
import glob as glob_mod
import os
import pathlib
import re
import subprocess
import sys


def log(msg):
    print(f"[live_test] {msg}")


def die(msg):
    print(f"[live_test][error] {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Locate SDK directory
# ---------------------------------------------------------------------------


def find_sdk_dir(worktree_dir, package_name):
    """Find the SDK package directory under <worktree>/sdk/."""
    sdk_root = os.path.join(worktree_dir, "sdk")
    if not os.path.isdir(sdk_root):
        die(f"sdk/ directory not found at {sdk_root}")

    for parent in os.listdir(sdk_root):
        candidate = os.path.join(sdk_root, parent, package_name)
        if os.path.isdir(candidate):
            return candidate

    die(f"Package directory for '{package_name}' not found under {sdk_root}")


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def get_sdk_version(changelog_path):
    """Extract the first version from CHANGELOG.md (e.g. '1.0.0b1')."""
    if not os.path.isfile(changelog_path):
        return None
    with open(changelog_path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^##\s+(\d+\.\S+)", line)
            if m:
                return m.group(1)
    return None


def get_pyproject_title(pyproject_path):
    """Extract the title field from pyproject.toml."""
    if not os.path.isfile(pyproject_path):
        return None
    with open(pyproject_path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r'^title\s*=\s*"(.+?)"', line)
            if m:
                return m.group(1)
    return None


def preflight_check(sdk_dir):
    """For 1.0.0b1 packages, validate that pyproject title contains 'Mgmt'."""
    changelog_path = os.path.join(sdk_dir, "CHANGELOG.md")
    pyproject_path = os.path.join(sdk_dir, "pyproject.toml")

    version = get_sdk_version(changelog_path)
    if version != "1.0.0b1":
        return

    title = get_pyproject_title(pyproject_path)
    if title is None:
        die("SDK version is 1.0.0b1 but pyproject.toml not found or has no title.")

    if "Mgmt" not in title:
        die(
            f"SDK version is 1.0.0b1 but pyproject.toml title ('{title}') does not "
            "contain 'Mgmt'. Please update pyproject.toml before running live tests."
        )

    log(f"Pre-flight: version is 1.0.0b1, title ('{title}') contains 'Mgmt'.")


# ---------------------------------------------------------------------------
# Test file transformation
# ---------------------------------------------------------------------------


def transform_test_content(text):
    """Apply all transformations to a generated test file."""
    # @pytest.mark.skip -> @pytest.mark.live_test_only
    text = re.sub(
        r"^(\s*)@pytest\.mark\.skip.*$",
        r"\1@pytest.mark.live_test_only",
        text,
        flags=re.MULTILINE,
    )

    # "# please add some check logic here by yourself" -> assert result == []
    text = re.sub(
        r"^(?P<indent>\s*)# please add some check logic here by yourself\s*(?:\r?\n)",
        lambda m: f"{m.group('indent')}assert result == []\n",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # Remove "# ..." comment lines
    text = text.replace("# ...\n", "")

    # Strip api_version= from list*() calls
    text = re.sub(
        r"(?P<prefix>(?:[A-Za-z_][\w.]*\.)?list[\w]*)\(\s*api_version\s*=\s*[^,)]*(?:,\s*)?\s*\)",
        lambda m: f"{m.group('prefix')}()",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    return text


def copy_and_transform_tests(sdk_dir):
    """Copy generated tests to tests/ with transformations. Returns list of created files."""
    gen_dir = os.path.join(sdk_dir, "generated_tests")
    tests_dir = os.path.join(sdk_dir, "tests")

    # Skip if *_test.py files already exist
    existing = glob_mod.glob(os.path.join(tests_dir, "**", "*_test.py"), recursive=True)
    if existing:
        log(f"Existing *_test.py files found in {tests_dir}, skipping generated tests copy.")
        return []

    if not os.path.isdir(gen_dir):
        die(f"generated_tests/ directory not found at {gen_dir}")

    updated_files = []

    # Process conftest.py first
    conftest_src = os.path.join(gen_dir, "conftest.py")
    if os.path.isfile(conftest_src):
        conftest_dest = os.path.join(tests_dir, "conftest.py")
        _process_file(conftest_src, conftest_dest)
        updated_files.append(conftest_dest)

    # Find all .py files except conftest.py
    sources = sorted(p for p in pathlib.Path(gen_dir).rglob("*.py") if p.name != "conftest.py")

    if not sources:
        die(f"No generated test files found in {gen_dir}")

    copied = 0
    for src_file in sources:
        # Only copy files that contain "list" (case-insensitive)
        content = src_file.read_text(encoding="utf-8")
        if not re.search(r"list", content, re.IGNORECASE):
            continue

        rel_path = src_file.relative_to(gen_dir)
        base_no_ext = rel_path.stem
        parent = rel_path.parent

        if parent == pathlib.Path("."):
            dest_rel = f"{base_no_ext}_test.py"
        else:
            dest_rel = str(parent / f"{base_no_ext}_test.py")

        dest_file = os.path.join(tests_dir, dest_rel)
        _process_file(str(src_file), dest_file)
        updated_files.append(dest_file)
        copied += 1

    if copied == 0:
        die("No generated tests contained list* method instances.")

    return updated_files


def _process_file(src, dest):
    """Read src, transform, write to dest."""
    text = pathlib.Path(src).read_text(encoding="utf-8")
    text = transform_test_content(text)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    pathlib.Path(dest).write_text(text, encoding="utf-8")
    log(f"Processed: {os.path.basename(dest)}")


# ---------------------------------------------------------------------------
# Virtual environment setup
# ---------------------------------------------------------------------------


def get_python_executable():
    """Get the python executable name (python or python3)."""
    # On Windows, python3 may not exist
    if sys.platform == "win32":
        return "python"
    return "python3"


def setup_venv(worktree_dir):
    """Set up or reuse .venv at worktree root. Returns path to venv python."""
    venv_path = os.path.join(worktree_dir, ".venv")

    if sys.platform == "win32":
        venv_python = os.path.join(venv_path, "Scripts", "python.exe")
        venv_pip = os.path.join(venv_path, "Scripts", "pip.exe")
    else:
        venv_python = os.path.join(venv_path, "bin", "python")
        venv_pip = os.path.join(venv_path, "bin", "pip")

    if os.path.isfile(venv_python):
        log(f"Reusing existing virtual environment at {venv_path}")
    else:
        log(f"Creating virtual environment at {venv_path}")
        python_exe = get_python_executable()
        subprocess.run([python_exe, "-m", "venv", venv_path], check=True)

        # Install azure-sdk-tools
        eng_tools = os.path.join(worktree_dir, "eng", "tools", "azure-sdk-tools")
        if os.path.isdir(eng_tools):
            log("Installing azure-sdk-tools[ghtools,sdkgenerator]...")
            subprocess.run(
                [venv_pip, "install", f"{eng_tools}[ghtools,sdkgenerator]"],
                check=True,
            )
        else:
            log(f"Warning: eng/tools/azure-sdk-tools not found at {eng_tools}, skipping.")

    return venv_python, venv_pip


# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------


def load_env_file(work_dir):
    """Load environment variables from <work_dir>/.env."""
    env_path = os.path.join(work_dir, ".env")
    if not os.path.isfile(env_path):
        die(
            f".env file not found at {env_path}. "
            "Please create it with the required environment variables:\n"
            "  AZURE_TEST_RUN_LIVE=true\n"
            "  AZURE_TEST_USE_CLI_AUTH=true\n"
            "  AZURE_SKIP_LIVE_RECORDING=true\n"
            "  AZURE_TENANT_ID=<your-tenant-id>\n"
            "  AZURE_SUBSCRIPTION_ID=<your-subscription-id>"
        )

    env_vars = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                env_vars[key] = value

    log(f"Loaded {len(env_vars)} variable(s) from {env_path}")
    return env_vars


# ---------------------------------------------------------------------------
# Install deps, run tests, format
# ---------------------------------------------------------------------------


def ensure_test_deps_in_dev_requirements(sdk_dir):
    """Append azure-identity and aiohttp to dev_requirements.txt if missing."""
    dev_req = os.path.join(sdk_dir, "dev_requirements.txt")
    if not os.path.isfile(dev_req):
        return

    content = pathlib.Path(dev_req).read_text(encoding="utf-8")
    lines = content.splitlines()
    # Normalize for comparison: strip whitespace, ignore comments/blanks
    existing = {l.strip().lower() for l in lines if l.strip() and not l.strip().startswith("#")}

    to_add = []
    for dep in ["azure-identity", "aiohttp"]:
        if not any(dep in entry for entry in existing):
            to_add.append(dep)

    if to_add:
        log(f"Adding missing test deps to dev_requirements.txt: {', '.join(to_add)}")
        with open(dev_req, "a", encoding="utf-8") as f:
            for dep in to_add:
                f.write(f"\n{dep}")


def install_deps(venv_pip, sdk_dir):
    """Install dev requirements and package in editable mode."""
    ensure_test_deps_in_dev_requirements(sdk_dir)

    dev_req = os.path.join(sdk_dir, "dev_requirements.txt")
    if os.path.isfile(dev_req):
        log("Installing dev_requirements.txt...")
        subprocess.run([venv_pip, "install", "-r", dev_req], cwd=sdk_dir, check=True)
    else:
        log("Warning: dev_requirements.txt not found, skipping.")

    log("Installing package in editable mode...")
    subprocess.run([venv_pip, "install", "-e", sdk_dir], check=True)


def run_pytest(venv_python, sdk_dir, env_vars):
    """Run pytest on the tests/ directory. Returns (passed, summary_md)."""
    tests_dir = os.path.join(sdk_dir, "tests")
    env = os.environ.copy()
    env.update(env_vars)

    log("Running pytest...")
    result = subprocess.run(
        [venv_python, "-m", "pytest", tests_dir, "-v"],
        cwd=sdk_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    full_output = stdout + "\n" + stderr

    # Always print output so the caller can see it
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)

    passed = result.returncode == 0
    summary_md = _build_test_summary(full_output, passed)

    if not passed:
        log("Pytest failed; continuing script execution.")
    else:
        log("Pytest passed.")

    return passed, summary_md


def _build_test_summary(output, passed):
    """Build a markdown summary of pytest results with failure root causes."""
    lines = output.splitlines()

    # Extract the pytest summary line (e.g., "= 3 passed, 1 failed in 5.23s =")
    summary_line = ""
    for line in reversed(lines):
        if re.search(r"\d+\s+(passed|failed|error)", line):
            summary_line = line.strip().strip("=").strip()
            break

    status_emoji = "✅" if passed else "❌"
    parts = [f"## {status_emoji} Live Test Results\n"]
    if summary_line:
        parts.append(f"**Summary:** {summary_line}\n")

    if not passed:
        failures = _extract_failures(lines)
        if failures:
            parts.append("### Failed Tests\n")
            for name, root_cause in failures:
                parts.append(f"#### `{name}`\n")
                parts.append(f"```\n{root_cause}\n```\n")

    return "\n".join(parts)


def _extract_failures(lines):
    """Extract failed test names and their root cause from pytest output.

    Returns a list of (test_name, root_cause) tuples.
    """
    failures = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect FAILED header: "_ _ _ test_name _ _ _" or "FAILED test_name"
        header_match = re.match(r"^_{3,}\s+(.+?)\s+_{3,}$", line)
        if header_match:
            test_name = header_match.group(1)
            # Collect the failure block until the next separator or short summary
            block_lines = []
            i += 1
            while i < len(lines):
                if re.match(r"^(_{3,}|={3,})\s", lines[i]):
                    break
                block_lines.append(lines[i])
                i += 1
            root_cause = _extract_root_cause(block_lines)
            failures.append((test_name, root_cause))
            continue

        # Also catch the short summary line: "FAILED tests/foo_test.py::test_bar - Error..."
        short_match = re.match(r"^FAILED\s+(\S+?)(?:\s+-\s+(.+))?$", line)
        if short_match:
            test_name = short_match.group(1)
            # Only add if we didn't already capture this test from a full block
            if not any(test_name in n for n, _ in failures):
                error_hint = short_match.group(2) or ""
                failures.append((test_name, error_hint))

        i += 1

    return failures


def _extract_root_cause(block_lines):
    """Extract the root cause from a failure block.

    Looks for the last exception/error message and the most relevant traceback
    lines (the final raise + error line).
    """
    if not block_lines:
        return "(no details captured)"

    # Find lines starting with "E " (pytest error annotation) — these are the root cause
    error_lines = [l for l in block_lines if re.match(r"^E\s+", l)]
    if error_lines:
        # Include the last few context lines before the first E line for traceback
        first_e_idx = next(i for i, l in enumerate(block_lines) if re.match(r"^E\s+", l))
        # Grab up to 3 lines of traceback context before the E lines
        context_start = max(0, first_e_idx - 3)
        context = block_lines[context_start:first_e_idx]
        # Filter context to only file/line references
        context = [l for l in context if re.search(r"\.py:\d+", l) or l.strip().startswith(">")]
        return "\n".join(context + error_lines).strip()

    # Fallback: return last 10 non-empty lines
    tail = [l for l in block_lines if l.strip()][-10:]
    return "\n".join(tail).strip() if tail else "(no details captured)"


def run_black_formatting(venv_python, sdk_dir):
    """Run black on generated_tests/, generated_samples/, and tests/ directories."""
    targets = []
    for dirname in ("generated_tests", "generated_samples", "tests"):
        dirpath = os.path.join(sdk_dir, dirname)
        if os.path.isdir(dirpath):
            targets.append(dirpath)

    if not targets:
        log("No directories to format.")
        return

    log(f"Running black on: {', '.join(os.path.basename(t) for t in targets)}")
    subprocess.run(
        [venv_python, "-m", "black", "-l", "120"] + targets,
        cwd=sdk_dir,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Run live tests for an Azure SDK package")
    parser.add_argument("package_name", help="SDK package name (e.g. azure-mgmt-containerregistry)")
    parser.add_argument("--worktree-dir", required=True, help="Path to the git worktree root")
    parser.add_argument("--work-dir", required=True, help="Path to the work folder (e.g. C:/dev)")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Only copy and transform tests, then exit for review",
    )
    args = parser.parse_args()

    worktree_dir = os.path.abspath(args.worktree_dir)
    work_dir = os.path.abspath(args.work_dir)

    # --- Locate SDK directory ---
    sdk_dir = find_sdk_dir(worktree_dir, args.package_name)
    log(f"SDK directory: {sdk_dir}")

    # --- Pre-flight check ---
    preflight_check(sdk_dir)

    # --- Copy and transform tests ---
    updated_files = copy_and_transform_tests(sdk_dir)

    if updated_files:
        log("Updated files:")
        for f in updated_files:
            print(f"  - {f}")

    # --- Output session state ---
    print("\n=== SESSION_STATE ===")
    print(f"sdk_dir={sdk_dir}")
    print(f"files_updated={len(updated_files)}")
    print("=====================")

    if args.prepare_only:
        log("Prepare-only mode: stopping for review.")
        return

    # --- Full run: venv, deps, tests, format ---

    # Load .env
    env_vars = load_env_file(work_dir)

    # Setup venv
    venv_python, venv_pip = setup_venv(worktree_dir)

    # Install dependencies
    install_deps(venv_pip, sdk_dir)

    # Run pytest
    test_passed, summary_md = run_pytest(venv_python, sdk_dir, env_vars)

    # Write test summary to a temp file for PR commenting (inside SDK dir, excluded from git add)
    summary_path = os.path.join(sdk_dir, ".test_summary.md")
    pathlib.Path(summary_path).write_text(summary_md, encoding="utf-8")
    log(f"Test summary written to {summary_path}")

    # Format
    run_black_formatting(venv_python, sdk_dir)

    # --- Output final session state ---
    print("\n=== SESSION_STATE ===")
    print(f"sdk_dir={sdk_dir}")
    print(f"files_updated={len(updated_files)}")
    print(f"test_result={'passed' if test_passed else 'failed'}")
    print(f"test_summary_path={summary_path}")
    print("=====================")

    log("Done.")


if __name__ == "__main__":
    main()
