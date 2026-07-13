# SDK Smoke Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generated-code smoke-test framework to typespec-azure: a shared config pinning real spec-repo services, a language-agnostic shared helper (`smoke-test-common.ts`), and a Python `regenerate-smoke.ts` that regenerates those services and diff-checks against committed snapshots.

**Architecture:** A new workspace package `smoke-test/` at the repo root holds the config, the language-agnostic helpers (`loadConfig` / `fetchSpecs` / `checkDiff`), and — via its own `package.json` `dependencies` — provides node-module resolution for every TypeSpec library a real service imports (so specs resolve against the **monorepo workspace** versions, which is the whole point). The Python command `packages/typespec-python/eng/scripts/ci/regenerate-smoke.ts` calls the shared helpers, builds `TaskGroup[]`, and reuses `compileSpec`/`runParallel` from the existing `regenerate-common.ts` to emit into committed snapshots under `packages/typespec-python/smoke-test/generated/`.

**Tech Stack:** TypeScript run via `tsx`, `@typespec/compiler` (in-process `compile`), pnpm workspaces, vitest for the shared-package unit tests, git sparse-checkout for fetching specs.

---

## Working Environment

All implementation happens in the **git worktree** already created at
`C:\dev\wt-smoke-test` (branch `copilot/sdk-smoke-tests-impl`, based on
`origin/main`) — **not** in `C:\dev\typespec-azure`. All paths below are relative
to the worktree root unless stated otherwise.

## File Structure

**Create:**
- `smoke-test/package.json` — new workspace package `@azure-tools/typespec-python-smoke-test`; its `dependencies` provide TypeSpec-library resolution for fetched specs; `exports` maps to the TS source (resolved by `tsx`).
- `smoke-test/smoke-test-config.json` — pinned spec-repo commit + selected services.
- `smoke-test/smoke-test-common.ts` — shared helpers: `loadConfig`, `fetchSpecs`, `resolveEntrypoint`, `checkDiff`.
- `smoke-test/README.md` — service-selection criteria + how-to.
- `smoke-test/.gitignore` — ignores `.specs-cache/`.
- `smoke-test/vitest.config.ts` — vitest config for the unit tests.
- `smoke-test/test/smoke-test-common.test.ts` — unit tests for config parsing + entrypoint resolution.
- `smoke-test/test/fixtures/mini-service/main.tsp` — tiny local fixture service for the e2e test.
- `packages/typespec-python/eng/scripts/ci/regenerate-smoke.ts` — the Python generate + `--check` command.

**Modify:**
- `packages/typespec-python/package.json` — add `regenerate:smoke` script + `@azure-tools/typespec-python-smoke-test` devDependency (`workspace:^`).
- `pnpm-workspace.yaml` — add `smoke-test/` to the `packages:` list.

**Committed snapshots (generated, not hand-written):**
- `packages/typespec-python/smoke-test/generated/<service>/**`

---

## Task 1: Scaffold the `smoke-test` workspace package

**Files:**
- Modify: `pnpm-workspace.yaml`
- Create: `smoke-test/package.json`
- Create: `smoke-test/.gitignore`

- [ ] **Step 1: Add `smoke-test/` to the pnpm workspace**

Edit `pnpm-workspace.yaml`; add `smoke-test/` under `packages:` (keep the existing
entries):

```yaml
packages:
  - packages/*
  - packages/typespec-java/src/*
  - core/
  - website/
  - eng/feeds/
  - core/packages/*
  - smoke-test/
  - "!core/packages/http-client-csharp/**"
  - "!core/packages/http-client-java/**"
  - "!core/packages/http-client-python/**"
  - "!core/packages/typespec-vs"
```

- [ ] **Step 2: Create `smoke-test/package.json`**

The `dependencies` exist purely to make node resolve every library a real
service tsp may import against the workspace versions. Use `workspace:^` so pnpm
symlinks the in-repo packages into `smoke-test/node_modules`.

