"""P4: Completeness — tests that memory covers all critical observations
and contains all required keys.
"""

from __future__ import annotations

import pytest

from .gateway_client import (
    DomainSpec,
    InferenceChain,
    InferenceStep,
    MemoryEntry,
    MemoryIntent,
    MemoryState,
    Observation,
    PoisonPatterns,
    TetherGatewayClient,
    WriteResult,
    aggregation_rule,
    identity_rule,
)


def _make_completeness_intent(
    obs_contents: list[str],
    conclusion_content: str,
    existing_facts: list[MemoryEntry] | None = None,
    spec: DomainSpec | None = None,
    conclusion_key: str = "observation_summary",
) -> MemoryIntent:
    observations = [Observation(source="test", content=c) for c in obs_contents]
    if len(obs_contents) == 1 and conclusion_content == obs_contents[0]:
        rule = identity_rule()
    else:
        rule = aggregation_rule(source_premises=obs_contents)
    step = InferenceStep(premises=obs_contents, rule=rule, conclusion=conclusion_content)
    chain = InferenceChain(steps=[step], final_conclusion=conclusion_content)
    entry = MemoryEntry(key=conclusion_key, content=conclusion_content, source_trusted=True)
    existing = MemoryState(facts=existing_facts or [])
    if spec is None:
        spec = DomainSpec(required_keys=[conclusion_key])

    return MemoryIntent(
        agent_id="test-agent",
        observations=observations,
        chain=chain,
        conclusion=entry,
        existing=existing,
        bound=2200,
        poison_patterns=PoisonPatterns(),
        domain_spec=spec,
    )


class TestCriticalObservationCoverage:
    @pytest.mark.p4
    def test_single_critical_observation_covered(self, gateway: TetherGatewayClient):
        intent = _make_completeness_intent(
            obs_contents=["GPU utilization at 90%"],
            conclusion_content="GPU utilization at 90%",
            spec=DomainSpec(
                critical_patterns=["GPU"],
                required_keys=["observation_summary"],
            ),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK

    @pytest.mark.p4
    def test_critical_observation_not_covered(self, gateway: TetherGatewayClient):
        intent = _make_completeness_intent(
            obs_contents=["GPU utilization at 90%", "latency spike detected"],
            conclusion_content="GPU utilization at 90%",
            spec=DomainSpec(
                critical_patterns=["GPU", "latency"],
                required_keys=["observation_summary"],
            ),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.INCOMPLETE_COVERAGE

    @pytest.mark.p4
    def test_non_critical_observations_dont_require_coverage(self, gateway: TetherGatewayClient):
        intent = _make_completeness_intent(
            obs_contents=["temperature is 22C"],
            conclusion_content="temperature is 22C",
            spec=DomainSpec(
                critical_patterns=["GPU"],
                required_keys=["observation_summary"],
            ),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK

    @pytest.mark.p4
    def test_multiple_critical_all_covered(self, gateway: TetherGatewayClient):
        obs = [
            "GPU utilization at 90% latency",
            "latency p99 = 45ms error",
            "error rate 0.1%",
        ]
        content = "GPU utilization at 90% latency p99 = 45ms error rate 0.1%"
        intent = _make_completeness_intent(
            obs_contents=obs,
            conclusion_content=content,
            spec=DomainSpec(
                critical_patterns=["GPU", "latency", "error"],
                required_keys=["observation_summary"],
            ),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK

    @pytest.mark.p4
    def test_critical_covered_by_existing_fact(self, gateway: TetherGatewayClient):
        existing = [
            MemoryEntry(
                key="prior_obs",
                content="latency spike detected at 14:00",
                source_trusted=True,
            )
        ]
        intent = _make_completeness_intent(
            obs_contents=["GPU at 85%", "latency spike detected"],
            conclusion_content="GPU at 85%",
            existing_facts=existing,
            spec=DomainSpec(
                critical_patterns=["GPU", "latency"],
                required_keys=["observation_summary"],
            ),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK


class TestRequiredKeys:
    @pytest.mark.p4
    def test_required_key_present(self, gateway: TetherGatewayClient):
        intent = _make_completeness_intent(
            obs_contents=["data point"],
            conclusion_content="data point",
            spec=DomainSpec(required_keys=["observation_summary"]),
            conclusion_key="observation_summary",
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK

    @pytest.mark.p4
    def test_required_key_missing(self, gateway: TetherGatewayClient):
        intent = _make_completeness_intent(
            obs_contents=["data point"],
            conclusion_content="data point",
            spec=DomainSpec(required_keys=["observation_summary", "action_taken"]),
            conclusion_key="observation_summary",
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.INCOMPLETE_COVERAGE

    @pytest.mark.p4
    def test_required_key_in_existing_facts(self, gateway: TetherGatewayClient):
        existing = [
            MemoryEntry(
                key="action_taken",
                content="scaled replicas to 3",
                source_trusted=True,
            )
        ]
        intent = _make_completeness_intent(
            obs_contents=["data point"],
            conclusion_content="data point",
            existing_facts=existing,
            spec=DomainSpec(required_keys=["observation_summary", "action_taken"]),
            conclusion_key="observation_summary",
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK

    @pytest.mark.p4
    def test_no_required_keys_always_passes(self, gateway: TetherGatewayClient):
        intent = _make_completeness_intent(
            obs_contents=["anything"],
            conclusion_content="anything",
            spec=DomainSpec(required_keys=[]),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK


class TestEmptyDomainSpec:
    @pytest.mark.p4
    def test_empty_spec_always_complete(self, gateway: TetherGatewayClient):
        intent = _make_completeness_intent(
            obs_contents=["anything at all"],
            conclusion_content="anything at all",
            spec=DomainSpec(),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK

    @pytest.mark.p4
    def test_empty_observations_with_required_key(self, gateway: TetherGatewayClient):
        intent = _make_completeness_intent(
            obs_contents=["input"],
            conclusion_content="input",
            spec=DomainSpec(required_keys=["observation_summary"]),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK
