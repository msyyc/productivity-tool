# CHANGELOG Optimization Guide

This document provides rules and guidelines for optimizing and standardizing CHANGELOG entries. Apply these rules to ensure consistency and clarity in documentation.

## Overview

When optimizing a CHANGELOG, **ONLY** make necessary updates that ensure the log completely meets the conditions of the rules while respecting the original format.

## Optimization Rules

### 1. Naming Corrections

Correct misuse of "Model" for entities that are not models (e.g., operation groups, clients).

#### 1.1 Added Operation Group

The operation group class name is BigCamelCase (e.g., `PrivateLinkResourcesOperations`), but as a property of the client it appears in related snake_case (e.g., `private_link_resources`). Replace "model" with "operation group".

**Before:**
```
- Client `AttestationManagementClient` added operation group `private_link_resources`
- Added model `PrivateLinkResourcesOperations`
```

**After:**
```
- Client `AttestationManagementClient` added operation group `private_link_resources`
- Added operation group `PrivateLinkResourcesOperations`
```

#### 1.2 Added Method

**Before:**
```
Model ...Operations added method `...`
```

**After:**
```
Operation group ...Operations added method `...`
```

#### 1.3 Client Naming

When a `...Client` class is referred to as "Model", replace with "Client".

**Before:**
```
Model `...Client` added parameter `...` in method `__init__`
```

**After:**
```
Client `...Client` added parameter `...` in method `__init__`
```

### 2. Parameter Default Value Changes

Transform default value change descriptions into more user-friendly language.

#### 2.1 Required Parameters

**Before:**
```
`A` removed default value None from its parameter `B`
```

**After:**
```
Parameter `B` of `A` is now required
```

#### 2.2 Optional Parameters

**Before:**
```
`A` parameter `B` changed default value from ... to none
```

**After:**
```
Parameter `B` of `A` is now optional
```

### 3. Entries to Remove

The following types of entries should be removed as they are not relevant for end users:

1. **Method overloads:**
   ```
   Method `...` has a new overload `...`
   ```

2. **Internal property changes:**
   ```
   Model `...` deleted or renamed its instance variable `additional_properties`
   ```

3. **Async-to-sync changes on `Operations.list`:**
   ```
   Method `Operations.list` changed from `asynchronous` to `synchronous`
   ```

### 4. Parameter Renaming

When both insertion and deletion of parameters occur together, merge them into a single rename entry.

**Before:**
```
`A` inserted a `positional_or_keyword` parameter `C`
`A` deleted or renamed its parameter `B` of kind `positional_or_keyword`
```

**After:**
```
`A` renamed its instance variable `B` to `C`
```

### 5. Renaming of Properties That Conflict with Base Model Methods

When a model deletes a property that conflicts with base model method names and adds a corresponding property with `_property` suffix, merge them into a single rename entry. The conflicting names are: `keys`, `items`, `values`, `popitem`, `clear`, `update`, `setdefault`, `pop`, `get`, `copy`.

**Before:**
```
   - Model `ExceptionEntry` deleted or renamed its instance variable `values`
   - Model `ExceptionEntry` added property `values_property`
```

**After:**
```
   - Model `ExceptionEntry` renamed its instance variable `values` to `values_property`
```

### 6. Grouping Moved Instance Variables Under a New Container Property

When a model adds a new property and multiple instance variables of that model are subsequently reported as "deleted or renamed", treat these as a structural move rather than separate deletions.

