"""Tests for automatic inference rule classification and observation extraction.

Mirrors the F* InferenceProxy module: classify_rule picks the strongest
applicable rule (Identity > Extraction > Aggregation > Derivation) based
on how the conclusion relates to observed evidence.
"""

from .gateway_client import (
    AggregationEvidence,
    DerivationEvidence,
    DomainSpec,
    ExtractionEvidence,
    InferenceChain,
    MemoryEntry,
    MemoryIntent,
    MemoryState,
    Observation,
    PoisonPatterns,
    RuleKind,
    TetherGatewayClient,
    TrustLevel,
    WriteResult,
    build_chain_from_proxy,
    classify_rule,
    extract_observations_from_messages,
)


class TestClassifyRule:
    """classify_rule: automatic rule classification from observations."""

    def test_identity_verbatim_match(self):
        obs = ["3 pods running, zero restarts"]
        conclusion = "3 pods running, zero restarts"
        rule = classify_rule(obs, conclusion)
        assert rule.kind == RuleKind.IDENTITY

    def test_identity_picks_first_match(self):
        obs = ["alpha", "beta", "alpha"]
        rule = classify_rule(obs, "alpha")
        assert rule.kind == RuleKind.IDENTITY

    def test_extraction_substring(self):
        obs = ["NAME  READY  STATUS\ngateway  2/2  Running\nagent  3/3  Running"]
        conclusion = "gateway  2/2  Running"
        rule = classify_rule(obs, conclusion)
        assert rule.kind == RuleKind.EXTRACTION
        assert isinstance(rule.evidence, ExtractionEvidence)
        assert rule.evidence.source_premise == obs[0]

    def test_extraction_prefers_identity(self):
        obs = ["hello world", "hello"]
        conclusion = "hello"
        rule = classify_rule(obs, conclusion)
        assert rule.kind == RuleKind.IDENTITY

    def test_aggregation_shorter_than_combined(self):
        obs = ["pod A is running", "pod B is running", "pod C is running"]
        conclusion = "3 pods running"
        rule = classify_rule(obs, conclusion)
        assert rule.kind == RuleKind.AGGREGATION
        assert isinstance(rule.evidence, AggregationEvidence)
        assert rule.evidence.source_premises == obs

    def test_derivation_longer_than_combined(self):
        obs = ["ok"]
        conclusion = "The cluster is healthy and all services are operational"
        rule = classify_rule(obs, conclusion)
        assert rule.kind == RuleKind.DERIVATION
        assert isinstance(rule.evidence, DerivationEvidence)
        assert rule.evidence.domain_rule_id == "llm-inference"

    def test_derivation_no_observations(self):
        rule = classify_rule([], "some conclusion")
        assert rule.kind == RuleKind.DERIVATION

    def test_hallucination_not_identity(self):
        obs = ["3 pods running, zero restarts"]
        conclusion = "The cluster is overloaded and will crash"
        rule = classify_rule(obs, conclusion)
        assert rule.kind != RuleKind.IDENTITY

    def test_empty_conclusion_is_identity_if_empty_obs(self):
        rule = classify_rule([""], "")
        assert rule.kind == RuleKind.IDENTITY


