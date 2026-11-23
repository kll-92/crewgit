"""Adapter factory."""

from __future__ import annotations

from ..config import AgentConfig
from ..models import ContractError
from .base import Adapter
from .claude import ClaudeAdapter
from .generic import GenericAdapter
from .mock import MockAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    "mock": MockAdapter,
    "generic": GenericAdapter,
    "claude": ClaudeAdapter,
}


def build_adapter(config: AgentConfig) -> Adapter:
    adapter_class = ADAPTERS.get(config.adapter)
    if adapter_class is None:
        known = ", ".join(sorted(ADAPTERS))
        raise ContractError(f"unknown adapter '{config.adapter}' (known: {known})", detail={"field": "adapter"})
    return adapter_class(config)
