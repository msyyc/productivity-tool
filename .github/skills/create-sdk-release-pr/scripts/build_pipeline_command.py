"""Build the az pipelines run command for SDK Generation - Python pipeline.

This module constructs the CLI command with correct parameter formatting
to prevent the common pitfall of wrapping all --parameters values in a
single quoted string (which causes az CLI to treat everything as ConfigPath).
"""

PIPELINE_ID = 7423
ORG = "https://dev.azure.com/azure-sdk"
PROJECT = "internal"


def build_pipeline_command(
    config_path: str,
    release_type: str,
    api_version: str,
    branch: str = "main",
    create_pr: bool = True,
) -> list[str]:
    """Return the az pipelines run command as a list of argument tokens.

    Each --parameters key=value pair is a separate token so that az CLI
    parses them correctly. Joining them into a single string would cause
    the entire value to be assigned to the first parameter (ConfigPath).
    """
    if not config_path or not config_path.endswith("tspconfig.yaml"):
        raise ValueError(f"config_path must end with 'tspconfig.yaml', got: {config_path!r}")

    if release_type not in ("beta", "stable"):
        raise ValueError(f"release_type must be 'beta' or 'stable', got: {release_type!r}")

    if not api_version:
        raise ValueError("api_version is required")

    return [
        "az",
        "pipelines",
        "run",
        "--id",
        str(PIPELINE_ID),
        "--org",
        ORG,
        "--project",
        PROJECT,
        "--branch",
        branch,
        "--parameters",
        f"ConfigPath={config_path}",
        "ConfigType=TypeSpec",
        f"SdkReleaseType={release_type}",
        f"CreatePullRequest={'true' if create_pr else 'false'}",
        f"ApiVersion={api_version}",
        "--output",
        "json",
    ]
