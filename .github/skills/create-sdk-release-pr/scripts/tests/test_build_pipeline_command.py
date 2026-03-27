"""Tests for build_pipeline_command.py.

Validates that the az pipelines run command is constructed with each
--parameters key=value as a separate token — preventing the bug where
wrapping all params in one string causes az CLI to assign the entire
value to ConfigPath.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from build_pipeline_command import build_pipeline_command


# ── Correct command structure ────────────────────────────────────────────


class TestBuildPipelineCommand:
    """Core tests for command token structure."""

    SAMPLE_PATH = "specification/peering/resource-manager/Microsoft.Peering/Peering/tspconfig.yaml"

    def test_parameters_are_separate_tokens(self):
        """Each key=value after --parameters must be its own list element.

        This is the exact bug we're guarding against: if multiple key=value
        pairs end up in a single string, az CLI assigns everything to the
        first key (ConfigPath).
        """
        tokens = build_pipeline_command(self.SAMPLE_PATH, "beta", "2025-05-01")
        idx = tokens.index("--parameters")
        param_tokens = []
        for t in tokens[idx + 1 :]:
            if t.startswith("--"):
                break
            param_tokens.append(t)

        # Each token must be exactly one key=value pair (no spaces)
        for token in param_tokens:
            assert " " not in token, (
                f"Parameter token contains a space — multiple params collapsed "
                f"into one string: {token!r}"
            )
            assert "=" in token, f"Expected key=value format, got: {token!r}"

    def test_config_path_not_concatenated_with_other_params(self):
        """ConfigPath value must contain only the path, not other params."""
        tokens = build_pipeline_command(self.SAMPLE_PATH, "beta", "2025-05-01")
        config_token = [t for t in tokens if t.startswith("ConfigPath=")][0]
        value = config_token.split("=", 1)[1]

        assert "SdkReleaseType" not in value
        assert "CreatePullRequest" not in value
        assert "ApiVersion" not in value
        assert value == self.SAMPLE_PATH

    def test_config_type_included(self):
        """ConfigType=TypeSpec must be present as a separate parameter."""
        tokens = build_pipeline_command(self.SAMPLE_PATH, "stable", "2025-05-01")
        assert "ConfigType=TypeSpec" in tokens

    def test_all_required_params_present(self):
        """All five required pipeline parameters must be in the command."""
        tokens = build_pipeline_command(self.SAMPLE_PATH, "beta", "2025-05-01")
        param_keys = set()
        for t in tokens:
            if "=" in t and not t.startswith("--"):
                param_keys.add(t.split("=", 1)[0])

        expected = {"ConfigPath", "ConfigType", "SdkReleaseType", "CreatePullRequest", "ApiVersion"}
        assert expected == param_keys

    def test_release_type_beta(self):
        tokens = build_pipeline_command(self.SAMPLE_PATH, "beta", "2025-05-01")
        assert "SdkReleaseType=beta" in tokens

    def test_release_type_stable(self):
        tokens = build_pipeline_command(self.SAMPLE_PATH, "stable", "2025-05-01")
        assert "SdkReleaseType=stable" in tokens

    def test_create_pr_true(self):
        tokens = build_pipeline_command(self.SAMPLE_PATH, "beta", "2025-05-01", create_pr=True)
        assert "CreatePullRequest=true" in tokens

    def test_create_pr_false(self):
        tokens = build_pipeline_command(self.SAMPLE_PATH, "beta", "2025-05-01", create_pr=False)
        assert "CreatePullRequest=false" in tokens

    def test_custom_branch(self):
        tokens = build_pipeline_command(self.SAMPLE_PATH, "beta", "2025-05-01", branch="feature/test")
        idx = tokens.index("--branch")
        assert tokens[idx + 1] == "feature/test"

    def test_api_version_in_command(self):
        tokens = build_pipeline_command(self.SAMPLE_PATH, "beta", "2026-01-15-preview")
        assert "ApiVersion=2026-01-15-preview" in tokens


# ── Input validation ─────────────────────────────────────────────────────


class TestInputValidation:

    def test_rejects_empty_config_path(self):
        with pytest.raises(ValueError, match="tspconfig.yaml"):
            build_pipeline_command("", "beta", "2025-05-01")

    def test_rejects_non_tspconfig_path(self):
        with pytest.raises(ValueError, match="tspconfig.yaml"):
            build_pipeline_command("specification/foo/readme.md", "beta", "2025-05-01")

    def test_rejects_invalid_release_type(self):
        with pytest.raises(ValueError, match="release_type"):
            build_pipeline_command(
                "specification/foo/tspconfig.yaml", "preview", "2025-05-01"
            )

    def test_rejects_empty_api_version(self):
        with pytest.raises(ValueError, match="api_version"):
            build_pipeline_command(
                "specification/foo/tspconfig.yaml", "beta", ""
            )


# ── SKILL.md validation ──────────────────────────────────────────────────


SKILL_MD_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "SKILL.md"
)


class TestSkillMdInstructions:
    """Validate that SKILL.md pipeline command instructions stay correct."""

    @pytest.fixture(autouse=True)
    def _load_skill(self):
        with open(SKILL_MD_PATH, "r", encoding="utf-8") as f:
            self.content = f.read()

    def _extract_pipeline_code_block(self):
        """Extract the code block containing 'az pipelines run'."""
        blocks = re.findall(r"```\n(.*?)```", self.content, re.DOTALL)
        for block in blocks:
            if "az pipelines run" in block:
                return block
        pytest.fail("No code block with 'az pipelines run' found in SKILL.md")

    def test_config_type_documented(self):
        """ConfigType=TypeSpec must appear in the pipeline command."""
        block = self._extract_pipeline_code_block()
        assert "ConfigType=TypeSpec" in block, (
            "SKILL.md pipeline command is missing ConfigType=TypeSpec"
        )

    def test_params_not_in_single_string(self):
        """The --parameters line must not have all values on the same line."""
        block = self._extract_pipeline_code_block()
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("--parameters"):
                # Count key=value pairs on this same line
                pairs = re.findall(r"\w+=", stripped)
                assert len(pairs) <= 1, (
                    f"Multiple key=value params on the --parameters line risks "
                    f"single-string quoting: {stripped!r}"
                )

    def test_quoting_warning_present(self):
        """SKILL.md must warn about not wrapping params in a single string."""
        assert "single quoted string" in self.content.lower() or "single string" in self.content.lower(), (
            "SKILL.md should contain a warning about not wrapping "
            "parameters in a single quoted string"
        )
