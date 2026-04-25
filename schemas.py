from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


ExecutionBackend = Literal["api_based", "python_process_wrapped"]
ScanMode = Literal["blackbox", "whitebox"]
FrameworkName = Literal["art", "foolbox", "pyrit", "garak", "textattack"]
ReportName = Literal["json", "html", "pdf", "xlsx", "txt_log"]
ModelSourceType = Literal["hf", "local", "url", "s3", "api"]
SAFE_WRAPPER_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$")
SAFE_CLASS_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class ModelSelection(BaseModel):
    model_id: str = Field(..., description="Display or registry key for the target model.")
    source_type: ModelSourceType = "hf"
    source_value: str = Field(..., description="Repo ID, path, URL, bucket/key, or API endpoint.")
    task_family: str = Field(..., description="ocr, captioning, vqa, speech-to-text, audio-classification, multimodal-chat, etc.")
    modality: str = Field(..., description="vision, audio, multimodal, text")

    @field_validator("model_id", "source_value", "task_family", "modality")
    @classmethod
    def validate_required_model_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned


class ScanConfiguration(BaseModel):
    execution_backend: ExecutionBackend
    scan_modes: list[ScanMode]
    frameworks: list[FrameworkName]
    reports: list[ReportName] = Field(default_factory=lambda: ["json", "html", "txt_log"])
    sample_path: str = ""
    min_samples: int = 1
    max_iter: int = 1
    batch_size: int = 1
    include_all_applicable_attacks: bool = True
    target_text: Optional[str] = None
    extra_options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scan_modes", "reports")
    @classmethod
    def validate_non_empty_lists(cls, value: list[Any]) -> list[Any]:
        if not value:
            raise ValueError("Select at least one option.")
        return value


class ScanJobCreate(BaseModel):
    job_name: str
    model: ModelSelection
    configuration: ScanConfiguration
    wrapper_id: Optional[str] = None

    @field_validator("job_name")
    @classmethod
    def validate_job_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned

    @field_validator("wrapper_id")
    @classmethod
    def validate_wrapper_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not SAFE_WRAPPER_ID_RE.fullmatch(cleaned):
            raise ValueError(
                "Wrapper ID must start with a letter, number, or underscore and contain only letters, numbers, underscores, or hyphens."
            )
        return cleaned


class JobTemplateCreate(BaseModel):
    template_name: str
    description: str = ""
    payload: ScanJobCreate


class JobTemplateUpdate(BaseModel):
    template_name: str
    description: str = ""
    payload: ScanJobCreate


class JobTemplateImport(BaseModel):
    template: dict[str, Any]
    template_name: Optional[str] = None
    description: Optional[str] = None


class JobTemplateRecord(BaseModel):
    template_id: str
    template_name: str
    description: str = ""
    created_at_utc: str
    updated_at_utc: str
    builtin: bool = False
    payload: dict[str, Any]


class WrapperRegistration(BaseModel):
    wrapper_id: str
    display_name: str
    class_name: str
    code: str
    supports_blackbox: bool = True
    supports_whitebox: bool = False
    supports_api_models: bool = True
    supports_python_process_models: bool = True
    supports_art: bool = False
    supports_foolbox: bool = False
    supports_pyrit: bool = False
    supports_garak: bool = False
    supports_giskard: bool = False
    supports_promptfoo: bool = False
    supports_textattack: bool = False
    supports_logits: bool = False
    supports_gradients: bool = False
    supported_modalities: list[str] = Field(default_factory=list)
    supported_task_families: list[str] = Field(default_factory=list)
    supported_frameworks: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("wrapper_id", "display_name", "class_name")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned

    @field_validator("wrapper_id")
    @classmethod
    def validate_safe_wrapper_id(cls, value: str) -> str:
        if not SAFE_WRAPPER_ID_RE.fullmatch(value):
            raise ValueError(
                "Wrapper ID must start with a letter, number, or underscore and contain only letters, numbers, underscores, or hyphens."
            )
        return value

    @field_validator("class_name")
    @classmethod
    def validate_safe_class_name(cls, value: str) -> str:
        if not SAFE_CLASS_NAME_RE.fullmatch(value):
            raise ValueError(
                "Class Name must be a valid Python identifier using letters, numbers, and underscores."
            )
        return value


class WrapperInfo(BaseModel):
    wrapper_id: str
    display_name: str
    class_name: str
    file_path: str
    capabilities: dict[str, Any]
    # Task 1: version info for the UI's Version column. `installed_versions` maps
    # framework name -> resolved version string ("" if the package isn't present).
    # `installed_version` is a convenience scalar for single-framework wrappers;
    # multi-framework wrappers expose "" here and rely on `installed_versions`.
    installed_versions: dict[str, str] = Field(default_factory=dict)
    installed_version: str = ""


class ScanJobRecord(BaseModel):
    job_id: str
    job_name: str
    status: str
    created_at_utc: str
    updated_at_utc: str
    wrapper_id: Optional[str] = None
    model: dict[str, Any]
    configuration: dict[str, Any]
    result: Optional[dict[str, Any]] = None
    errors: list[str] = Field(default_factory=list)