The container property is NOT always named `properties` — you MUST check the SDK source code (the `_models.py` file under the package directory, e.g. `<worktree_path>/sdk/<service-dir>/<package_name>/<package_namespace>/models/_models.py`) to:
1. Identify which added property is the container (by inspecting the model class definition and seeing which property's type holds the moved variables).
2. Find the type of that container property.
3. Link the `Added model XXX` changelog entry (for the container type) with the `added property` and `deleted or renamed` entries to merge them all together.

Additionally, the changelog often contains an `Added model XXX` entry for the type of the new container property. Merge the `Added model` entry into the consolidated line using `whose type is XXX`.

**Before:**
```
   - Added model `AProperties`
   - Model `A` added property `properties`
   - Model `A` deleted or renamed its instance variable `a`
   - Model `A` deleted or renamed its instance variable `b`
   - Model `A` deleted or renamed its instance variable `c`
```

**After:**
```
   - Model `A` moved instance variable `a`, `b` and `c` under property `properties` whose type is `AProperties`
```

**Before (non-`properties` container name):**
```
   - Added model `AConfig`
   - Model `A` added property `config`
   - Model `A` deleted or renamed its instance variable `x`
   - Model `A` deleted or renamed its instance variable `y`
```

**After:**
```
   - Model `A` moved instance variable `x` and `y` under property `config` whose type is `AConfig`
```

### 7. Hybrid Model Migration Note

When a CHANGELOG contains one or more entries in the `### Breaking Changes` section of the form:

```
Model `X` deleted or renamed its instance variable `y`
```

insert the following standardized migration note as the FIRST bullet directly under `### Breaking Changes`:

```
This version introduces new hybrid models which have dual dictionary and model nature. Please follow https://aka.ms/azsdk/python/migrate/hybrid-models for migration.
```

Rules:
1. Add the note only if at least one matching instance-variable deletion/rename line exists.
2. Do not add the note if it already exists (avoid duplicates).
3. Preserve the original ordering of existing entries after inserting the note.

### 8. Hybrid Operation Migration Note

When a method adds keyword-only `etag` and `match_condition` and (in the same CHANGELOG block) deletes or renames positional_or_keyword `if_match` and `if_none_match`, treat this as a single migration. Replace the individual add/remove lines with one concise entry. Also insert a migration note as the FIRST bullet under `### Breaking Changes`:

**Before:**
```
   - Operation group `A` added parameter `etag` in method `...`
   - Operation group `A` added parameter `match_condition` in method `...`
   - Method `...` deleted or renamed its parameter `if_match` of kind `positional_or_keyword`
   - Method `...` deleted or renamed its parameter `if_none_match` of kind `positional_or_keyword`
```

**After:**
```
   - For the method breakings, please refer to https://aka.ms/azsdk/python/migrate/operations for migration.
   - Method `...` replaced positional_or_keyword ... `if_match`/`if_none_match` to keyword_only ... `etag`/`match_condition`
```

When only `if_match` is removed (without `if_none_match`):

**After:**
```
   - For the method breakings, please refer to https://aka.ms/azsdk/python/migrate/operations for migration.
   - Method `...` replaced positional_or_keyword ... `if_match` to keyword_only ... `etag`/`match_condition`
```

### 9. Consolidate Unused Pageable Models

A "pageable model" is a pageable response wrapper whose only properties are `value`, or `next_link` plus `value`. Their names usually end with `List` but not always — verify by checking the model definition in `_models.py` or `_models_py3.py`.

When multiple pageable models are reported as "deleted or renamed", consolidate them into a single entry under `### Other Changes`:

**Before:**
```
### Breaking Changes

  - Deleted or renamed model `SkuInformationList`
  - Deleted or renamed model `SnapshotList`
```

**After:**
```
### Other Changes

  - Deleted model `SkuInformationList`/`SnapshotList` which actually were not used by SDK users
```

### 10. Group Parameter Kind Changes

When multiple parameters of the same method change from `positional_or_keyword` to `keyword_only`, merge into a single entry:

**Before:**
```
  - Method `CertificateOrdersDiagnosticsOperations.get_app_service_certificate_order_detector_response` changed its parameter `start_time` from `positional_or_keyword` to `keyword_only`
  - Method `CertificateOrdersDiagnosticsOperations.get_app_service_certificate_order_detector_response` changed its parameter `end_time` from `positional_or_keyword` to `keyword_only`
  - Method `CertificateOrdersDiagnosticsOperations.get_app_service_certificate_order_detector_response` changed its parameter `time_grain` from `positional_or_keyword` to `keyword_only`
```

**After:**
```
  - For the method breakings, please refer to https://aka.ms/azsdk/python/migrate/operations for migration.
  - Method `CertificateOrdersDiagnosticsOperations.get_app_service_certificate_order_detector_response` changed its parameter `start_time`/`end_time`/`time_grain` from `positional_or_keyword` to `keyword_only`
```

It's often along with a fake `re-ordered` report like:
```
- Method `...` re-ordered its parameters from `['self', '...', 'if_match', 'if_none_match', 'kwargs']` to `['self', '...', 'etag', 'match_condition', 'kwargs']`
```
Remove this fake re-order report. Don't change other `re-order` reports that do not represent an operation migration.

### 11. Consolidate Unused Models or Enums

When one or more entities are reported as "deleted or renamed" and are NOT referenced anywhere in the SDK source (i.e., never used as a parameter type, return type, or property type by any operation or other model/enum), treat them as unused and consolidate them.

**Important:** The original changelog does NOT distinguish enums from models — it always reports `Deleted or renamed model `X``, even when `X` is actually an enum. You MUST classify each entity by checking which source file defines it:
- **Enum**: defined in a file named `_*enums.py` (e.g., `_enums.py`, `_patch_enums.py`).
- **Model**: defined in `_models.py` or `_models_py3.py`.
- **Operation**: an API defined in files under `operations/*.py` or `_operations/*.py`. Any usage of `X` in these files counts as a reference.

Detection procedure (you MUST verify by checking the SDK source under the package directory, typically `<worktree_path>/sdk/<service-dir>/<package_name>/<package_namespace>/`):
1. For each `Deleted or renamed model `X`` entry, locate the previous-version source to determine whether `X` is a model or enum (by the defining file name above).
2. Search the SDK source for any reference to `X` (in `models/_models.py`, `models/_enums.py`, operation files, etc.). If `X` is not referenced by any operation or any other model/enum, it is unused.
3. Exclude entries already covered by rule 9 (pageable models) or by rule 12's rename/combine consolidation.

Replace the individual lines with consolidated entries under `### Other Changes`, emitting **two separate lines** — one for unused models and one for unused enums (omit a line if its group is empty):

**Before:**
```
### Breaking Changes

  - Deleted or renamed model `FooSettings`
  - Deleted or renamed model `BarMode`
  - Deleted or renamed model `BazKind`
```

(Suppose `FooSettings` is defined in `_models.py`, while `BarMode` and `BazKind` are defined in `_enums.py`.)

**After:**
```
### Other Changes

  - Deleted model `FooSettings` which actually were not used by SDK users
  - Deleted enum `BarMode`/`BazKind` which actually were not used by SDK users
```

If only one group has entries, emit only that line (e.g., only the `Deleted model ...` line, or only the `Deleted enum ...` line).

### 12. Consolidate Renames and Combined Enums

After applying the rules above, also apply the rename/combine consolidation procedure described in [../../sdk-breaking-check-for-tsp-migration/references/optimize-changelog-consolidate-renames.md](../../sdk-breaking-check-for-tsp-migration/references/optimize-changelog-consolidate-renames.md) to collapse paired `Deleted or renamed model` + `Added model/enum` entries into clearer `Renamed X to Y` (1‑1) or `Combined enum X/Y/... to Z` (many‑1) lines.

### 13. Deduplicate Return Type Changes for Async/Sync Pairs

When a `Method X.Y changed return type ...` entry appears twice for the same method name — once for the async client (return type contains `AsyncIterator`, `AsyncLROPoller`, `AsyncItemPaged`, etc.) and once for the sync client — keep only the sync entry.

**Before:**
```
  - Method `RunbookOperations.get_content` changed return type from `AsyncIterator[bytes]` to `str`
  - Method `RunbookOperations.get_content` changed return type from `Iterator[bytes]` to `str`
```

**After:**
```
  - Method `RunbookOperations.get_content` changed return type from `Iterator[bytes]` to `str`
```

### NOTE

- Declarations about migration docs shall be at the top line in the `### Breaking Changes` section.
- Only check the latest part of the changelog.