```json
{
  "name": "@azure-tools/typespec-python-smoke-test",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "description": "SDK generated-code smoke tests: shared config, spec fetch, and diff-check helpers.",
  "exports": {
    ".": "./smoke-test-common.ts"
  },
  "scripts": {
    "test": "vitest run"
  },
  "dependencies": {
    "@azure-tools/typespec-azure-core": "workspace:^",
    "@azure-tools/typespec-azure-resource-manager": "workspace:^",
    "@azure-tools/typespec-azure-rulesets": "workspace:^",
    "@azure-tools/typespec-client-generator-core": "workspace:^",
    "@azure-tools/typespec-python": "workspace:^",
    "@typespec/compiler": "workspace:^",
    "@typespec/http": "workspace:^",
    "@typespec/openapi": "workspace:^",
    "@typespec/rest": "workspace:^",
    "@typespec/versioning": "workspace:^"
  },
  "devDependencies": {
    "picocolors": "catalog:",
    "tsx": "catalog:",
    "vitest": "catalog:"
  }
}
```

> If `pnpm install` complains that `picocolors`/`tsx`/`vitest` are not in the
> catalog, replace `"catalog:"` with the version already used elsewhere in the
> repo (grep `pnpm-workspace.yaml` and existing `package.json`s for the pinned
> versions) — e.g. `"tsx": "^4.21.0"`.

- [ ] **Step 3: Create `smoke-test/.gitignore`**

```gitignore
# Fetched spec-repo checkouts are reproducible from smoke-test-config.json
.specs-cache/
```

- [ ] **Step 4: Install so the workspace links resolve**

Run (from the worktree root): `pnpm install`
Expected: completes without error.

Verify: `Test-Path smoke-test/node_modules/@azure-tools/typespec-azure-resource-manager`
Expected: `True` (a symlink into the workspace).

- [ ] **Step 5: Commit**

```bash
git add pnpm-workspace.yaml smoke-test/package.json smoke-test/.gitignore pnpm-lock.yaml
git commit -m "chore(smoke-test): scaffold smoke-test workspace package"
```

---

## Task 2: Add the smoke-test config and README

**Files:**
- Create: `smoke-test/smoke-test-config.json`
- Create: `smoke-test/README.md`

- [ ] **Step 1: Create `smoke-test/smoke-test-config.json`**

One pinned commit for all services. Compute is the first service.

```json
{
  "specRepo": "Azure/azure-rest-api-specs",
  "commit": "ea850a065dc8679f82dc3fdbba9ceff53eeba116",
  "services": [
    {
      "name": "compute-resource-manager",
      "specPath": "specification/compute/resource-manager/Microsoft.Compute/Compute",
      "scenarios": ["arm", "lro", "paging", "discriminator", "large-models"]
    }
  ]
}
```

- [ ] **Step 2: Create `smoke-test/README.md`**

````markdown
# SDK Generated-Code Smoke Tests

Regenerates a small set of **real** spec-repo services against the current
in-repo TypeSpec/TCGC/emitter code and fails when the generated SDK code drifts
from the committed baseline. This catches unintended generated-code changes from
upstream codegen changes early, in the PR that causes them.

## Config: `smoke-test-config.json`

- `commit` — a single `Azure/azure-rest-api-specs` commit that **all** services
  are fetched from. Bump deliberately; it produces one reviewable PR.
- `services[]` — `name` (snapshot folder), `specPath` (folder in the spec repo
  containing `main.tsp`/`client.tsp`), and `scenarios` (coverage metadata).

### Selection criteria
Pick services that together exercise the major generation paths: ARM + data-plane,
LRO, paging, discriminators/polymorphism, versioning, and large model graphs.
Compute is the primary ARM service (LRO + paging + discriminators + big models).

## Commands (Python)

```bash
# regenerate snapshots in place
pnpm --filter @azure-tools/typespec-python run regenerate:smoke

# regenerate + fail on any diff (CI)
pnpm --filter @azure-tools/typespec-python run regenerate:smoke -- --check
```

## Updating the baseline
Run the regenerate command and commit the changed
`packages/typespec-python/smoke-test/generated/**`. To move to newer specs,
change `commit` in the config, regenerate, and commit.

> CI triggering (when/where these run) is tracked in a separate issue.
````

- [ ] **Step 3: Commit**

```bash
git add smoke-test/smoke-test-config.json smoke-test/README.md
git commit -m "docs(smoke-test): add config and README"
```

---

## Task 3: Config loading + entrypoint resolution (TDD)

**Files:**
- Create: `smoke-test/smoke-test-common.ts`
- Create: `smoke-test/vitest.config.ts`
- Create: `smoke-test/test/smoke-test-common.test.ts`
- Create: `smoke-test/test/fixtures/mini-service/main.tsp`

- [ ] **Step 1: Create the vitest config**

`smoke-test/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    testTimeout: 30_000,
  },
});
```

- [ ] **Step 2: Create the fixture service (used by later tests too)**

`smoke-test/test/fixtures/mini-service/main.tsp`:

```tsp
import "@typespec/http";
import "@typespec/rest";

using Http;

@service(#{ title: "Mini Service" })
namespace MiniService;

model Widget {
  @key id: string;
  name: string;
  weight: int32;
}

@route("/widgets")
interface Widgets {
  @get list(): Widget[];
  @get get(@path id: string): Widget;
}
```

- [ ] **Step 3: Write the failing test**

`smoke-test/test/smoke-test-common.test.ts`:

```ts
import { mkdtemp, rm, writeFile } from "fs/promises";
import { tmpdir } from "os";
import { join, resolve } from "path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { loadConfig, resolveEntrypoint } from "../smoke-test-common";

describe("loadConfig", () => {
  let dir: string;
  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "smoke-cfg-"));
  });
  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it("parses a valid config", async () => {
    const path = join(dir, "cfg.json");
    await writeFile(
      path,
      JSON.stringify({
        specRepo: "Azure/azure-rest-api-specs",
        commit: "abc123",
        services: [{ name: "svc", specPath: "specification/x", scenarios: ["arm"] }],
      }),
    );
    const cfg = await loadConfig(path);
    expect(cfg.commit).toBe("abc123");
    expect(cfg.services).toHaveLength(1);
    expect(cfg.services[0].name).toBe("svc");
  });

  it("throws when a service is missing specPath", async () => {
    const path = join(dir, "cfg.json");
    await writeFile(
      path,
      JSON.stringify({ specRepo: "r", commit: "c", services: [{ name: "svc" }] }),
    );
    await expect(loadConfig(path)).rejects.toThrow(/specPath/);
  });

  it("throws when commit is missing", async () => {
    const path = join(dir, "cfg.json");
    await writeFile(path, JSON.stringify({ specRepo: "r", services: [] }));
    await expect(loadConfig(path)).rejects.toThrow(/commit/);
  });
});

describe("resolveEntrypoint", () => {
  it("returns main.tsp when only main.tsp exists", async () => {
    const fixture = resolve(__dirname, "fixtures/mini-service");
    expect(await resolveEntrypoint(fixture)).toBe(resolve(fixture, "main.tsp"));
  });

  it("throws when neither client.tsp nor main.tsp exists", async () => {
    const missing = resolve(__dirname, "fixtures/does-not-exist");
    await expect(resolveEntrypoint(missing)).rejects.toThrow(/no client.tsp or main.tsp/i);
  });
});
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `pnpm --filter @azure-tools/typespec-python-smoke-test run test`
Expected: FAIL — `Cannot find module '../smoke-test-common.js'` (file not created yet).

- [ ] **Step 5: Create `smoke-test/smoke-test-common.ts` with the minimal implementation**

```ts
/* eslint-disable no-console */
/**
 * Language-agnostic helpers for the SDK generated-code smoke tests.
 * Every language emitter's `regenerate-smoke` command calls these so config
 * parsing, spec fetching, and diff-checking are written once.
 */
import { access, readFile } from "fs/promises";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

export interface SmokeService {
  /** Snapshot folder name. */
  name: string;
  /** Folder inside the spec repo containing the tsp entrypoint. */
  specPath: string;
  /** Coverage metadata; not used by tooling. */
  scenarios?: string[];
}

export interface SmokeConfig {
  specRepo: string;
  /** One commit that ALL services are fetched from. */
  commit: string;
  services: SmokeService[];
}

async function exists(p: string): Promise<boolean> {
  return access(p).then(
    () => true,
    () => false,
  );
}

/** Absolute path to `smoke-test/smoke-test-config.json`. */
export function defaultConfigPath(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  return resolve(here, "smoke-test-config.json");
}

