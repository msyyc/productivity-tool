---
name: looking-up-urls
description: Constructs direct GitHub HTTP URLs (permalinks) for files, folders, or code matches in Azure SDK-related repositories. Use when the user asks to find, locate, or look up a file, path, string, or symbol within a GitHub repository and wants a clickable link.
---

# URL Lookup

When the user asks to find something in a repository, search for it and return a direct GitHub URL so they can open it in a browser immediately.

## URL format

Use the appropriate GitHub URL pattern:

- **File or folder on a branch**: `https://github.com/{owner}/{repo}/tree/{branch}/{path}`
- **File at a specific commit**: `https://github.com/{owner}/{repo}/blob/{commit_sha}/{path}`
- **Line in a file**: `https://github.com/{owner}/{repo}/blob/{branch}/{path}#L{line}`
- **Line range**: `https://github.com/{owner}/{repo}/blob/{branch}/{path}#L{start}-L{end}`

Prefer permalinks with commit SHA over branch names when the user is referencing a specific version.

## Workflow

1. Identify the target repository from user context. Refer to the `## Key Terminology` section in [copilot-instructions.md](../../copilot-instructions.md) for repo aliases and local paths.
2. Search the repository for the requested string, file, or path.
3. Return the result as a clickable HTTP URL with a brief description of what was found.

## Output format

Always include:
- The full clickable URL
- A short description of what the link points to (e.g., file name, matched line content)

Example:

```
The `Client` class is defined here:
https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/core/azure-core/azure/core/_pipeline_client.py#L30
```

## Rules

- If a local repo path is available (e.g., `C:/dev/azure-rest-api-specs`), search locally first, then construct the remote GitHub URL from the relative path.
- If the content is not found, say so clearly rather than guessing a URL.
- When multiple matches exist, return the most relevant match first, then list others.
- Exclude `examples` folders from search results by default. Only include them if the user explicitly asks for examples.
