"""Tests for generate_typespec_sdk.py"""

import os

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generate_typespec_sdk import strip_mgmt_prefix


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