export async function loadConfig(path: string = defaultConfigPath()): Promise<SmokeConfig> {
  const raw = JSON.parse(await readFile(path, "utf8"));
  if (typeof raw.commit !== "string" || raw.commit.length === 0) {
    throw new Error(`smoke-test config ${path}: missing "commit"`);
  }
  if (!Array.isArray(raw.services)) {
    throw new Error(`smoke-test config ${path}: "services" must be an array`);
  }
  for (const [i, svc] of raw.services.entries()) {
    if (typeof svc.name !== "string" || svc.name.length === 0) {
      throw new Error(`smoke-test config ${path}: services[${i}] missing "name"`);
    }
    if (typeof svc.specPath !== "string" || svc.specPath.length === 0) {
      throw new Error(`smoke-test config ${path}: services[${i}] missing "specPath"`);
    }
  }
  return raw as SmokeConfig;
}

/**
 * Return the tsp entrypoint inside `serviceDir`, preferring `client.tsp` over
 * `main.tsp` (matching the regenerate harness).
 */
export async function resolveEntrypoint(serviceDir: string): Promise<string> {
  const client = resolve(serviceDir, "client.tsp");
  const main = resolve(serviceDir, "main.tsp");
  if (await exists(client)) return client;
  if (await exists(main)) return main;
  throw new Error(`smoke-test: no client.tsp or main.tsp in ${serviceDir}`);
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pnpm --filter @azure-tools/typespec-python-smoke-test run test`
Expected: PASS — all 5 tests green.

- [ ] **Step 7: Commit**

```bash
git add smoke-test/smoke-test-common.ts smoke-test/vitest.config.ts smoke-test/test/
git commit -m "feat(smoke-test): add loadConfig and resolveEntrypoint with tests"
```

---

## Task 4: Implement `fetchSpecs` (sparse checkout)

**Files:**
- Modify: `smoke-test/smoke-test-common.ts`
- Modify: `smoke-test/test/smoke-test-common.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `smoke-test/test/smoke-test-common.test.ts`:

```ts
import { resolveManifestForLocalDir } from "../smoke-test-common";

describe("resolveManifestForLocalDir", () => {
  it("builds a manifest entry pointing at the fixture entrypoint", async () => {
    const cacheRoot = resolve(__dirname, "fixtures");
    const manifest = await resolveManifestForLocalDir(cacheRoot, {
      name: "mini",
      specPath: "mini-service",
    });
    expect(manifest.name).toBe("mini");
    expect(manifest.entrypoint).toBe(resolve(cacheRoot, "mini-service/main.tsp"));
    expect(manifest.serviceDir).toBe(resolve(cacheRoot, "mini-service"));
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --filter @azure-tools/typespec-python-smoke-test run test`
Expected: FAIL — `resolveManifestForLocalDir` is not exported.

- [ ] **Step 3: Add the fetch code to `smoke-test/smoke-test-common.ts`**

Add these imports at the top (merge with the existing import block):

```ts
import { execFileSync } from "child_process";
import { mkdir, rm } from "fs/promises";
import { join } from "path";
```

Then append to the file:

```ts
export interface ServiceManifest {
  name: string;
  /** Absolute path to the fetched service directory. */
  serviceDir: string;
  /** Absolute path to the tsp entrypoint (client.tsp or main.tsp). */
  entrypoint: string;
}

/** Commit-keyed cache dir: `smoke-test/.specs-cache/<commit>`. */
export function cacheDirForCommit(commit: string): string {
  const here = dirname(fileURLToPath(import.meta.url));
  return resolve(here, ".specs-cache", commit);
}

/** Build a manifest entry from an already-present local service dir. */
export async function resolveManifestForLocalDir(
  cacheRoot: string,
  svc: SmokeService,
): Promise<ServiceManifest> {
  const serviceDir = resolve(cacheRoot, svc.specPath);
  const entrypoint = await resolveEntrypoint(serviceDir);
  return { name: svc.name, serviceDir, entrypoint };
}

/**
 * Sparse, shallow checkout of `config.commit` from the spec repo into
 * `smoke-test/.specs-cache/<commit>/`, pulling only the configured `specPath`s
 * plus shared `common-types`. Cached by commit SHA. Returns one manifest per
 * service. Requires `git` on PATH.
 */
export async function fetchSpecs(config: SmokeConfig): Promise<ServiceManifest[]> {
  const cacheDir = cacheDirForCommit(config.commit);
  const git = (args: string[]) =>
    execFileSync("git", args, { cwd: cacheDir, stdio: ["ignore", "ignore", "inherit"] });

  if (!(await exists(join(cacheDir, ".git")))) {
    await rm(cacheDir, { recursive: true, force: true });
    await mkdir(cacheDir, { recursive: true });
    const url = `https://github.com/${config.specRepo}.git`;
    git(["init", "--quiet"]);
    git(["remote", "add", "origin", url]);
    git(["sparse-checkout", "init", "--cone"]);
    const sparsePaths = [
      "specification/common-types",
      ...config.services.map((s) => s.specPath),
    ];
    git(["sparse-checkout", "set", ...sparsePaths]);
    git(["fetch", "--depth", "1", "origin", config.commit]);
    git(["checkout", "--quiet", "FETCH_HEAD"]);
  }

  const manifests: ServiceManifest[] = [];
  for (const svc of config.services) {
    manifests.push(await resolveManifestForLocalDir(cacheDir, svc));
  }
  return manifests;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm --filter @azure-tools/typespec-python-smoke-test run test`
Expected: PASS — the new `resolveManifestForLocalDir` test plus all prior tests.

- [ ] **Step 5: Commit**

```bash
git add smoke-test/smoke-test-common.ts smoke-test/test/smoke-test-common.test.ts
git commit -m "feat(smoke-test): add sparse-checkout fetchSpecs + manifest resolver"
```

---

## Task 5: Implement `checkDiff`

**Files:**
- Modify: `smoke-test/smoke-test-common.ts`
- Modify: `smoke-test/test/smoke-test-common.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `smoke-test/test/smoke-test-common.test.ts`:

