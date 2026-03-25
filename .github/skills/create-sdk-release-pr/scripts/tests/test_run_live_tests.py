"""Tests for run_live_tests.py."""

import os
import pathlib
import textwrap

import pytest

# Add parent directory to path so we can import the module under test
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from run_live_tests import (
    _build_test_summary,
    _extract_failures,
    _extract_root_cause,
    _has_only_api_version_param,
    _split_test_file,
    copy_and_transform_tests,
    ensure_test_deps_in_dev_requirements,
    find_sdk_dir,
    get_pyproject_title,
    get_sdk_version,
    load_env_file,
    preflight_check,
    transform_test_content,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def sdk_tree(tmp_path):
    """Create a minimal SDK directory layout for tests."""
    worktree = tmp_path / "worktree"
    service = worktree / "sdk" / "myservice" / "azure-mgmt-myservice"
    service.mkdir(parents=True)
    (service / "tests").mkdir()
    (service / "generated_tests").mkdir()
    return worktree, service


# ── get_sdk_version ───────────────────────────────────────────────────────


class TestGetSdkVersion:
    def test_extracts_first_version(self, tmp_path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "# Release History\n\n## 1.0.0b1 (2024-01-01)\n\n- Initial release\n",
            encoding="utf-8",
        )
        assert get_sdk_version(str(changelog)) == "1.0.0b1"

    def test_extracts_stable_version(self, tmp_path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "## 2.3.0 (2024-06-01)\n\n- Feature A\n\n## 2.2.0 (2024-01-01)\n\n- Feature B\n",
            encoding="utf-8",
        )
        assert get_sdk_version(str(changelog)) == "2.3.0"

    def test_returns_none_for_missing_file(self, tmp_path):
        assert get_sdk_version(str(tmp_path / "CHANGELOG.md")) is None

    def test_returns_none_when_no_version_found(self, tmp_path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# No version here\n\nJust text.\n", encoding="utf-8")
        assert get_sdk_version(str(changelog)) is None


# ── get_pyproject_title ───────────────────────────────────────────────────


class TestGetPyprojectTitle:
    def test_extracts_title(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "azure-mgmt-foo"\ntitle = "Microsoft Azure Mgmt Foo"\n',
            encoding="utf-8",
        )
        assert get_pyproject_title(str(pyproject)) == "Microsoft Azure Mgmt Foo"

    def test_returns_none_for_missing_file(self, tmp_path):
        assert get_pyproject_title(str(tmp_path / "pyproject.toml")) is None

    def test_returns_none_when_no_title(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "azure-mgmt-foo"\n', encoding="utf-8")
        assert get_pyproject_title(str(pyproject)) is None


# ── preflight_check ───────────────────────────────────────────────────────


class TestPreflightCheck:
    def test_passes_for_non_1_0_0b1(self, tmp_path):
        sdk_dir = tmp_path / "pkg"
        sdk_dir.mkdir()
        (sdk_dir / "CHANGELOG.md").write_text("## 2.0.0 (2024-01-01)\n", encoding="utf-8")
        # Should not raise
        preflight_check(str(sdk_dir))

    def test_passes_when_version_is_1_0_0b1_and_title_has_mgmt(self, tmp_path):
        sdk_dir = tmp_path / "pkg"
        sdk_dir.mkdir()
        (sdk_dir / "CHANGELOG.md").write_text("## 1.0.0b1 (2024-01-01)\n", encoding="utf-8")
        (sdk_dir / "pyproject.toml").write_text('title = "Azure Mgmt Foo"\n', encoding="utf-8")
        preflight_check(str(sdk_dir))

    def test_fails_when_1_0_0b1_and_no_mgmt(self, tmp_path):
        sdk_dir = tmp_path / "pkg"
        sdk_dir.mkdir()
        (sdk_dir / "CHANGELOG.md").write_text("## 1.0.0b1 (2024-01-01)\n", encoding="utf-8")
        (sdk_dir / "pyproject.toml").write_text('title = "Azure Foo Client"\n', encoding="utf-8")
        with pytest.raises(SystemExit):
            preflight_check(str(sdk_dir))

    def test_fails_when_1_0_0b1_and_no_pyproject(self, tmp_path):
        sdk_dir = tmp_path / "pkg"
        sdk_dir.mkdir()
        (sdk_dir / "CHANGELOG.md").write_text("## 1.0.0b1 (2024-01-01)\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            preflight_check(str(sdk_dir))


# ── find_sdk_dir ──────────────────────────────────────────────────────────


class TestFindSdkDir:
    def test_finds_package(self, sdk_tree):
        worktree, _ = sdk_tree
        result = find_sdk_dir(str(worktree), "azure-mgmt-myservice")
        assert result == str(worktree / "sdk" / "myservice" / "azure-mgmt-myservice")

    def test_dies_when_no_sdk_root(self, tmp_path):
        with pytest.raises(SystemExit):
            find_sdk_dir(str(tmp_path), "azure-mgmt-myservice")

    def test_dies_when_package_not_found(self, tmp_path):
        (tmp_path / "sdk" / "other").mkdir(parents=True)
        with pytest.raises(SystemExit):
            find_sdk_dir(str(tmp_path), "azure-mgmt-missing")


# ── _split_test_file ─────────────────────────────────────────────────────


class TestSplitTestFile:
    def test_splits_methods_with_decorators(self):
        text = textwrap.dedent("""\
            import pytest

            class TestFoo:
                @pytest.mark.skip
                def test_alpha(self):
                    pass

                @pytest.mark.skip
                def test_beta(self):
                    pass
        """)
        header, methods = _split_test_file(text)
        assert "import pytest" in header
        assert "class TestFoo:" in header
        assert len(methods) == 2
        assert methods[0][1] == "test_alpha"
        assert methods[1][1] == "test_beta"

    def test_no_methods(self):
        text = "import pytest\n\nclass TestFoo:\n    pass\n"
        header, methods = _split_test_file(text)
        assert header == text
        assert methods == []

    def test_async_methods(self):
        text = textwrap.dedent("""\
            class TestAsync:
                async def test_one(self):
                    pass
        """)
        header, methods = _split_test_file(text)
        assert len(methods) == 1
        assert methods[0][1] == "test_one"

    def test_multiple_decorators(self):
        text = textwrap.dedent("""\
            class TestDeco:
                @decorator_a
                @decorator_b
                def test_multi(self):
                    pass
        """)
        header, methods = _split_test_file(text)
        assert len(methods) == 1
        assert "@decorator_a" in methods[0][0]
        assert "@decorator_b" in methods[0][0]


# ── _has_only_api_version_param ───────────────────────────────────────────


class TestHasOnlyApiVersionParam:
    def test_no_params(self):
        text = '    result = self.client.operations.list()'
        assert _has_only_api_version_param(text) is True

    def test_only_api_version(self):
        text = '    result = self.client.operations.list(api_version="2024-01-01")'
        assert _has_only_api_version_param(text) is True

    def test_other_params(self):
        text = '    result = self.client.operations.create(name="test", api_version="2024-01-01")'
        assert _has_only_api_version_param(text) is False

    def test_no_client_call(self):
        text = "    x = 1"
        assert _has_only_api_version_param(text) is False

    def test_api_version_with_trailing_comma(self):
        text = '    result = self.client.operations.list(api_version="2024-01-01",)'
        assert _has_only_api_version_param(text) is True


# ── transform_test_content ────────────────────────────────────────────────


class TestTransformTestContent:
    SAMPLE_TEST = textwrap.dedent("""\
        import pytest
        from devtools_testutils import AzureMgmtRecordedTestCase

        @pytest.mark.skip(reason="skip")
        class TestFoo(AzureMgmtRecordedTestCase):
            @pytest.mark.skip(reason="skip")
            def test_list(self):
                response = self.client.operations.list(api_version="2024-01-01")
                # please add some check logic here by yourself
                # ...
    """)

    def test_replaces_skip_with_live_test_only(self):
        result = transform_test_content(self.SAMPLE_TEST)
        assert result is not None
        assert "@pytest.mark.live_test_only" in result
        assert "@pytest.mark.skip" not in result

    def test_adds_assertion(self):
        result = transform_test_content(self.SAMPLE_TEST)
        assert "assert response is not None" in result

    def test_removes_placeholder_comment(self):
        result = transform_test_content(self.SAMPLE_TEST)
        assert "# ..." not in result
        assert "# please add some check logic here by yourself" not in result

    def test_strips_api_version_param(self):
        result = transform_test_content(self.SAMPLE_TEST)
        assert "api_version" not in result
        assert "self.client.operations.list()" in result

    def test_returns_none_when_no_qualifying_methods(self):
        text = textwrap.dedent("""\
            class TestFoo:
                def test_create(self):
                    result = self.client.resources.create(name="test", resource={})
        """)
        assert transform_test_content(text) is None

    def test_uses_result_variable_name(self):
        text = textwrap.dedent("""\
            class TestFoo:
                def test_list(self):
                    result = self.client.operations.list()
                    # please add some check logic here by yourself
        """)
        result = transform_test_content(text)
        assert "assert result is not None" in result

    def test_uses_len_assertion_for_list_comprehension_result(self):
        text = textwrap.dedent("""\
            class TestFoo:
                def test_list(self):
                    response = self.client.operations.list()
                    result = [r for r in response]
                    # please add some check logic here by yourself
        """)
        result = transform_test_content(text)
        assert "assert len(result) >= 0" in result
        assert "assert result is not None" not in result

    def test_filters_out_non_qualifying_methods(self):
        text = textwrap.dedent("""\
            class TestFoo:
                def test_list(self):
                    response = self.client.operations.list()
                    # please add some check logic here by yourself

                def test_create(self):
                    response = self.client.resources.create(name="test")
                    # please add some check logic here by yourself
        """)
        result = transform_test_content(text)
        assert result is not None
        assert "test_list" in result
        assert "test_create" not in result

    def test_class_level_skip_replaced(self):
        text = textwrap.dedent("""\
            @pytest.mark.skip(reason="skip test")
            class TestFoo:
                def test_list(self):
                    response = self.client.operations.list()
                    # please add some check logic here by yourself
        """)
        result = transform_test_content(text)
        assert "@pytest.mark.live_test_only" in result
        assert "@pytest.mark.skip" not in result


# ── copy_and_transform_tests ─────────────────────────────────────────────


class TestCopyAndTransformTests:
    def test_copies_and_transforms_generated_tests(self, sdk_tree):
        _, sdk_dir = sdk_tree
        gen = sdk_dir / "generated_tests"
        gen.mkdir(exist_ok=True)
        (gen / "test_operations.py").write_text(
            textwrap.dedent("""\
                import pytest

                class TestOps:
                    def test_list(self):
                        response = self.client.operations.list()
                        # please add some check logic here by yourself
            """),
            encoding="utf-8",
        )

        updated = copy_and_transform_tests(str(sdk_dir))
        assert len(updated) > 0
        test_file = sdk_dir / "tests" / "test_operations_test.py"
        assert test_file.exists()
        content = test_file.read_text(encoding="utf-8")
        assert "assert response is not None" in content

    def test_skips_when_test_files_exist(self, sdk_tree):
        _, sdk_dir = sdk_tree
        tests_dir = sdk_dir / "tests"
        (tests_dir / "existing_test.py").write_text("pass", encoding="utf-8")

        result = copy_and_transform_tests(str(sdk_dir))
        assert result == []

    def test_dies_when_no_generated_tests_dir(self, tmp_path):
        sdk_dir = tmp_path / "pkg"
        sdk_dir.mkdir()
        (sdk_dir / "tests").mkdir()
        with pytest.raises(SystemExit):
            copy_and_transform_tests(str(sdk_dir))

    def test_copies_conftest(self, sdk_tree):
        _, sdk_dir = sdk_tree
        gen = sdk_dir / "generated_tests"
        gen.mkdir(exist_ok=True)
        (gen / "conftest.py").write_text("# conftest\nfixture = True\n", encoding="utf-8")
        (gen / "test_ops.py").write_text(
            textwrap.dedent("""\
                class TestOps:
                    def test_list(self):
                        response = self.client.operations.list()
                        # please add some check logic here by yourself
            """),
            encoding="utf-8",
        )

        updated = copy_and_transform_tests(str(sdk_dir))
        conftest_dest = sdk_dir / "tests" / "conftest.py"
        assert conftest_dest.exists()
        assert str(conftest_dest) in updated

    def test_dies_when_no_qualifying_methods(self, sdk_tree):
        _, sdk_dir = sdk_tree
        gen = sdk_dir / "generated_tests"
        gen.mkdir(exist_ok=True)
        (gen / "test_ops.py").write_text(
            textwrap.dedent("""\
                class TestOps:
                    def test_create(self):
                        response = self.client.resources.create(name="x", body={})
            """),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit):
            copy_and_transform_tests(str(sdk_dir))


# ── load_env_file ─────────────────────────────────────────────────────────


class TestLoadEnvFile:
    def test_loads_variables(self, tmp_path):
        (tmp_path / ".env").write_text(
            'AZURE_TEST_RUN_LIVE=true\nAZURE_TENANT_ID="abc-123"\n',
            encoding="utf-8",
        )
        env = load_env_file(str(tmp_path))
        assert env["AZURE_TEST_RUN_LIVE"] == "true"
        assert env["AZURE_TENANT_ID"] == "abc-123"

    def test_skips_comments_and_blanks(self, tmp_path):
        (tmp_path / ".env").write_text(
            "# comment\n\nKEY=value\n",
            encoding="utf-8",
        )
        env = load_env_file(str(tmp_path))
        assert env == {"KEY": "value"}

    def test_dies_when_missing(self, tmp_path):
        with pytest.raises(SystemExit):
            load_env_file(str(tmp_path / "nonexistent"))

    def test_strips_quotes(self, tmp_path):
        (tmp_path / ".env").write_text(
            "A='single'\nB=\"double\"\n",
            encoding="utf-8",
        )
        env = load_env_file(str(tmp_path))
        assert env["A"] == "single"
        assert env["B"] == "double"


# ── ensure_test_deps_in_dev_requirements ──────────────────────────────────


class TestEnsureTestDeps:
    def test_adds_missing_deps(self, tmp_path):
        dev_req = tmp_path / "dev_requirements.txt"
        dev_req.write_text("pytest\n", encoding="utf-8")
        ensure_test_deps_in_dev_requirements(str(tmp_path))
        content = dev_req.read_text(encoding="utf-8")
        assert "azure-identity" in content
        assert "aiohttp" in content

    def test_does_not_duplicate_existing(self, tmp_path):
        dev_req = tmp_path / "dev_requirements.txt"
        dev_req.write_text("pytest\nazure-identity\naiohttp\n", encoding="utf-8")
        ensure_test_deps_in_dev_requirements(str(tmp_path))
        content = dev_req.read_text(encoding="utf-8")
        assert content.count("azure-identity") == 1
        assert content.count("aiohttp") == 1

    def test_noop_when_no_file(self, tmp_path):
        # Should not raise
        ensure_test_deps_in_dev_requirements(str(tmp_path))


# ── _build_test_summary ──────────────────────────────────────────────────


class TestBuildTestSummary:
    def test_passed_summary(self):
        output = "tests/foo_test.py::test_one PASSED\n= 1 passed in 0.5s ="
        md = _build_test_summary(output, passed=True)
        assert "✅" in md
        assert "1 passed" in md

    def test_failed_summary(self):
        output = "tests/foo_test.py::test_one FAILED\n= 1 failed in 0.5s ="
        md = _build_test_summary(output, passed=False)
        assert "❌" in md
        assert "Failed Tests" in md or "1 failed" in md

    def test_empty_output(self):
        md = _build_test_summary("", passed=True)
        assert "✅" in md


# ── _extract_failures ─────────────────────────────────────────────────────


class TestExtractFailures:
    def test_extracts_full_block_failure(self):
        lines = [
            "___ test_alpha ___",
            "    def test_alpha():",
            ">       assert False",
            "E       AssertionError",
            "=== short test summary ===",
        ]
        failures = _extract_failures(lines)
        assert len(failures) == 1
        assert failures[0][0] == "test_alpha"

    def test_extracts_short_summary_failure(self):
        lines = [
            "FAILED tests/foo_test.py::test_bar - AssertionError",
        ]
        failures = _extract_failures(lines)
        assert len(failures) == 1
        assert "test_bar" in failures[0][0]
        assert "AssertionError" in failures[0][1]

    def test_no_duplicate_from_short_and_full(self):
        lines = [
            "___ tests/foo_test.py::test_bar ___",
            "E       AssertionError",
            "=== short test summary ===",
            "FAILED tests/foo_test.py::test_bar - AssertionError",
        ]
        failures = _extract_failures(lines)
        assert len(failures) == 1

    def test_no_failures(self):
        lines = ["tests/foo_test.py::test_one PASSED", "= 1 passed ="]
        assert _extract_failures(lines) == []


# ── _extract_root_cause ───────────────────────────────────────────────────


class TestExtractRootCause:
    def test_extracts_e_lines(self):
        block = [
            "    def test_foo():",
            ">       assert 1 == 2",
            "E       AssertionError: assert 1 == 2",
        ]
        cause = _extract_root_cause(block)
        assert "AssertionError" in cause

    def test_fallback_for_no_e_lines(self):
        block = ["line 1", "line 2", "line 3"]
        cause = _extract_root_cause(block)
        assert "line" in cause

    def test_empty_block(self):
        assert _extract_root_cause([]) == "(no details captured)"

    def test_includes_traceback_context(self):
        block = [
            "    some preamble",
            "    x = foo()",
            '    file.py:42: in test_bar',
            ">       raise ValueError",
            "E       ValueError: bad value",
        ]
        cause = _extract_root_cause(block)
        assert "ValueError: bad value" in cause
        assert "file.py:42" in cause
