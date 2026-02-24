---
name: typespec-completion
description: Complete partial TypeSpec (.tsp) code into a fully compilable file and verify it compiles. Use when the user provides TypeSpec code snippets, models, operations, or asks to create/complete/fix a TypeSpec file. Triggers on mentions of TypeSpec, tsp, models, operations, or REST API definitions in TypeSpec syntax.
---

# TypeSpec Completion

Complete user-provided partial TypeSpec code into a fully compilable `.tsp` file, write it to disk, and verify compilation.

## Workflow

1. Analyze the user's partial TypeSpec code to determine what is missing (imports, using statements, namespace, decorators, etc.)
2. Determine flavor: **Azure** (uses `@azure-tools/*` packages, Azure.Core, ARM) or **Unbranded** (plain `@typespec/http`)
3. Assemble the complete file using the appropriate template from [references/templates.md](references/templates.md)
4. Write the file to the target path (default: `C:\dev\typespec\packages\http-client-python\alpha\client.tsp`)
5. Compile: `cd C:\dev\typespec\packages\http-client-python && npx tsp compile alpha/client.tsp`
6. If compilation fails, read the error, fix the code, and retry
7. Show the user the final compilable code

## Key Rules

- **Object values** use `#{}` syntax (TypeSpec compiler v1.9+): `@service(#{title: "MyService"})` NOT `@service({title: "MyService"})`
- **@error models** must use a literal status code: `@statusCode _: 500;` NOT `@statusCode code: int32;`
- **@visibility** uses `Lifecycle.Read` (capitalized) not `Lifecycle.read`
- **Azure.Core** does NOT have `Versions` member — do not use `@useDependency(Azure.Core.Versions.xxx)`
- **@resource** decorator is required on models used with `Azure.Core.ResourceOperations`
- Always include `@service(#{title: "..."})` decorator on the namespace
- Always include a top-level namespace declaration

## Target Path

- Default: `C:\dev\typespec\packages\http-client-python\alpha\client.tsp`
- If user specifies a different folder, use that instead
- Create the `alpha` directory if it doesn't exist

## Compilation

Run from `C:\dev\typespec\packages\http-client-python`:

```
npx tsp compile alpha/client.tsp
```

To also generate Python SDK output:

```
npx tsp compile alpha/client.tsp --emit @typespec/http-client-python
```

## Available Imports

See [references/templates.md](references/templates.md) for complete import/using patterns and compilable examples for both unbranded and Azure flavors.
