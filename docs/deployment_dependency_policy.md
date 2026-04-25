# Deployment Dependency Policy

This document defines how framework runtimes and local model infrastructure are expected to be delivered for the platform.

## Policy Summary

The platform should distinguish between:

- bundled platform dependencies;
- optional or future framework dependencies;
- external inference infrastructure.

The current policy is:

- `ART`, `Foolbox`, `Garak`, and `PyRIT` should be installed during initial environment setup for a supported deployment.
- frameworks that are not yet wired into a real execution path should not be treated as required deployment dependencies.
- local inference servers such as `Ollama` remain external infrastructure even when the platform integrates with them.

## Bundled During Initial Setup

These dependencies are part of the platform runtime and should be installed as part of the environment bootstrap, image build, or deployment job:

- `adversarial-robustness-toolbox`
- `foolbox`
- `garak`
- `pyrit`

Why this group is bundled:

- the platform already exposes real or near-term committed execution paths for them;
- operators should not need to manually install framework packages after the app is deployed;
- preflight and runtime behavior become more predictable when the framework runtime is already present.

## Not Bundled As Required Platform Runtime

These should not be treated as mandatory deployment dependencies until a real execution path is shipped:

- `textattack`
- any future planned framework that is still UI-only or placeholder-only

Reason:

- shipping dormant dependencies increases install size, version pressure, and maintenance overhead without improving the user experience.

## External Infrastructure

These are intentionally outside the platform package and deployment runtime:

- `Ollama`
- any other local model server
- hosted provider endpoints
- model weights and caches that are downloaded or mounted separately

Reason:

- model serving is infrastructure, not a Python framework dependency;
- operators may choose different local or remote inference backends;
- some environments will use hosted APIs and some will use local inference.

## Operational Meaning

For a fresh supported deployment:

- installing the platform dependencies should make `ART`, `Foolbox`, `Garak`, and `PyRIT` immediately available;
- starting the web app should not require a separate manual install of those framework packages;
- using a local Ollama target may still require Ollama itself to be installed and running on the host.

## Recommended Delivery Model

Preferred order of implementation:

1. Pin required framework dependencies in the platform environment.
2. Install them during the standard setup path such as `pip install -r requirements.txt`, container image build, or deployment bootstrap.
3. Keep local model servers outside the app install, but document them clearly as external prerequisites when selected.
4. Fail preflight honestly when a required external service such as Ollama is not reachable.

## Non-Goals

This policy does not mean:

- the app should silently install Python packages on first launch;
- the app should install Ollama automatically;
- every framework listed in long-term roadmap material must be shipped in the base runtime today.

The current intent is reproducible deployment, not hidden runtime mutation.
