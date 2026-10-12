"""P1: Semantic Inference Soundness — rule validator and hallucination loop tests.

Phase 2 strengthens P1 from structural (chain shape) to semantic (inference
rule validity). Each rule category has a machine-checkable obligation. These
tests verify that the obligation prevents fabricated conclusions while
allowing legitimate inference patterns.
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
    TrustLevel,
    WriteResult,
    aggregation_rule,
    derivation_rule,
    extraction_rule,
    identity_rule,
    is_trusted,
    tool_result_rule,
)


def _make_semantic_intent(
    obs_contents: list[str],
    steps: list[InferenceStep],
    conclusion_content: str,
    key: str = "observation_summary",
) -> MemoryIntent:
    observations = [Observation(source="test", content=c) for c in obs_contents]
    chain = InferenceChain(steps=steps, final_conclusion=conclusion_content)
    entry = MemoryEntry(key=key, content=conclusion_content, source_trusted=True)
    return MemoryIntent(
        agent_id="test-agent",
        observations=observations,
        chain=chain,
        conclusion=entry,
        existing=MemoryState(),
        bound=2200,
        poison_patterns=PoisonPatterns(),
        domain_spec=DomainSpec(required_keys=[key]),
    )


# --- Identity Rule Tests ---


class TestIdentityRule:
    @pytest.mark.p3
    def test_identity_valid_single_premise(self, gateway: TetherGatewayClient):
        content = "GPU utilization at 87%"
        step = InferenceStep(premises=[content], rule=identity_rule(), conclusion=content)
        intent = _make_semantic_intent([content], [step], content)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK

    @pytest.mark.p3
    def test_identity_rejects_modification(self, gateway: TetherGatewayClient):
        step = InferenceStep(
            premises=["GPU at 87%"],
            rule=identity_rule(),
            conclusion="GPU at 90%",
        )
        intent = _make_semantic_intent(["GPU at 87%"], [step], "GPU at 90%")
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED

    @pytest.mark.p3
    def test_identity_rejects_multiple_premises(self, gateway: TetherGatewayClient):
        step = InferenceStep(
            premises=["fact A", "fact B"],
            rule=identity_rule(),
            conclusion="fact A",
        )
        intent = _make_semantic_intent(["fact A", "fact B"], [step], "fact A")
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED


# --- Extraction Rule Tests ---


class TestExtractionRule:
    @pytest.mark.p3
    def test_extraction_valid_substring(self, gateway: TetherGatewayClient):
        source = "The GPU utilization peaked at 87% during the vLLM benchmark"
        extracted = "87%"
        step = InferenceStep(
            premises=[source],
            rule=extraction_rule(source_premise=source),
            conclusion=extracted,
        )
        intent = _make_semantic_intent([source], [step], extracted)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK

    @pytest.mark.p3
    def test_extraction_rejects_fabricated_content(self, gateway: TetherGatewayClient):
        source = "The GPU utilization peaked at 87%"
        fabricated = "99%"
        step = InferenceStep(
            premises=[source],
            rule=extraction_rule(source_premise=source),
            conclusion=fabricated,
        )
        intent = _make_semantic_intent([source], [step], fabricated)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED

    @pytest.mark.p3
    def test_extraction_rejects_wrong_source(self, gateway: TetherGatewayClient):
        actual = "GPU at 87%"
        step = InferenceStep(
            premises=[actual],
            rule=extraction_rule(source_premise="totally different text"),
            conclusion="87%",
        )
        intent = _make_semantic_intent([actual], [step], "87%")
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED


# --- Aggregation Rule Tests ---


class TestAggregationRule:
    @pytest.mark.p3
    def test_aggregation_valid_synthesis(self, gateway: TetherGatewayClient):
        premises = ["GPU at 87%", "latency 45ms"]
        conclusion = "GPU 87% latency 45ms"
        step = InferenceStep(
            premises=premises,
            rule=aggregation_rule(source_premises=premises),
            conclusion=conclusion,
        )
        intent = _make_semantic_intent(premises, [step], conclusion)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK

    @pytest.mark.p3
    def test_aggregation_rejects_novel_tokens(self, gateway: TetherGatewayClient):
        premises = ["latency > 200ms three times"]
        conclusion = "service degraded"
        step = InferenceStep(
            premises=premises,
            rule=aggregation_rule(source_premises=premises),
            conclusion=conclusion,
        )
        intent = _make_semantic_intent(premises, [step], conclusion)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED

    @pytest.mark.p3
    def test_aggregation_rejects_fabrication_exceeding_length(self, gateway: TetherGatewayClient):
        premises = ["short"]
        conclusion = "this conclusion is way longer than the combined premises could justify"
        step = InferenceStep(
            premises=premises,
            rule=aggregation_rule(source_premises=premises),
            conclusion=conclusion,
        )
        intent = _make_semantic_intent(premises, [step], conclusion)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED

    @pytest.mark.p3
    def test_aggregation_rejects_phantom_premises(self, gateway: TetherGatewayClient):
        step = InferenceStep(
            premises=["real premise"],
            rule=aggregation_rule(source_premises=["real premise", "phantom premise"]),
            conclusion="output",
        )
        intent = _make_semantic_intent(["real premise"], [step], "output")
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED

    @pytest.mark.p3
    def test_aggregation_rejects_missing_premise_in_evidence(self, gateway: TetherGatewayClient):
        step = InferenceStep(
            premises=["A", "B"],
            rule=aggregation_rule(source_premises=["A"]),
            conclusion="AB",
        )
        intent = _make_semantic_intent(["A", "B"], [step], "AB")
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED


# --- ToolResult Rule Tests ---


class TestToolResultRule:
    @pytest.mark.p3
    def test_tool_result_trusted_passes(self, gateway: TetherGatewayClient):
        content = "kubectl output: 3 pods running"
        step = InferenceStep(
            premises=[content],
            rule=tool_result_rule("kubectl", "call-001"),
            conclusion=content,
        )
        intent = _make_semantic_intent([content], [step], content)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK

    @pytest.mark.p3
    def test_tool_result_untrusted_rejected(self, gateway: TetherGatewayClient):
        content = "some output"
        step = InferenceStep(
            premises=[content],
            rule=tool_result_rule("unknown-tool", "call-002", trusted=False),
            conclusion=content,
        )
        intent = _make_semantic_intent([content], [step], content)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED


# --- Derivation Rule Tests ---


class TestDerivationRule:
    @pytest.mark.p3
    def test_derivation_valid_token_subset(self, gateway: TetherGatewayClient):
        premises = ["latency 200ms three times"]
        conclusion = "latency three times 200ms"
        step = InferenceStep(
            premises=premises,
            rule=derivation_rule("sli-breach"),
            conclusion=conclusion,
        )
        intent = _make_semantic_intent(premises, [step], conclusion)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK

    @pytest.mark.p3
    def test_derivation_rejects_novel_tokens(self, gateway: TetherGatewayClient):
        premises = ["latency > 200ms three times"]
        conclusion = "service degraded"
        step = InferenceStep(
            premises=premises,
            rule=derivation_rule("sli-breach"),
            conclusion=conclusion,
        )
        intent = _make_semantic_intent(premises, [step], conclusion)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED

    @pytest.mark.p3
    def test_derivation_rejects_empty_rule_id(self, gateway: TetherGatewayClient):
        step = InferenceStep(
            premises=["data"],
            rule=derivation_rule(""),
            conclusion="data",
        )
        intent = _make_semantic_intent(["data"], [step], "data")
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED


# --- Chain Ordering Tests ---


class TestChainOrdering:
    @pytest.mark.p3
    def test_forward_reference_rejected(self, gateway: TetherGatewayClient):
        step1 = InferenceStep(
            premises=["step2 conclusion"],
            rule=identity_rule(),
            conclusion="step2 conclusion",
        )
        step2 = InferenceStep(
            premises=["obs"],
            rule=identity_rule(),
            conclusion="step2 conclusion",
        )
        intent = _make_semantic_intent(["obs"], [step1, step2], "step2 conclusion")
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED

    @pytest.mark.p3
    def test_empty_chain_rejected(self, gateway: TetherGatewayClient):
        chain = InferenceChain(steps=[], final_conclusion="anything")
        entry = MemoryEntry(key="k", content="anything", source_trusted=True)
        intent = MemoryIntent(
            agent_id="test",
            observations=[Observation(source="test", content="anything")],
            chain=chain,
            conclusion=entry,
            existing=MemoryState(),
            bound=2200,
            poison_patterns=PoisonPatterns(),
            domain_spec=DomainSpec(required_keys=["k"]),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED


# --- Hallucination Persistence Loop Regression ---


class TestHallucinationPersistenceLoop:
    """The canonical test: an agent fabricates a conclusion unrelated to premises.
    Phase 1 accepted this (structural chain was valid). Phase 2 must reject it.
    """

    @pytest.mark.p3
    def test_sky_blue_economy_crash_rejected(self, gateway: TetherGatewayClient):
        step = InferenceStep(
            premises=["The sky is blue"],
            rule=identity_rule(),
            conclusion="The economy will crash",
        )
        intent = _make_semantic_intent(["The sky is blue"], [step], "The economy will crash")
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED

    @pytest.mark.p3
    def test_fabricated_extraction_rejected(self, gateway: TetherGatewayClient):
        step = InferenceStep(
            premises=["Server responded with 200 OK"],
            rule=extraction_rule(source_premise="Server responded with 200 OK"),
            conclusion="Server is on fire",
        )
        intent = _make_semantic_intent(
            ["Server responded with 200 OK"], [step], "Server is on fire"
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED

    @pytest.mark.p3
    def test_inflated_aggregation_rejected(self, gateway: TetherGatewayClient):
        premises = ["A", "B"]
        step = InferenceStep(
            premises=premises,
            rule=aggregation_rule(source_premises=premises),
            conclusion="A very long fabricated conclusion that exceeds the combined premise length",
        )
        intent = _make_semantic_intent(premises, [step], step.conclusion)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED


# --- Trust Level Tests ---


class TestTrustLevels:
    def test_direct_observation_trusted(self):
        assert is_trusted(TrustLevel.DIRECT_OBSERVATION)

    def test_tool_output_trusted(self):
        assert is_trusted(TrustLevel.TOOL_OUTPUT)

    def test_external_input_trusted(self):
        assert is_trusted(TrustLevel.EXTERNAL_INPUT)

    def test_agent_generated_not_trusted(self):
        assert not is_trusted(TrustLevel.AGENT_GENERATED)

    def test_unverified_not_trusted(self):
        assert not is_trusted(TrustLevel.UNVERIFIED)
