"""Proof certificate tests — generation on WriteOk and re-verification."""

from __future__ import annotations

import hashlib

from .gateway_client import (
    DomainSpec,
    InferenceChain,
    InferenceStep,
    MemoryEntry,
    MemoryIntent,
    MemoryState,
    Observation,
    PoisonPatterns,
    RuleKind,
    TetherGatewayClient,
    WriteResult,
    identity_rule,
    verify_certificate,
)


def _valid_intent(content: str = "GPU utilization at 87%") -> MemoryIntent:
    obs = Observation(source="test", content=content)
    step = InferenceStep(premises=[content], rule=identity_rule(), conclusion=content)
    chain = InferenceChain(steps=[step], final_conclusion=content)
    entry = MemoryEntry(key="observation_summary", content=content, source_trusted=True)
    return MemoryIntent(
        agent_id="test",
        observations=[obs],
        chain=chain,
        conclusion=entry,
        existing=MemoryState(),
        bound=2200,
        poison_patterns=PoisonPatterns(),
        domain_spec=DomainSpec(required_keys=["observation_summary"]),
    )


class TestCertificateGeneration:
    def test_write_ok_returns_certificate(self, gateway: TetherGatewayClient):
        resp = gateway.verify_write(_valid_intent())
        assert resp.result == WriteResult.WRITE_OK
        assert resp.certificate is not None

    def test_failed_write_has_no_certificate(self, gateway: TetherGatewayClient):
        intent = _valid_intent(content="x" * 2201)
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.BOUNDS_FAILED
        assert resp.certificate is None

    def test_certificate_trace_id_matches(self, gateway: TetherGatewayClient):
        intent = _valid_intent()
        resp = gateway.verify_write(intent)
        assert resp.certificate.trace_id == intent.conclusion.trace_id

    def test_certificate_content_hash_valid(self, gateway: TetherGatewayClient):
        content = "GPU utilization at 87%"
        resp = gateway.verify_write(_valid_intent(content))
        expected_hash = hashlib.sha256(content.encode()).hexdigest()
        assert resp.certificate.content_hash == expected_hash

    def test_certificate_records_rule(self, gateway: TetherGatewayClient):
        resp = gateway.verify_write(_valid_intent())
        assert resp.certificate.rule_used.kind == RuleKind.IDENTITY

    def test_certificate_records_all_properties(self, gateway: TetherGatewayClient):
        resp = gateway.verify_write(_valid_intent())
        expected = [
            "P1:inference_sound",
            "P2:consistent",
            "P3:not_poisoned",
            "P4:complete",
            "P5:bounds_ok",
            "P6:ownership",
        ]
        assert resp.certificate.properties_satisfied == expected

    def test_certificate_obs_count(self, gateway: TetherGatewayClient):
        resp = gateway.verify_write(_valid_intent())
        assert resp.certificate.obs_count == 1


class TestCertificateReverification:
    def test_reverification_passes_for_unmodified_entry(self, gateway: TetherGatewayClient):
        intent = _valid_intent()
        resp = gateway.verify_write(intent)
        assert verify_certificate(intent.conclusion, resp.certificate)

    def test_reverification_fails_for_tampered_entry(self, gateway: TetherGatewayClient):
        intent = _valid_intent()
        resp = gateway.verify_write(intent)
        tampered = MemoryEntry(
            key=intent.conclusion.key,
            content="TAMPERED CONTENT",
            source_trusted=True,
            trace_id=intent.conclusion.trace_id,
        )
        assert not verify_certificate(tampered, resp.certificate)