```ts
import { execFileSync as execGit } from "child_process";
import { checkDiff } from "../smoke-test-common";

describe("checkDiff", () => {
  let repo: string;
  beforeEach(async () => {
    repo = await mkdtemp(join(tmpdir(), "smoke-diff-"));
    execGit("git", ["init", "-q"], { cwd: repo });
    execGit("git", ["config", "user.email", "t@t"], { cwd: repo });
    execGit("git", ["config", "user.name", "t"], { cwd: repo });
    await writeFile(join(repo, "snap.txt"), "baseline\n");
    execGit("git", ["add", "."], { cwd: repo });
    execGit("git", ["commit", "-qm", "baseline"], { cwd: repo });
  });
  afterEach(async () => {
    await rm(repo, { recursive: true, force: true });
  });

  it("returns clean=true when the snapshot dir is unchanged", async () => {
    const res = await checkDiff(repo, ".");
    expect(res.clean).toBe(true);
  });

  it("returns clean=false when the snapshot dir changed", async () => {
    await writeFile(join(repo, "snap.txt"), "changed\n");
    const res = await checkDiff(repo, ".");
    expect(res.clean).toBe(false);
    expect(res.diff).toContain("changed");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --filter @azure-tools/typespec-python-smoke-test run test`
Expected: FAIL — `checkDiff` is not exported.

- [ ] **Step 3: Add `checkDiff` to `smoke-test/smoke-test-common.ts`**

```ts
export interface DiffResult {
  clean: boolean;
  /** The `git diff` text (empty when clean). */
  diff: string;
}

/**
 * Diff-check the committed snapshot: returns `clean=false` if regeneration
 * produced any change (tracked or untracked) under `relSnapshotDir`, relative
 * to `repoRoot`. Mirrors the `check-for-changed-files` contract.
 */
export async function checkDiff(repoRoot: string, relSnapshotDir: string): Promise<DiffResult> {
  const runCapture = (args: string[]) =>
    execFileSync("git", args, { cwd: repoRoot, encoding: "utf8" });

  // Tracked changes.
  const tracked = runCapture(["diff", "--", relSnapshotDir]);
  // Untracked new files inside the snapshot dir.
  const untracked = runCapture([
    "ls-files",
    "--others",
    "--exclude-standard",
    "--",
    relSnapshotDir,
  ]);

  const diff = [tracked, untracked].filter((s) => s.trim().length > 0).join("\n");
  return { clean: diff.trim().length === 0, diff };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm --filter @azure-tools/typespec-python-smoke-test run test`
Expected: PASS — both `checkDiff` tests plus all prior tests.