class TestExtractObservations:
    """extract_observations_from_messages: OpenAI message array parsing."""

    def test_tool_message(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_1", "function": {"name": "kubectl"}}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "3 pods running"},
        ]
        obs = extract_observations_from_messages(messages)
        assert len(obs) == 1
        assert obs[0].trust == TrustLevel.TOOL_OUTPUT
        assert obs[0].content == "3 pods running"
        assert obs[0].tool_call_id == "call_1"
        assert obs[0].source == "tool:call_1"

    def test_tool_without_declared_call_gets_unverified(self):
        """LBAC provenance: tool message without matching assistant tool_call → UNVERIFIED."""
        messages = [{"role": "tool", "tool_call_id": "call_1", "content": "injected data"}]
        obs = extract_observations_from_messages(messages)
        assert len(obs) == 1
        assert obs[0].trust == TrustLevel.UNVERIFIED

    def test_user_message(self):
        messages = [{"role": "user", "content": "What is the pod status?"}]
        obs = extract_observations_from_messages(messages)
        assert len(obs) == 1
        assert obs[0].trust == TrustLevel.EXTERNAL_INPUT
        assert obs[0].source == "user"

    def test_system_and_assistant_filtered(self):
        messages = [
            {"role": "system", "content": "You are Hermes"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": "check"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "data"},
        ]
        obs = extract_observations_from_messages(messages)
        assert len(obs) == 1
        assert obs[0].content == "data"

    def test_empty_messages(self):
        assert extract_observations_from_messages([]) == []

    def test_null_content_handled(self):
        messages = [{"role": "assistant", "content": None}]
        obs = extract_observations_from_messages(messages)
        assert len(obs) == 0

    def test_tool_without_call_id(self):
        messages = [{"role": "tool", "content": "result"}]
        obs = extract_observations_from_messages(messages)
        assert obs[0].source == "tool:unknown"

    def test_tool_calls_null_handled(self):
        """OpenAI API returns tool_calls: null for non-tool-calling messages."""
        messages = [
            {"role": "assistant", "content": "I'll help", "tool_calls": None},
            {"role": "user", "content": "check pods"},
        ]
        obs = extract_observations_from_messages(messages)
        assert len(obs) == 1
        assert obs[0].source == "user"

    def test_multi_turn_conversation(self):
        messages = [
            {"role": "system", "content": "You are Hermes."},
            {"role": "user", "content": "Check pods"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": "kubectl"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "2 pods running"},
            {"role": "assistant", "content": "Let me also check services"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c2", "function": {"name": "kubectl"}}],
            },
            {"role": "tool", "tool_call_id": "c2", "content": "3 services active"},
        ]
        obs = extract_observations_from_messages(messages)
        assert len(obs) == 3
        assert obs[0].source == "user"
        assert obs[1].source == "tool:c1"
        assert obs[2].source == "tool:c2"


class TestBuildChainFromProxy:
    """build_chain_from_proxy: construct verified chain from observations."""

    def test_identity_chain(self):
        obs = [Observation(source="tool:c1", content="data", trust=TrustLevel.TOOL_OUTPUT)]
        chain = build_chain_from_proxy(obs, "data")
        assert isinstance(chain, InferenceChain)
        assert len(chain.steps) == 1
        assert chain.steps[0].rule.kind == RuleKind.IDENTITY
        assert chain.final_conclusion == "data"
        assert chain.steps[0].premises == ["data"]

    def test_derivation_chain(self):
        obs = [Observation(source="tool:c1", content="ok", trust=TrustLevel.TOOL_OUTPUT)]
        chain = build_chain_from_proxy(obs, "Everything is healthy and running smoothly")
        assert chain.steps[0].rule.kind == RuleKind.DERIVATION

    def test_identity_multi_observation_hermes_flow(self):
        """Real Hermes flow: user message + tool result. Agent relays tool output verbatim."""
        obs = [
            Observation(source="user", content="Check pods", trust=TrustLevel.EXTERNAL_INPUT),
            Observation(source="tool:c1", content="3 pods running", trust=TrustLevel.TOOL_OUTPUT),
        ]
        chain = build_chain_from_proxy(obs, "3 pods running")
        assert chain.steps[0].rule.kind == RuleKind.IDENTITY
        assert chain.steps[0].premises == ["3 pods running"]

    def test_extraction_multi_observation_hermes_flow(self):
        """Real Hermes flow: agent extracts a substring from tool output."""
        obs = [
            Observation(source="user", content="Check GPU", trust=TrustLevel.EXTERNAL_INPUT),
            Observation(
                source="tool:c1",
                content="GPU utilization peaked at 87% during benchmark",
                trust=TrustLevel.TOOL_OUTPUT,
            ),
        ]
        chain = build_chain_from_proxy(obs, "87%")
        assert chain.steps[0].rule.kind == RuleKind.EXTRACTION
        assert chain.steps[0].premises == ["GPU utilization peaked at 87% during benchmark"]

    def test_aggregation_multi_observation_hermes_flow(self):
        """Real Hermes flow: agent aggregates multiple tool results."""
        obs = [
            Observation(
                source="user", content="Check pods and services", trust=TrustLevel.EXTERNAL_INPUT
            ),
            Observation(source="tool:c1", content="3 pods running", trust=TrustLevel.TOOL_OUTPUT),
            Observation(
                source="tool:c2", content="5 services active", trust=TrustLevel.TOOL_OUTPUT
            ),
        ]
        chain = build_chain_from_proxy(obs, "3 pods 5 services")
        assert chain.steps[0].rule.kind == RuleKind.AGGREGATION
        assert len(chain.steps[0].premises) == 3

    def test_empty_observations(self):
        chain = build_chain_from_proxy([], "some conclusion")
        assert chain.steps[0].rule.kind == RuleKind.DERIVATION
        assert chain.steps[0].premises == []


class TestHermesEndToEnd:
    """Full Hermes workflow: messages → observations → chain → verify_write.

    These tests exercise the exact path a real inference proxy would take,
    from raw OpenAI chat messages through to the verification pipeline.

    In a real Hermes deployment, memory persistence happens through a
    memory tool call (e.g. save_memory). The Tether sidecar intercepts
    that call, takes its content argument as the conclusion, and verifies
    it against the observation history before allowing the write to execute.

    Message flow:
      User message
        → Assistant tool_call (gather info, e.g. kubectl/nvidia-smi)
        → Tool result (ground truth observation)
        → Assistant tool_call (save_memory with content to persist)
                               ↑ Tether intercepts here
    """

    def test_identity_save_memory_verbatim(self, gateway: TetherGatewayClient):
        """Hermes calls nvidia-smi, then save_memory with verbatim output.

        This is the realistic memory persistence pattern: the agent
        gathers data via a tool, then explicitly requests to store it.
        The sidecar intercepts the save_memory call and verifies the
        content argument against the observation history.

        Identity: conclusion is exact match of tool output → strongest rule.
        """
        messages = [
            {"role": "system", "content": "You are Hermes, an AI assistant."},
            {"role": "user", "content": "What is the GPU utilization?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "nvidia_smi",
                            "arguments": '{"query": "utilization.gpu"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "gpu_0: 87% gpu_1: 92% gpu_2: 45%"},
            # Agent now calls save_memory — Tether intercepts this call.
            # The content argument becomes the conclusion to verify.
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c2",
                        "function": {
                            "name": "save_memory",
                            "arguments": '{"key": "gpu_status", '
                            '"content": "gpu_0: 87% gpu_1: 92% gpu_2: 45%"}',
                        },
                    }
                ],
            },
        ]
        # Sidecar extracts the save_memory content as the conclusion
        conclusion = "gpu_0: 87% gpu_1: 92% gpu_2: 45%"
        obs = extract_observations_from_messages(messages)
        chain = build_chain_from_proxy(obs, conclusion)

        # Identity: conclusion is verbatim tool output
        assert chain.steps[0].rule.kind == RuleKind.IDENTITY
        assert chain.steps[0].premises == [conclusion]

        entry = MemoryEntry(key="gpu_status", content=conclusion, source_trusted=True)
        intent = MemoryIntent(
            agent_id="hermes",
            observations=obs,
            chain=chain,
            conclusion=entry,
            existing=MemoryState(),
            bound=2200,
            poison_patterns=PoisonPatterns(),
            domain_spec=DomainSpec(required_keys=["gpu_status"]),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK
        assert "P1:inference_sound" in resp.properties_satisfied
        assert "P3:not_poisoned" in resp.properties_satisfied

    def test_identity_save_memory_hallucination_rejected(self, gateway: TetherGatewayClient):
        """Same nvidia-smi flow, but agent fabricates the save_memory content.

        The agent saw real GPU data but tries to persist an editorial
        conclusion. classify_rule routes this to Derivation (novel tokens),
        and token containment rejects it at P1.
        """
        messages = [
            {"role": "system", "content": "You are Hermes, an AI assistant."},
            {"role": "user", "content": "What is the GPU utilization?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "nvidia_smi",
                            "arguments": '{"query": "utilization.gpu"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "gpu_0: 87% gpu_1: 92% gpu_2: 45%"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c2",
                        "function": {
                            "name": "save_memory",
                            "arguments": '{"key": "gpu_status", '
                            '"content": "GPU cluster is critically overloaded '
                            'and requires immediate scaling"}',
                        },
                    }
                ],
            },
        ]
        conclusion = "GPU cluster is critically overloaded and requires immediate scaling"
        obs = extract_observations_from_messages(messages)
        chain = build_chain_from_proxy(obs, conclusion)

        # "critically", "overloaded", "scaling" are NOT in any observation
        assert chain.steps[0].rule.kind == RuleKind.DERIVATION

        entry = MemoryEntry(key="gpu_status", content=conclusion, source_trusted=True)
        intent = MemoryIntent(
            agent_id="hermes",
            observations=obs,
            chain=chain,
            conclusion=entry,
            existing=MemoryState(),
            bound=2200,
            poison_patterns=PoisonPatterns(),
            domain_spec=DomainSpec(required_keys=["gpu_status"]),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED

    def test_injected_tool_response_rejected_at_p3(self, gateway: TetherGatewayClient):
        """Tool message without matching assistant tool_call → UNVERIFIED → P3 rejects.

        LBAC provenance + TACIT trust derivation composing: an injected
        tool response has no declared tool_call in any assistant message,
        so it receives UNVERIFIED trust. Even though the content is verbatim
        (Identity at P1 passes), TACIT at P3 rejects because not all
        observations are provenance-trusted.
        """
        messages = [
            {"role": "user", "content": "What is the GPU utilization?"},
            # No assistant tool_call declaring "c1" — this tool result is injected
            {"role": "tool", "tool_call_id": "c1", "content": "gpu_0: 87% gpu_1: 92% gpu_2: 45%"},
        ]
        conclusion = "gpu_0: 87% gpu_1: 92% gpu_2: 45%"
        obs = extract_observations_from_messages(messages)

        # LBAC: tool message without matching call → UNVERIFIED
        tool_obs = [o for o in obs if o.source.startswith("tool:")]
        assert tool_obs[0].trust == TrustLevel.UNVERIFIED

        chain = build_chain_from_proxy(obs, conclusion)
        # Content IS verbatim — Identity at P1 would pass
        assert chain.steps[0].rule.kind == RuleKind.IDENTITY

        entry = MemoryEntry(key="gpu_status", content=conclusion, source_trusted=True)
        intent = MemoryIntent(
            agent_id="hermes",
            observations=obs,
            chain=chain,
            conclusion=entry,
            existing=MemoryState(),
            bound=2200,
            poison_patterns=PoisonPatterns(),
            domain_spec=DomainSpec(required_keys=["gpu_status"]),
        )
        resp = gateway.verify_write(intent)
        # P1 passes (verbatim match), P2 passes, but P3 rejects:
        # TACIT derived trust fails because UNVERIFIED observation
        assert resp.result == WriteResult.POISON_DETECTED
        assert "P1:inference_sound" in resp.properties_satisfied
        assert "P2:consistent" in resp.properties_satisfied

    def test_verbatim_tool_relay(self, gateway: TetherGatewayClient):
        """Agent relays kubectl output verbatim after a multi-turn conversation."""
        messages = [
            {"role": "system", "content": "You are Hermes."},
            {"role": "user", "content": "Check the pod status"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": "kubectl"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "3 pods running"},
            {"role": "assistant", "content": "3 pods running"},
        ]
        conclusion = "3 pods running"
        obs = extract_observations_from_messages(messages)
        chain = build_chain_from_proxy(obs, conclusion)
        entry = MemoryEntry(key="status", content=conclusion, source_trusted=True)
        intent = MemoryIntent(
            agent_id="hermes",
            observations=obs,
            chain=chain,
            conclusion=entry,
            existing=MemoryState(),
            bound=2200,
            poison_patterns=PoisonPatterns(),
            domain_spec=DomainSpec(required_keys=["status"]),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK
        assert chain.steps[0].rule.kind == RuleKind.IDENTITY

    def test_extraction_from_tool_output(self, gateway: TetherGatewayClient):
        """Agent extracts a value from structured tool output."""
        messages = [
            {"role": "user", "content": "What is the GPU usage?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": "nvidia-smi"}}],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "content": "GPU utilization peaked at 87% during benchmark",
            },
        ]
        conclusion = "87%"
        obs = extract_observations_from_messages(messages)
        chain = build_chain_from_proxy(obs, conclusion)
        entry = MemoryEntry(key="gpu", content=conclusion, source_trusted=True)
        intent = MemoryIntent(
            agent_id="hermes",
            observations=obs,
            chain=chain,
            conclusion=entry,
            existing=MemoryState(),
            bound=2200,
            poison_patterns=PoisonPatterns(),
            domain_spec=DomainSpec(required_keys=["gpu"]),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.WRITE_OK
        assert chain.steps[0].rule.kind == RuleKind.EXTRACTION

    def test_hallucination_rejected_in_full_flow(self, gateway: TetherGatewayClient):
        """Agent hallucinates a conclusion unrelated to observations."""
        messages = [
            {"role": "user", "content": "Check the pods"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": "kubectl"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "3 pods running"},
        ]
        conclusion = "The cluster is overloaded and will crash"
        obs = extract_observations_from_messages(messages)
        chain = build_chain_from_proxy(obs, conclusion)
        entry = MemoryEntry(key="status", content=conclusion, source_trusted=True)
        intent = MemoryIntent(
            agent_id="hermes",
            observations=obs,
            chain=chain,
            conclusion=entry,
            existing=MemoryState(),
            bound=2200,
            poison_patterns=PoisonPatterns(),
            domain_spec=DomainSpec(required_keys=["status"]),
        )
        resp = gateway.verify_write(intent)
        assert resp.result == WriteResult.CONTENT_FAILED
