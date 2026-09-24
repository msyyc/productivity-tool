---
name: github-alias-to-teams-alias
description: Find a Microsoft employee's Teams display name and work email from a GitHub username. Reuse the local identity cache first; resolve new identities with GitHub public evidence and Agency directory lookup, with WorkIQ as an evidence fallback.
---

# GitHub username to Teams identity

Run the bundled PowerShell 7 helper before doing any other identity search:

```powershell
pwsh -NoProfile -File "<skill-directory>\lookup-github-teams.ps1" -GithubAlias msyyc
```

The default cache is `identity.json` in this skill's folder, alongside
`SKILL.md` and the helper (independent of the current working directory). It contains corporate
identity data and is ignored by Git. Do not commit or upload it. A custom
`-CachePath` is supported; keep custom paths outside version control too.
Keep the sibling `common\agency-mcp.ps1` when copying this skill.

## Cache and output

- GitHub usernames are normalized to lowercase.
- A `corroborated` cache entry is returned without calling GitHub or Agency,
  even when those tools are unavailable. Output has `source: cache`.
- A new lookup returns `source: lookup`. Only corroborated identities are
  persisted. Each saved entry has exactly three fields: `githubAlias`,
  `teamsAlias` (the person's full display name, NOT their corporate short alias),
  and `emailAddress`. The file has a `schemaVersion: 2` / `entries` envelope.
- Search Teams by the returned identity's `displayName`, using `mail` to
  distinguish people with the same name. Never construct an email address.
- Live output includes status, candidates, evidence, and a lookup timestamp
  for evaluation, but these are NOT saved in the cache. Cached output contains
  only the login, corroborated status, and identity; it has no verification date.
- Entries do not automatically expire. Use `-Refresh` for stale mappings,
  renamed GitHub accounts, or
  an explicit request to recheck. A failed refresh raises an error and leaves
  the previous record untouched; do not present it as newly verified.
- `candidate`, `ambiguous`, and `not_found` results are returned for inspection,
  not saved. A completed refresh yielding one of these removes any previous
  cached match. A failed lookup does not alter the cache.
- Legacy version 1 caches are migrated atomically on successful use: corroborated
  entries become three-field records, and unresolved entries are removed with
  a warning. Migration of a cached match requires no network access.
- Writes are atomic and serialized with a sidecar lock. A busy lock raises an
  error; do not delete it or bypass it. Malformed cache files raise an error
  without being overwritten. The empty `.lock` sidecar may remain after use.

## Lookup and confidence

The helper reads the public GitHub profile. A Microsoft work email is matched
exactly against Agency `m365-user` / `GetMultipleUsersDetails`. Without that
email, it checks up to five recent public commits and accepts email evidence
only when GitHub attributes the commit to the requested login. Multiple email
candidates are ambiguous, even if only one matches the current directory.

If no work email is available, an exact full-name directory search can return
candidates, never a corroborated result. A missing directory display name also
prevents corroboration. External contributors may remain unresolved.

Public profile/commit data is self-asserted; `corroborated` means supported by
public evidence plus a current directory match, NOT an authoritative
linked-account assertion. Do not use this cache for authorization or automatic
message sending. This skill performs no messaging.

## WorkIQ fallback

For unresolved results, use Agency `workiq` / `retrieve` to search the exact
GitHub handle or profile URL. Prefer an explicit contact table linking both
identities. A person's name, a search-generated answer, or merely sharing a PR
link is not sufficient evidence. Inspect the underlying source and retain its
URL; do not cache unrelated message bodies or personal profile details.

Once a source explicitly links the GitHub login to a work email, persist it
through the same helper (which checks the email against the directory):

```powershell
pwsh -NoProfile -File "<skill-directory>\lookup-github-teams.ps1" `
    -GithubAlias "<login>" -EvidenceEmail "<work-email-from-source>" `
    -EvidenceUrl "<https-source-explicitly-linking-both-identities>"
```

These parameters bypass an existing cache hit and declare that you have
inspected the explicit mapping. The helper does not read or authenticate the
source URL itself. Never supply guessed emails or evidence URLs.

If evidence conflicts or multiple people match, show the candidates and ask
the user to resolve the ambiguity; do not choose automatically. GitHub or
Agency errors are failures, not evidence that no person exists. Do not install
tools or request new permissions without user approval.

## Requirements and offline tests

PowerShell 7.1+, authenticated `gh`, and an installed/authenticated Agency CLI
are needed for live lookups. The portal's API key is not needed.

```powershell
python -m pytest .github\skills\github-alias-to-teams-alias\tests -q
```
