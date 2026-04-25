# Tool Compatibility Layer

## Decision

Use a local adapter-first compatibility layer as the primary architecture.

Do not use MCP as the primary execution boundary for Foolbox, ART, Garak, PyRIT, or TextAttack right now.

## Logic

The orchestrator already runs a local API app with local executors, wrappers, files, templates, and reports. The problem we are solving is framework-version drift: CLI flags, imports, optional dependencies, attack APIs, and runtime capabilities change over time.

That problem is best solved close to the executor with a compatibility registry and per-framework adapters. MCP is a good future sidecar when we need remote workers, sandbox isolation, or cross-machine tool execution, but it adds process and protocol complexity before we need it.

## Architecture

```text
UI / API
  -> preflight and options
  -> compatibility registry
  -> framework executor
  -> framework-specific adapter/runner
  -> normalized reports and artifacts
```

## Phase Plan

Phase 1: Compatibility registry

- Add one registry for package names, import names, version risks, execution boundaries, and feature checks.
- Expose compatibility inventory through existing options/runtime responses.
- Preserve current executor behavior.
- Status: implemented.

Phase 2: Executor adoption

- Garak: keep version-safe CLI/function bridge and avoid unsupported flags.
- TextAttack: keep runtime-safe recipe downgrade and optional dependency checks.
- PyRIT: keep text and Vision-Language profiles separate and certified.
- ART: classify available attacks through wrapper capabilities.
- Foolbox: classify attack availability through model boundary and wrapper capabilities.
- Status: implemented at the run-metadata layer. Each framework result now carries `tool_compatibility` metadata without changing the underlying scan path.

Phase 3: Registry-based dispatch

- Route by `framework + backend + modality + task_family + scan_mode`.
- Keep the current support matrix as the user-facing source of truth.
- Keep per-framework executor internals hidden behind compatibility adapters.

Phase 4: Audit and reporting

- Include compatibility metadata in preflight and reports.
- Record package version, selected execution boundary, fallback decisions, and skipped/blocked capabilities.
- Keep normalized severity separate from original framework reports.

Phase 5: Optional MCP sidecar

- Add MCP only for remote or isolated workers.
- Do not make MCP responsible for scan semantics or severity decisions.
- Keep local adapters as the stable contract.

## Provenance Policy

Required copyright, license, attribution, and third-party notices must be preserved.

Product naming, UI, and architecture can evolve, but the project must not hide source provenance or remove required notices. This protects auditability and reduces legal risk.

## Framework Notes

| Framework | Primary Boundary | Version Risk | Compatibility Strategy |
| --- | --- | --- | --- |
| Foolbox | Wrapper-backed Python process | Attack/model APIs vary | Gate attacks by modality, logits, gradients, and wrapper tensor boundary |
| IBM ART | Wrapper-backed Python process | Estimator and attack requirements vary | Gate attacks by wrapper estimator capabilities |
| Garak | Built-in CLI runner | CLI flags and generator modules vary | Probe features, avoid unsupported flags, use function bridge when REST generator is absent |
| PyRIT | Built-in API runner | Class names and attack APIs vary | Keep certified profiles and scorer normalization |
| TextAttack | Built-in Python runner | Optional NLP dependencies vary | Use recipe aliases and runtime-safe constraint downgrade |
