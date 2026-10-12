"""Pytest fixtures for Project Tether tests."""

from __future__ import annotations

import pytest

from .gateway_client import (
    DomainSpec,
    MemoryState,
    PoisonPatterns,
    TetherGatewayClient,
)
from .owasp_asi06_vectors import DEFAULT_POISON_PATTERNS
from .run_fstar import FSTAR_EXE, verify_all


@pytest.fixture(scope="session")
def fstar_verified():
    """Verify all F* specs once per test session."""
    if not FSTAR_EXE.exists():
        pytest.skip(f"fstar.exe not found at {FSTAR_EXE}")
    results = verify_all()
    failures = [r for r in results if not r.success]
    if failures:
        details = "\n".join(f"  {r.file}: {r.stderr[:200]}" for r in failures)
        pytest.fail(f"F* verification failed:\n{details}")
    return results


@pytest.fixture
def gateway() -> TetherGatewayClient:
    return TetherGatewayClient()


@pytest.fixture
def default_poison_patterns() -> PoisonPatterns:
    return PoisonPatterns(**DEFAULT_POISON_PATTERNS)


@pytest.fixture
def empty_memory() -> MemoryState:
    return MemoryState()


@pytest.fixture
def basic_domain_spec() -> DomainSpec:
    return DomainSpec(
        critical_patterns=["GPU", "latency", "error"],
        required_keys=["observation_summary"],
    )
