"""Tests for generate_typespec_sdk.py"""

import os
import tempfile

import pytest

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generate_typespec_sdk import (
    extract_versions_from_main_tsp,
    resolve_api_version,
    strip_mgmt_prefix,
)


# ---------------------------------------------------------------------------
# strip_mgmt_prefix
# ---------------------------------------------------------------------------
class TestStripMgmtPrefix:
    def test_strips_azure_mgmt(self):
        assert strip_mgmt_prefix("azure-mgmt-securityinsights") == "securityinsights"

    def test_strips_azure(self):
        assert strip_mgmt_prefix("azure-storage-blob") == "storage-blob"

    def test_no_prefix(self):
        assert strip_mgmt_prefix("somepackage") == "somepackage"

    def test_case_insensitive(self):
        assert strip_mgmt_prefix("Azure-Mgmt-Compute") == "compute"

    def test_azure_mgmt_takes_priority(self):
        assert strip_mgmt_prefix("azure-mgmt-network") == "network"

    def test_empty_after_prefix(self):
        assert strip_mgmt_prefix("azure-mgmt-") == ""

    def test_empty_string(self):
        assert strip_mgmt_prefix("") == ""


# ---------------------------------------------------------------------------
# extract_versions_from_main_tsp
# ---------------------------------------------------------------------------
class TestExtractVersionsFromMainTsp:
    def _write_main_tsp(self, tmpdir, spec_folder, content):
        full_dir = os.path.join(tmpdir, spec_folder)
        os.makedirs(full_dir, exist_ok=True)
        with open(os.path.join(full_dir, "main.tsp"), "w") as f:
            f.write(content)

    def test_single_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_main_tsp(
                tmpdir,
                "spec/svc",
                """
import "@typespec/versioning";

enum Versions {
  /** The 2025-09-01 API version. */
  v2025_09_01: "2025-09-01",
}
""",
            )
            result = extract_versions_from_main_tsp("spec/svc", tmpdir)
            assert result == ["2025-09-01"]

    def test_multiple_versions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_main_tsp(
                tmpdir,
                "spec/svc",
                """
enum Versions {
  v2025_10_01: "2025-10-01",
  v2025_11_01: "2025-11-01",
}
""",
            )
            result = extract_versions_from_main_tsp("spec/svc", tmpdir)
            assert result == ["2025-10-01", "2025-11-01"]

    def test_preview_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_main_tsp(
                tmpdir,
                "spec/svc",
                """
enum Versions {
  v2025_07_01_preview: "2025-07-01-preview",
}
""",
            )
            result = extract_versions_from_main_tsp("spec/svc", tmpdir)
            assert result == ["2025-07-01-preview"]

    def test_no_main_tsp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = extract_versions_from_main_tsp("spec/nonexistent", tmpdir)
            assert result == []

    def test_no_enum_versions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_main_tsp(tmpdir, "spec/svc", 'import "./models.tsp";')
            result = extract_versions_from_main_tsp("spec/svc", tmpdir)
            assert result == []

    def test_preserves_declaration_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_main_tsp(
                tmpdir,
                "spec/svc",
                """
enum Versions {
  v2024_01_01: "2024-01-01",
  v2025_03_01: "2025-03-01",
  v2024_06_01: "2024-06-01",
}
""",
            )
            result = extract_versions_from_main_tsp("spec/svc", tmpdir)
            assert result == ["2024-01-01", "2025-03-01", "2024-06-01"]


# ---------------------------------------------------------------------------
# resolve_api_version
# ---------------------------------------------------------------------------
class TestResolveApiVersion:
    def test_single_swagger_version_in_tsp(self):
        version, source = resolve_api_version("2025-11-01", ["2025-10-01", "2025-11-01"])
        assert version == "2025-11-01"
        assert source == "swagger"

    def test_single_swagger_version_not_in_tsp(self):
        version, source = resolve_api_version("2024-01-01", ["2025-10-01", "2025-11-01"])
        assert version == "2025-11-01"
        assert source == "typespec-latest"

    def test_multiple_swagger_versions(self):
        version, source = resolve_api_version("2019-11-01,2021-06-01,2025-03-01", ["2025-10-01", "2025-11-01"])
        assert version == "2025-11-01"
        assert source == "typespec-latest"

    def test_empty_swagger_versions(self):
        version, source = resolve_api_version("", ["2025-10-01", "2025-11-01"])
        assert version == "2025-11-01"
        assert source == "typespec-latest"

    def test_none_swagger_versions(self):
        version, source = resolve_api_version(None, ["2025-10-01"])
        assert version is None
        assert source is None

    def test_empty_tsp_versions_with_swagger(self):
        version, source = resolve_api_version("2025-11-01", [])
        assert version is None
        assert source is None

    def test_both_empty(self):
        version, source = resolve_api_version("", [])
        assert version is None
        assert source is None

    def test_single_swagger_matches_only_tsp_version(self):
        version, source = resolve_api_version("2025-09-01", ["2025-09-01"])
        assert version == "2025-09-01"
        assert source == "swagger"

    def test_uses_last_tsp_version_as_latest(self):
        version, source = resolve_api_version("2024-01-01,2024-06-01", ["2024-01-01", "2025-03-01", "2024-06-01"])
        assert version == "2024-06-01"
        assert source == "typespec-latest"
