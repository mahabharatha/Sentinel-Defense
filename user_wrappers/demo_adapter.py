from whitebox_scan_platform.contracts import BaseScanAdapter, WrapperCapabilities

class DemoAdapter(BaseScanAdapter):
    def capabilities(self):
        return WrapperCapabilities(
            wrapper_id="demo_adapter",
            display_name="Demo Adapter",
            supports_blackbox=True,
            supports_whitebox=True,
            supports_api_models=True,
            supports_python_process_models=True,
            supports_art=True,
            supports_foolbox=True,
            supports_pyrit=True,
            supports_garak=True,
            supports_textattack=True,
            supports_logits=True,
            supports_gradients=True,
            supported_modalities=["audio", "multimodal"],
            supported_frameworks=["art", "foolbox", "pyrit", "garak", "textattack"],
            notes="Smoke test adapter"
        )

    def run_blackbox_scan(self, config):
        return {"status": "ok", "kind": "blackbox", "model": config["model"]["model_id"]}

    def run_whitebox_scan(self, config):
        return {"status": "ok", "kind": "whitebox", "frameworks": config["configuration"]["frameworks"]}

    def run_framework_scan(self, framework, config):
        return {"status": "ok", "framework": framework, "backend": config["configuration"]["execution_backend"]}