- [ ] **Step 5: Commit**

```bash
git add smoke-test/smoke-test-common.ts smoke-test/test/smoke-test-common.test.ts
git commit -m "feat(smoke-test): add checkDiff diff-check helper"
```

---

## Task 6: Python `regenerate-smoke.ts` command

**Files:**
- Create: `packages/typespec-python/eng/scripts/ci/regenerate-smoke.ts`
- Modify: `packages/typespec-python/package.json`

- [ ] **Step 1: Confirm the reused symbols are exported from `regenerate-common.ts`**

Run: `Select-String -Path packages/typespec-python/eng/scripts/ci/regenerate-common.ts -Pattern "export (function toPosix|async function runParallel|interface CompileTask|interface TaskGroup|interface RegenerateContext)"`
Expected: five matches. (All are exported.)

- [ ] **Step 2: Add the npm script + devDependency**

In `packages/typespec-python/package.json`, add to `scripts`:

```json
    "regenerate:smoke": "tsx ./eng/scripts/ci/regenerate-smoke.ts",
```

and to `devDependencies`:

```json
    "@azure-tools/typespec-python-smoke-test": "workspace:^",
```

- [ ] **Step 3: Create `regenerate-smoke.ts`**

```ts
/* eslint-disable no-console */
/**
 * Regenerates Python SDK code for the real spec-repo services listed in
 * smoke-test-config.json and (optionally) fails on any diff vs the committed
 * snapshots under `packages/typespec-python/smoke-test/generated/`.
 *
 * Reuses the compile pipeline from `regenerate-common.ts`; the only new logic
 * is "config + fetched specs -> point the emitter at these specs / this output
 * folder".
 */
import { rmSync } from "fs";
import { dirname, resolve } from "path";
import pc from "picocolors";
import { fileURLToPath } from "url";
import { parseArgs } from "util";

import {
  checkDiff,
  fetchSpecs,
  loadConfig,
  type ServiceManifest,
} from "@azure-tools/typespec-python-smoke-test";

import {
  runParallel,
  toPosix,
  type CompileTask,
  type RegenerateContext,
  type TaskGroup,
} from "./regenerate-common.js";

const argv = parseArgs({
  args: process.argv.slice(2),
  options: {
    check: { type: "boolean" },
    name: { type: "string", short: "n" },
    debug: { type: "boolean", short: "d" },
    jobs: { type: "string", short: "j" },
  },
});

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
// eng/scripts/ci -> eng/scripts -> eng -> packageRoot
const PLUGIN_DIR = resolve(SCRIPT_DIR, "../../../");
const REPO_ROOT = resolve(PLUGIN_DIR, "../../"); // packages/typespec-python -> packages -> repoRoot
const SNAPSHOT_ROOT = resolve(PLUGIN_DIR, "smoke-test/generated");
const REL_SNAPSHOT = "packages/typespec-python/smoke-test/generated";

const ctx: RegenerateContext = {
  pluginDir: PLUGIN_DIR,
  // azureHttpSpecs / httpSpecs are unused for smoke specs (we set package-name
  // explicitly), but the type requires them.
  azureHttpSpecs: resolve(PLUGIN_DIR, "node_modules/@azure-tools/azure-http-specs/specs"),
  httpSpecs: resolve(PLUGIN_DIR, "node_modules/@typespec/http-specs/specs"),
  generatedFolder: resolve(PLUGIN_DIR, "generator"),
  emitterName: "@azure-tools/typespec-python",
};

function buildSmokeTaskGroups(manifests: ServiceManifest[], debug: boolean): TaskGroup[] {
  return manifests.map((m) => {
    const outputDir = toPosix(resolve(SNAPSHOT_ROOT, m.name));
    // Clear the output dir first so deletions are reflected in the diff.
    rmSync(outputDir, { recursive: true, force: true });
    const options: Record<string, unknown> = {
      flavor: "azure",
      "package-name": m.name,
      "emitter-output-dir": outputDir,
      "examples-dir": toPosix(resolve(m.serviceDir, "examples")),
      "generate-test": false,
      "generate-sample": false,
    };
    if (debug) options["debug"] = true;
    const task: CompileTask = { spec: m.entrypoint, outputDir, options };
    return { spec: m.entrypoint, tasks: [task] };
  });
}

async function main(): Promise<void> {
  const debug = argv.values.debug ?? false;
  const jobs = argv.values.jobs ? parseInt(argv.values.jobs, 10) : 4;

  const config = await loadConfig();
  const selected = argv.values.name
    ? { ...config, services: config.services.filter((s) => s.name.includes(argv.values.name!)) }
    : config;

  console.log(pc.cyan(`\nFetching ${selected.services.length} service(s) @ ${config.commit}`));
  const manifests = await fetchSpecs(selected);

  const groups = buildSmokeTaskGroups(manifests, debug);
  console.log(pc.cyan(`Regenerating ${groups.length} service(s) with ${jobs} jobs\n`));

  const results = await runParallel(groups, jobs, ctx);
  const failed = Array.from(results.values()).filter((v) => !v).length;
  if (failed > 0) {
    console.error(pc.red(`\nRegeneration failed for ${failed} service(s).`));
    process.exit(1);
  }
  console.log(pc.green(`\nRegeneration succeeded for ${groups.length} service(s).`));

  if (argv.values.check) {
    const { clean, diff } = await checkDiff(REPO_ROOT, REL_SNAPSHOT);
    if (!clean) {
      console.error(
        pc.red(
          `\nERROR: generated smoke-test code differs from the committed baseline.\n` +
            `Run "pnpm --filter @azure-tools/typespec-python run regenerate:smoke" and ` +
            `commit the changes under ${REL_SNAPSHOT}.\n`,
        ),
      );
      console.error(diff);
      process.exit(1);
    }
    console.log(pc.green("Diff check clean: snapshot matches generated output."));
  }
}

main().catch((err) => {
  console.error(pc.red(`\nUnexpected error: ${String(err)}`));
  process.exit(1);
});
```

