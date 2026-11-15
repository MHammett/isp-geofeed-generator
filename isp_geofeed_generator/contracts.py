"""Version 1 of the public adapter contract. Keep imports lightweight."""
from dataclasses import dataclass
from typing import Callable, Protocol

ADAPTER_API_VERSION = 1


class Source(Protocol):
    def snapshot(self) -> dict: ...
    def for_publication(self, snapshot: dict) -> dict: ...


class Target(Protocol):
    def publish(self, csv: bytes, state_dir, **guards) -> dict: ...


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

    def __call__(self, settings, credentials):
        return self.create(settings, credentials)
