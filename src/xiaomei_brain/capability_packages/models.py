"""Schema for portable ``.xmcap`` capability packages."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


PACKAGE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
CAPABILITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class PackageIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=2, max_length=96)
    name: str = Field(..., min_length=1, max_length=120)
    version: str = Field(..., min_length=5, max_length=64)
    description: str = Field(default="", max_length=1000)
    publisher: str = Field(default="", max_length=160)
    license: str = Field(default="", max_length=80)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not PACKAGE_ID_PATTERN.fullmatch(value):
            raise ValueError("必须使用小写字母、数字、短横线或下划线")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not VERSION_PATTERN.fullmatch(value):
            raise ValueError("必须使用语义版本，例如 1.0.0")
        return value


class PackagedCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=96)
    name: str = Field(..., min_length=1, max_length=120)
    summary: str = Field(default="", max_length=500)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not CAPABILITY_ID_PATTERN.fullmatch(value):
            raise ValueError("必须使用稳定的小写能力 ID，不能包含点号")
        return value


class PackageRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    xiaomei_brain: str = Field(default="", max_length=80)
    python: str = Field(default="", max_length=80)
    python_packages: list[str] = Field(default_factory=list, max_length=100)
    node_packages: list[str] = Field(default_factory=list, max_length=100)
    executables: list[str] = Field(default_factory=list, max_length=100)


class CapabilityPackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(..., ge=1, le=1)
    package: PackageIdentity
    capabilities: list[PackagedCapability] = Field(..., min_length=1, max_length=50)
    permissions: dict[str, list[str]] = Field(default_factory=dict)
    requirements: PackageRequirements = Field(default_factory=PackageRequirements)
    contents: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        allowed = {"filesystem", "network", "process", "secrets"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"未知权限分类: {', '.join(unknown)}")
        for category, entries in value.items():
            if len(entries) > 100 or any(not item.strip() or len(item) > 300 for item in entries):
                raise ValueError(f"权限分类 {category} 包含无效条目")
        return value

    @field_validator("contents")
    @classmethod
    def validate_contents(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if len(value) > 30:
            raise ValueError("内容分类过多")
        if sum(len(items) for items in value.values()) > 500:
            raise ValueError("内容声明过多")
        return value

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "package": self.package.model_dump(),
            "capabilities": [item.model_dump() for item in self.capabilities],
            "permissions": [
                {"category": category, "value": item}
                for category, items in self.permissions.items()
                for item in items
            ],
            "requirements": self.requirements.model_dump(),
            "contents": {key: list(items) for key, items in self.contents.items()},
        }