- [ ] **Step 4: Reinstall so the new devDependency links**

Run (worktree root): `pnpm install`
Expected: completes; `Test-Path packages/typespec-python/node_modules/@azure-tools/typespec-python-smoke-test` is `True`.

- [ ] **Step 5: Commit**

```bash
git add packages/typespec-python/eng/scripts/ci/regenerate-smoke.ts packages/typespec-python/package.json pnpm-lock.yaml
git commit -m "feat(typespec-python): add regenerate-smoke command"
```

---

## Task 7: Build the emitter, generate the first snapshot, commit it

**Files:**
- Create (generated): `packages/typespec-python/smoke-test/generated/compute-resource-manager/**`

- [ ] **Step 1: Ensure the core submodule + build are ready in the worktree**

The `core` submodule and the emitter `dist` are required (in-process `compile`
loads the emitter from `PLUGIN_DIR`, and emitter TS changes need a build).

Run (worktree root):
```
git submodule update --init --recursive
pnpm install
pnpm --filter "@azure-tools/typespec-python..." build
pnpm --filter @azure-tools/typespec-python run prepare
```
Expected: all succeed. (`prepare` sets up the Python venv the emitter uses.)

- [ ] **Step 2: Generate the Compute snapshot**

Run: `pnpm --filter @azure-tools/typespec-python run regenerate:smoke`
Expected: `Regenerating 1 service(s)` then
`Regeneration succeeded for 1 service(s).` Files appear under
`packages/typespec-python/smoke-test/generated/compute-resource-manager/`.

If compilation fails with unresolved TypeSpec library imports, confirm
`smoke-test/node_modules/@azure-tools/typespec-azure-resource-manager` is a
symlink into the workspace (Task 1 Step 4). The fetched spec resolves its
imports by walking up into `smoke-test/node_modules`. If the fetched Compute
folder uses `client.tsp`, `resolveEntrypoint` already prefers it.

- [ ] **Step 3: Sanity-check the generated output**

Run: `Get-ChildItem -Recurse packages/typespec-python/smoke-test/generated/compute-resource-manager -Filter *.py | Select-Object -First 5`
Expected: several `.py` files (e.g. `_client.py`, `models/`, `operations/`).

- [ ] **Step 4: Commit the baseline snapshot**

```bash
git add packages/typespec-python/smoke-test/generated
git commit -m "test(smoke-test): add Compute baseline snapshot"
```

- [ ] **Step 5: Verify the diff-check passes against the committed baseline**

