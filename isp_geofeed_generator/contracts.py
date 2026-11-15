"""Version 1 of the public adapter contract. Keep imports lightweight."""
from dataclasses import dataclass
from typing import Callable, Protocol
from .locations import COARSE_FIELDS

ADAPTER_API_VERSION = 1


class Source(Protocol):
    def snapshot(self) -> dict: ...
    def for_publication(self, snapshot: dict) -> dict: ...


class Target(Protocol):
    def publish(self, payload: bytes | list[dict], state_dir, **guards) -> dict: ...


@dataclass(frozen=True)
class SourceAdapter:
    create: Callable
    initial: bool = True
    settings: frozenset = frozenset()
    api_version: int = ADAPTER_API_VERSION
    validate: Callable | None = None


@dataclass(frozen=True)
class TargetAdapter:
    create: Callable
    initial: bool = True
    settings: frozenset = frozenset()
    api_version: int = ADAPTER_API_VERSION
    payload_format: str = 'csv'
    location_fields: frozenset = COARSE_FIELDS
    required_fields: frozenset = COARSE_FIELDS

    def __call__(self, settings, credentials):
        return self.create(settings, credentials)
