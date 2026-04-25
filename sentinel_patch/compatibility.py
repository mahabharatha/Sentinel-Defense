from __future__ import annotations

import importlib.metadata
import importlib.util
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


FindSpec = Callable[[str], Any]


# ---------------------------------------------------------------------------
# Package specs — no upper caps; feature probing handles API differences
# ---------------------------------------------------------------------------

FRAMEWORK_PACKAGE_SPECS: dict[str, dict[str, str]] = {
    "art":        {"package": "adversarial-robustness-toolbox", "import": "art",        "min": "1.19.0"},
    "foolbox":    {"package": "foolbox",                        "import": "foolbox",    "min": "3.3.0"},
    "garak":      {"package": "garak",                          "import": "garak",      "min": "0.9.0"},
    "pyrit":      {"package": "pyrit",                          "import": "pyrit",      "min": "0.10.0"},
    "textattack": {"package": "textattack",                     "import": "textattack", "min": "0.3.10"},
}


@dataclass(frozen=True)
class FrameworkCompatibilityProfile:
    framework: str
    package_name: str
    import_name: str
    delivery: str
    execution_boundary: str
    adapter_strategy: str
    mcp_strategy: str
    python_requirement: str = ""
    notes: str = ""
    known_version_risks: list[str] = field(default_factory=list)
    optional_capabilities: dict[str, str] = field(default_factory=dict)
    provenance_policy: str = (
        "Preserve required copyright, license, attribution, and third-party notices. "
        "Product branding can change, but provenance must not be hidden."
    )


def framework_compatibility_profiles() -> dict[str, FrameworkCompatibilityProfile]:
    return {
        "art": FrameworkCompatibilityProfile(
            framework="art",
            package_name="adversarial-robustness-toolbox",
            import_name="art",
            delivery="bundled_python_dependency",
            execution_boundary="adapter_wrapped_python_process",
            adapter_strategy="Use wrapper capabilities for logits/gradients/model objects, then call ART attacks through the existing adapter path.",
            mcp_strategy="Not primary. MCP may later expose remote ART workers, but the local adapter remains the compatibility contract.",
            notes="Required for built-in ART executor and ART-capable wrappers.",
            known_version_risks=[
                "Attack availability and estimator requirements vary by ART version.",
                "White-box attacks require wrapper-provided gradients/logits or a compatible estimator.",
            ],
            optional_capabilities={
                "logits": "Improves reporting and attack selection when available.",
                "gradients": "Required for many white-box ART attacks.",
            },
        ),
        "foolbox": FrameworkCompatibilityProfile(
            framework="foolbox",
            package_name="foolbox",
            import_name="foolbox",
            delivery="bundled_python_dependency",
            execution_boundary="adapter_wrapped_python_process",
            adapter_strategy="Use wrapper-provided model boundary and current Foolbox vision-classification execution path.",
            mcp_strategy="Not primary. MCP would be useful only for isolated/remote model workers.",
            notes="Required for built-in Foolbox executor and Foolbox-capable wrappers.",
            known_version_risks=[
                "Attack constructors and distance/criterion APIs can vary by Foolbox version.",
                "Supported attacks depend on model modality and wrapper tensor boundary.",
            ],
            optional_capabilities={
                "logits": "Needed for classifier-oriented reporting.",
                "gradients": "Required for gradient-based white-box attacks.",
            },
        ),
        "pyrit": FrameworkCompatibilityProfile(
            framework="pyrit",
            package_name="pyrit",
            import_name="pyrit",
            delivery="bundled_python_dependency",
            execution_boundary="built_in_api_executor",
            adapter_strategy="Use the built-in PyRIT runner for text and certified Vision-Language prompt-sending profiles.",
            mcp_strategy="Not primary. MCP may later broker remote targets or isolated PyRIT environments.",
            python_requirement=">=3.10,<3.14",
            notes="Required for the built-in PyRIT API executor. Local model servers remain external infrastructure.",
            known_version_risks=[
                "PyRIT class names and attack APIs can change; runner uses subprocess isolation and feature probes.",
                "Multimodal support must stay limited to certified Vision-Language paths until broader media contracts exist.",
            ],
            optional_capabilities={
                "vision_language_seed": "Image plus text prompt path certified for local VLM smoke tests.",
                "objective_scorer": "Used to normalize outcome without trusting framework wording alone.",
            },
        ),
        "garak": FrameworkCompatibilityProfile(
            framework="garak",
            package_name="garak",
            import_name="garak",
            delivery="bundled_python_dependency",
            execution_boundary="built_in_cli_executor",
            adapter_strategy="Use a version-safe CLI/function bridge; probe for REST generator availability at runtime.",
            mcp_strategy="Not primary. MCP can later isolate long-running probe suites, not replace the compatibility contract.",
            notes="Required for built-in Garak API executor. Local model servers remain external infrastructure.",
            known_version_risks=[
                "Some Garak versions do not expose garak.generators.rest.",
                "Older Garak CLIs do not accept newer --generator_option_file or --narrow_output flags.",
                "Probe suites can be long-running; local model timeout and output caps must be explicit.",
            ],
            optional_capabilities={
                "rest_generator": "Use only when garak.generators.rest is available.",
                "function_single": "Fallback bridge for local Ollama and custom Python generator functions.",
            },
        ),
        "textattack": FrameworkCompatibilityProfile(
            framework="textattack",
            package_name="textattack",
            import_name="textattack",
            delivery="bundled_python_dependency",
            execution_boundary="built_in_python_process_runner",
            adapter_strategy="Use the built-in runner with certified recipe aliases and runtime-safe constraint downgrades.",
            mcp_strategy="Not primary. MCP may later isolate heavy NLP dependencies, but should not own scan semantics.",
            notes="First landing is limited to black-box text-classification over in-process models.",
            known_version_risks=[
                "Recipe constraints may require optional NLP packages or NLTK resources.",
                "Model/dataset loading behavior can change across TextAttack and Transformers versions.",
            ],
            optional_capabilities={
                "pos_tagger": "Needed for TextFooler POS constraints; removed safely when missing.",
                "semantic_similarity": "USE-based constraints require optional tensorflow_hub support.",
            },
        ),
    }


