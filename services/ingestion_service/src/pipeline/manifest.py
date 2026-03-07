from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from ..domain.errors import InvalidInputError, UnsupportedSourceError
from ..domain.models import Source


class ManifestDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = None
    platform: str | None = None
    chunking: dict[str, Any] | None = None


class ManifestSourceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = None
    platform: str | None = None
    external_id: str | None = None
    title: str
    source_url: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    raw_meta: dict[str, Any] | None = None

    text: str | None = None
    youtube_video_id: str | None = None

    @model_validator(mode="after")
    def _validate_modes(self) -> ManifestSourceItem:
        modes = [
            bool(self.text),
            bool(self.youtube_video_id),
        ]
        if sum(modes) != 1:
            raise InvalidInputError(
                "Each manifest source must set exactly one of: text, youtube_video_id"
            )

        if self.external_id is None or not str(self.external_id).strip():
            if self.youtube_video_id:
                self.external_id = self.youtube_video_id
            else:
                raise InvalidInputError("Missing external_id")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1", "2"]
    run_name: str | None = None
    defaults: ManifestDefaults | None = None
    sources: list[ManifestSourceItem]


def load_manifest(path: Path) -> Manifest:
    if not path.is_absolute():
        raise InvalidInputError("Manifest path must be absolute")
    if not path.exists():
        raise InvalidInputError(f"Manifest not found: {path}")

    raw: dict[str, Any]
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise InvalidInputError(
                "PyYAML is required for .yaml manifests. Install with `pip install PyYAML`."
            ) from exc
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    elif path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise InvalidInputError("Manifest must be .yaml/.yml or .json")

    try:
        return Manifest.model_validate(raw)
    except ValidationError as exc:
        raise InvalidInputError(f"Invalid manifest: {exc}") from exc


@dataclass(frozen=True, slots=True)
class ResolvedManifestSource:
    source: Source
    mode: Literal["text", "youtube"]
    text: str | None = None
    youtube_video_id: str | None = None


def resolve_manifest_sources(manifest: Manifest) -> list[ResolvedManifestSource]:
    defaults = manifest.defaults or ManifestDefaults()
    out: list[ResolvedManifestSource] = []

    for item in manifest.sources:
        user_id = item.user_id or defaults.user_id
        platform = item.platform or defaults.platform
        if not user_id:
            raise InvalidInputError("Missing user_id (set per-source or in defaults)")
        if not platform:
            raise InvalidInputError("Missing platform (set per-source or in defaults)")

        source = Source(
            user_id=user_id,
            platform=platform,
            external_id=str(item.external_id),
            title=item.title,
            source_url=item.source_url,
            author=item.author,
            published_at=item.published_at,
            raw_meta=item.raw_meta,
        )

        if item.text is not None:
            out.append(ResolvedManifestSource(source=source, mode="text", text=item.text))
        elif item.youtube_video_id is not None:
            out.append(
                ResolvedManifestSource(
                    source=source,
                    mode="youtube",
                    youtube_video_id=item.youtube_video_id,
                )
            )
        else:  # pragma: no cover
            raise UnsupportedSourceError("Unsupported manifest source input mode")

    return out
