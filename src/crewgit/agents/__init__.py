"""Agent adapters: mock, generic CLI, claude."""

from .base import Adapter, AgentResult, RunContext
from .registry import ADAPTERS, build_adapter

__all__ = ["Adapter", "AgentResult", "RunContext", "ADAPTERS", "build_adapter"]
