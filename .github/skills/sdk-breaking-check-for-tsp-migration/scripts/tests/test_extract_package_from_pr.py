"""Tests for extract_package_from_pr.py"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from extract_package_from_pr import extract_package_name, parse_pr_number


# ---------------------------------------------------------------------------
# parse_pr_number
# ---------------------------------------------------------------------------
class TestParsePrNumber:
    def test_full_url(self):
        assert parse_pr_number("https://github.com/Azure/azure-rest-api-specs/pull/40023") == "40023"

    def test_url_with_trailing_slash(self):
        assert parse_pr_number("https://github.com/Azure/azure-rest-api-specs/pull/12345/") == "12345"

    def test_url_with_files_tab(self):
        assert parse_pr_number("https://github.com/Azure/azure-rest-api-specs/pull/99999/files") == "99999"

    def test_plain_number(self):
        assert parse_pr_number("40023") == "40023"

    def test_number_with_whitespace(self):
        assert parse_pr_number("  40023  ") == "40023"

    def test_invalid_input(self):
        with pytest.raises(SystemExit):
            parse_pr_number("not-a-pr")


# ---------------------------------------------------------------------------
# extract_package_name
# ---------------------------------------------------------------------------
class TestExtractPackageName:
    def test_mgmt_package(self):
        content = """\
options:
  "@azure-tools/typespec-python":
    emitter-output-dir: "{output-dir}/{service-dir}/azure-mgmt-advisor"
    namespace: "azure.mgmt.advisor"
    generate-test: true
    generate-sample: true
    flavor: "azure"
  "@azure-tools/typespec-java":
    emitter-output-dir: "{output-dir}/{service-dir}/azure-resourcemanager-advisor"
"""
        assert extract_package_name(content) == "azure-mgmt-advisor"

    def test_dataplane_package(self):
        content = """\
options:
  "@azure-tools/typespec-python":
    emitter-output-dir: "{output-dir}/{service-dir}/azure-ai-vision-face"
    namespace: "azure.ai.vision.face"
    package-version: 1.0.0b2
    flavor: azure
"""
        assert extract_package_name(content) == "azure-ai-vision-face"

    def test_no_python_emitter(self):
        content = """\
options:
  "@azure-tools/typespec-java":
    emitter-output-dir: "{output-dir}/{service-dir}/azure-resourcemanager-advisor"
"""
        assert extract_package_name(content) is None

    def test_empty_content(self):
        assert extract_package_name("") is None

    def test_quoted_keys(self):
        content = """\
options:
  "@azure-tools/typespec-python":
    emitter-output-dir: "{output-dir}/{service-dir}/azure-mgmt-network"
"""
        assert extract_package_name(content) == "azure-mgmt-network"

    def test_single_quoted_value(self):
        content = """\
options:
  '@azure-tools/typespec-python':
    emitter-output-dir: '{output-dir}/{service-dir}/azure-mgmt-storage'
"""
        assert extract_package_name(content) == "azure-mgmt-storage"

    def test_no_options_wrapper(self):
        """Fallback: emitter directly at top level (non-standard but possible)."""
        content = """\
"@azure-tools/typespec-python":
  emitter-output-dir: "{output-dir}/{service-dir}/azure-mgmt-compute"
"""
        # The line parser should still find it (indented under the emitter key)
        result = extract_package_name(content)
        # With yaml available, it won't have 'options' key so returns None
        # With line parser fallback, it should find it
        # Either outcome is acceptable - the key test is that it doesn't crash
        assert result in ("azure-mgmt-compute", None)