# ---------------------------------------------------------------------------
# Runtime version utilities
# ---------------------------------------------------------------------------

def _package_version(package_name: str) -> str:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _version_tuple(version_str: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple, ignoring non-numeric suffixes."""
    parts = []
    for part in version_str.split(".")[:3]:
        numeric = "".join(c for c in part if c.isdigit())
        parts.append(int(numeric) if numeric else 0)
    return tuple(parts)


def _meets_minimum(installed: str, minimum: str) -> bool:
    if not installed:
        return False
    try:
        return _version_tuple(installed) >= _version_tuple(minimum)
    except Exception:
        return True  # don't block on parse failure


# ---------------------------------------------------------------------------
# Runtime feature probing — replaces hard version checks
# ---------------------------------------------------------------------------

def _probe_garak_features() -> dict[str, Any]:
    """Probe garak capabilities at runtime without assuming a version."""
    features: dict[str, Any] = {
        "rest_generator_available": importlib.util.find_spec("garak.generators.rest") is not None,
        "ollama_function_bridge_available": True,
    }
    # Probe which CLI flags are accepted by the installed version
    try:
        result = subprocess.run(
            [sys.executable, "-m", "garak", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        help_text = result.stdout + result.stderr
        features["flag_generator_option_file"] = "--generator_option_file" in help_text
        features["flag_narrow_output"] = "--narrow_output" in help_text
        features["flag_report_prefix"] = "--report_prefix" in help_text
        features["flag_generations"] = "--generations" in help_text
        features["flag_eval_threshold"] = "--eval_threshold" in help_text
    except Exception:
        features["flag_generator_option_file"] = False
        features["flag_narrow_output"] = False
        features["flag_report_prefix"] = True
        features["flag_generations"] = True
        features["flag_eval_threshold"] = True
    return features


def _probe_textattack_features() -> dict[str, Any]:
    return {
        "runtime_safe_constraint_downgrade": True,
        "offline_cache_env_supported": True,
        "pos_tagger_available": importlib.util.find_spec("stanza") is not None
            or importlib.util.find_spec("flair") is not None,
        "tensorflow_hub_available": importlib.util.find_spec("tensorflow_hub") is not None,
    }


def _probe_pyrit_features() -> dict[str, Any]:
    return {
        "text_profile_available": True,
        "vision_language_profile_available": True,
        "subprocess_isolated": True,
    }


def _probe_art_features() -> dict[str, Any]:
    features: dict[str, Any] = {
        "wrapper_capability_driven": True,
        "requires_mode_specific_model_boundary": True,
    }
    # Probe for specific ART attack modules available in this version
    for module in ["art.attacks.evasion", "art.attacks.poisoning", "art.estimators"]:
        features[f"module_{module.replace('.', '_')}"] = importlib.util.find_spec(module) is not None
    return features


def _probe_foolbox_features() -> dict[str, Any]:
    features: dict[str, Any] = {
        "wrapper_capability_driven": True,
        "requires_mode_specific_model_boundary": True,
    }
    try:
        import foolbox  # noqa: F401
        # Probe attack availability without assuming version
        for attack in ["LinfPGD", "L2CarliniWagnerAttack", "LinfFastGradientAttack"]:
            module = importlib.util.find_spec(f"foolbox.attacks")
            features[f"attack_{attack}"] = module is not None
    except Exception:
        pass
    return features


def _feature_checks(framework: str, find_spec: FindSpec) -> dict[str, Any]:
    """Runtime feature probing — no version number comparisons."""
    if not (find_spec(FRAMEWORK_PACKAGE_SPECS.get(framework, {}).get("import", framework)) is not None
            or importlib.util.find_spec(FRAMEWORK_PACKAGE_SPECS.get(framework, {}).get("import", framework)) is not None):
        return {"installed": False}
    try:
        if framework == "garak":
            return _probe_garak_features()
        if framework == "textattack":
            return _probe_textattack_features()
        if framework == "pyrit":
            return _probe_pyrit_features()
        if framework == "art":
            return _probe_art_features()
        if framework == "foolbox":
            return _probe_foolbox_features()
    except Exception as exc:
        return {"probe_error": str(exc)}
    return {}


# ---------------------------------------------------------------------------
# Install support
# ---------------------------------------------------------------------------

def install_framework(framework: str) -> dict[str, Any]:
    """
    Install a framework package using pip into the active environment.
    Returns a result dict with status, stdout, stderr, returncode.
    Version-independent: installs latest compatible version with no upper cap.
    """
    spec = FRAMEWORK_PACKAGE_SPECS.get(framework)
    if spec is None:
        return {
            "framework": framework,
            "status": "error",
            "error": f"Unknown framework '{framework}'. Supported: {', '.join(FRAMEWORK_PACKAGE_SPECS)}",
        }

    package = f"{spec['package']}>={spec['min']}"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package, "--upgrade"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        installed_version = _package_version(spec["package"])
        return {
            "framework": framework,
            "package": spec["package"],
            "status": "installed" if result.returncode == 0 else "failed",
            "installed_version": installed_version,
            "returncode": result.returncode,
            "stdout": result.stdout[-3000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "framework": framework,
            "package": spec["package"],
            "status": "timeout",
            "error": "pip install timed out after 5 minutes.",
        }
    except Exception as exc:
        return {
            "framework": framework,
            "package": spec["package"],
            "status": "error",
            "error": repr(exc),
        }


def install_all_frameworks() -> dict[str, Any]:
    """Install all adversarial frameworks. Returns per-framework results."""
    results = {}
    for framework in FRAMEWORK_PACKAGE_SPECS:
        results[framework] = install_framework(framework)
    overall = "installed" if all(r["status"] == "installed" for r in results.values()) else "partial"
    return {"status": overall, "frameworks": results}


# ---------------------------------------------------------------------------
# Inventory and specs (unchanged API surface)
# ---------------------------------------------------------------------------

def framework_runtime_specs() -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for framework, profile in framework_compatibility_profiles().items():
        specs[framework] = {
            "package_name": profile.package_name,
            "import_name": profile.import_name,
            "delivery": profile.delivery,
            "python_requirement": profile.python_requirement,
            "notes": profile.notes,
        }
    return specs


def framework_compatibility_inventory(
    framework_order: list[str],
    *,
    find_spec: FindSpec | None = None,
) -> dict[str, dict[str, Any]]:
    finder = find_spec or importlib.util.find_spec
    profiles = framework_compatibility_profiles()
    inventory: dict[str, dict[str, Any]] = {}
    for framework in framework_order:
        profile = profiles.get(framework)
        if profile is None:
            continue
        installed = finder(profile.import_name) is not None if profile.import_name else True
        installed_version = _package_version(profile.package_name) if installed else ""
        spec = FRAMEWORK_PACKAGE_SPECS.get(framework, {})
        min_version = spec.get("min", "")
        version_ok = _meets_minimum(installed_version, min_version) if installed else False
        row = asdict(profile)
        row.update(
            {
                "installed": installed,
                "installed_version": installed_version,
                "minimum_version": min_version,
                "version_ok": version_ok,
                "feature_checks": _feature_checks(framework, finder) if installed else {},
                "installable": True,
            }
        )
        inventory[framework] = row
    return inventory


def framework_run_compatibility(
    framework: str,
    *,
    job_record: dict[str, Any] | None = None,
    decisions: dict[str, Any] | None = None,
    find_spec: FindSpec | None = None,
) -> dict[str, Any]:
    inventory = framework_compatibility_inventory([framework], find_spec=find_spec)
    row = dict(inventory.get(framework) or {})
    job_record = job_record or {}
    model = job_record.get("model") or {}
    config = job_record.get("configuration") or {}
    row["requested_shape"] = {
        "execution_backend": config.get("execution_backend", ""),
        "scan_modes": list(config.get("scan_modes") or []),
        "modality": model.get("modality", ""),
        "task_family": model.get("task_family", ""),
        "source_type": model.get("source_type", ""),
    }
    row["compatibility_decisions"] = decisions or {}
    return row


def attach_framework_compatibility(
    payload: dict[str, Any],
    framework: str,
    *,
    job_record: dict[str, Any] | None = None,
    decisions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = dict(payload)
    resolved["tool_compatibility"] = framework_run_compatibility(
        framework,
        job_record=job_record,
        decisions=decisions,
    )
    return resolved
