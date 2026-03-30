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

### 5. Renaming of `values`/`keys` Properties

When a model deletes a property named `values` or `keys` and adds a corresponding `values_property` or `keys_property`, merge them into a single rename entry.

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

When a model introduces a new container property (commonly named `properties`) and multiple instance variables of that model are subsequently reported as "deleted or renamed", treat these as a structural move rather than separate deletions.

**Before:**
```
   - Model `A` added property `properties`
   - Model `A` deleted or renamed its instance variable `a`
   - Model `A` deleted or renamed its instance variable `b`
   - Model `A` deleted or renamed its instance variable `c`
```

**After:**
```
   - Model `A` moved instance variable `a`, `b` and `c` under property `properties`
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

### 9. Consolidate Unused List Models

When multiple `...List` models are reported as "deleted or renamed" (including models that only contain `next_link` and `value` — typical paging result wrappers; verify by checking the SDK code), replace the individual lines with a single entry and move it to the `### Other Changes` section:

**Before:**
```
### Breaking Changes

  - Deleted or renamed model `SkuInformationList`
  - Deleted or renamed model `SnapshotList`
  - Deleted or renamed model `VolumeGroupList`
  - Deleted or renamed model `VolumeList`
```

**After:**
```
### Other Changes

  - Deleted model `SkuInformationList`/`SnapshotList`/`VolumeGroupList`/`VolumeList` which actually were not used by SDK users
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

### NOTE

- Declarations about migration docs shall be at the top line in the `### Breaking Changes` section.
- Only check the latest part of the changelog.