Run: `pnpm --filter @azure-tools/typespec-python run regenerate:smoke -- --check`
Expected: `Diff check clean: snapshot matches generated output.`

Run: `echo $LASTEXITCODE`
Expected: `0`

---

## Task 8: End-to-end guard test for the fetch cache short-circuit

**Files:**
- Modify: `smoke-test/test/smoke-test-common.test.ts`

Proves `fetchSpecs` resolves manifests from a present cache without cloning.

- [ ] **Step 1: Write the test**

Append to `smoke-test/test/smoke-test-common.test.ts`:

```ts
import { cacheDirForCommit, fetchSpecs } from "../smoke-test-common";
import { mkdir as mkdirp } from "fs/promises";

describe("fetchSpecs cache short-circuit", () => {
  it("returns one manifest per service when the cache already exists", async () => {
    const commit = "testcommit";
    const cacheDir = cacheDirForCommit(commit);
    await rm(cacheDir, { recursive: true, force: true });
    await mkdirp(join(cacheDir, ".git"), { recursive: true });
    await mkdirp(join(cacheDir, "mini-service"), { recursive: true });
    await writeFile(join(cacheDir, "mini-service", "main.tsp"), "// placeholder\n");

    const manifests = await fetchSpecs({
      specRepo: "r",
      commit,
      services: [{ name: "mini", specPath: "mini-service" }],
    });
    expect(manifests).toHaveLength(1);
    expect(manifests[0].name).toBe("mini");

    await rm(cacheDir, { recursive: true, force: true });
  });
});
```

- [ ] **Step 2: Run the full unit-test suite**

Run: `pnpm --filter @azure-tools/typespec-python-smoke-test run test`
Expected: PASS — all tests (loadConfig ×3, resolveEntrypoint ×2, manifest ×1,
checkDiff ×2, fetchSpecs ×1).

- [ ] **Step 3: Commit**

```bash
git add smoke-test/test/smoke-test-common.test.ts
git commit -m "test(smoke-test): guard fetchSpecs cache short-circuit"
```

---

## Task 9: Finalize and open the draft PR

- [ ] **Step 1: Run everything together**

Run:
```
pnpm --filter @azure-tools/typespec-python-smoke-test run test
pnpm --filter @azure-tools/typespec-python run regenerate:smoke -- --check
```
Expected: unit tests green; diff-check prints `Diff check clean`.

- [ ] **Step 2: Confirm the tree is clean and `.specs-cache` is ignored**

Run: `git status --short`
Expected: empty (no `.specs-cache/` listed; it is gitignored).

- [ ] **Step 3: Push the branch and open a draft PR**

```bash
git push msyyc copilot/sdk-smoke-tests-impl
gh pr create --repo Azure/typespec-azure --base main \
  --head msyyc:copilot/sdk-smoke-tests-impl --draft \
  --title "feat: SDK generated-code smoke tests (Python pilot) (#4720)" \
  --body "Implements docs/design/sdk-smoke-tests.md: shared smoke-test-common.ts (config/fetch/diff), Python regenerate-smoke.ts, and the Compute baseline snapshot. CI triggering deferred to a separate issue. Refs Azure/typespec-azure#4720"
```

---

## Notes & Risks

- **Library-version compatibility:** the pinned spec commit must compile against
  the current in-repo TypeSpec/TCGC/emitter versions. If a real service uses
  syntax newer/older than `main`, generation may error — that is a *signal*, but
  when it blocks the pilot, pick a spec commit known to compile against `main`
  and bump deliberately.
- **Snapshot size:** Compute is large. If the committed snapshot is unwieldy,
  narrow the emitted surface or swap to a smaller ARM service; this is an Open
  Question in the design.
- **`preprocess` / `prepareBaselineOfGeneratedCode` are intentionally NOT called** —
  they set up azure-http-specs marker files and the azure-sdk-for-python baseline
  respectively, which are irrelevant to smoke tests.
- **CI triggering is out of scope** (tracked separately). The recommended trigger
  mirrors core CI's `dorny/paths-filter` exclusion pattern.
- **`compileSpec` error cleanup:** on failure `compileSpec` removes the output
  dir, so a failed run leaves the previously-committed snapshot in place (git
  will show it deleted until you restore with `git checkout -- <dir>`).
