"""Mock Tether gateway client modeling the OpenShell sidecar → gateway call pattern.

In production:
  Agent (Python, inside OpenShell sandbox)
    → sidecar interceptor (port 50052)
      → Tether gateway (port 50051, gRPC)
        → F*/KaRaMeL verified write (native)

This module models the gRPC request/response as Python dataclasses,
allowing tests to exercise the verification logic without a running
cluster. The verified_write() function mirrors the F* VerifiedWrite
pipeline: P1 → P2 → P3 → P4 → P5 → P6.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum

# --- Observation Provenance ---


class TrustLevel(Enum):
    DIRECT_OBSERVATION = "DirectObservation"
    TOOL_OUTPUT = "ToolOutput"
    EXTERNAL_INPUT = "ExternalInput"
    AGENT_GENERATED = "AgentGenerated"
    UNVERIFIED = "Unverified"


def is_trusted(t: TrustLevel) -> bool:
    return t not in (TrustLevel.AGENT_GENERATED, TrustLevel.UNVERIFIED)


class WriteResult(Enum):
    WRITE_OK = "WriteOk"
    CONTENT_FAILED = "ContentFailed"
    POISON_DETECTED = "PoisonDetected"
    INCOMPLETE_COVERAGE = "IncompleteCoverage"
    BOUNDS_FAILED = "BoundsFailed"


# --- Inference Rule Evidence ---


@dataclass(frozen=True)
class ExtractionEvidence:
    source_premise: str


@dataclass(frozen=True)
class AggregationEvidence:
    source_premises: list[str]


@dataclass(frozen=True)
class ToolEvidence:
    tool_name: str
    call_id: str
    tool_trusted: bool = True


@dataclass(frozen=True)
class DerivationEvidence:
    domain_rule_id: str


# --- Inference Rule Catalog ---


class RuleKind(Enum):
    IDENTITY = "Identity"
    EXTRACTION = "Extraction"
    AGGREGATION = "Aggregation"
    TOOL_RESULT = "ToolResult"
    DERIVATION = "Derivation"


@dataclass(frozen=True)
class InferenceRule:
    kind: RuleKind
    evidence: (
        ExtractionEvidence | AggregationEvidence | ToolEvidence | DerivationEvidence | None
    ) = None


def identity_rule() -> InferenceRule:
    return InferenceRule(kind=RuleKind.IDENTITY)


def extraction_rule(source_premise: str) -> InferenceRule:
    return InferenceRule(kind=RuleKind.EXTRACTION, evidence=ExtractionEvidence(source_premise))


def aggregation_rule(source_premises: list[str]) -> InferenceRule:
    return InferenceRule(kind=RuleKind.AGGREGATION, evidence=AggregationEvidence(source_premises))


def tool_result_rule(tool_name: str, call_id: str, trusted: bool = True) -> InferenceRule:
    return InferenceRule(
        kind=RuleKind.TOOL_RESULT, evidence=ToolEvidence(tool_name, call_id, trusted)
    )


def derivation_rule(rule_id: str) -> InferenceRule:
    return InferenceRule(kind=RuleKind.DERIVATION, evidence=DerivationEvidence(rule_id))


# --- Automatic Rule Classification (mirrors F* InferenceProxy.classify_rule) ---


def classify_rule(obs_contents: list[str], conclusion: str) -> InferenceRule:
    """Classify the inference rule by comparing conclusion to observations.

    Picks the strongest applicable rule:
    Identity > Extraction > Aggregation > Derivation.
    """
    if any(o == conclusion for o in obs_contents):
        return identity_rule()
    matching = next((o for o in obs_contents if conclusion in o), None)
    if matching is not None:
        return extraction_rule(source_premise=matching)
    if len(conclusion) <= sum(len(o) for o in obs_contents):
        return aggregation_rule(source_premises=list(obs_contents))
    return derivation_rule(rule_id="llm-inference")


# --- Core Data Types ---


@dataclass(frozen=True)
class Observation:
    source: str
    content: str
    trust: TrustLevel = TrustLevel.DIRECT_OBSERVATION
    tool_call_id: str | None = None


@dataclass(frozen=True)
class InferenceStep:
    premises: list[str]
    rule: InferenceRule
    conclusion: str


@dataclass(frozen=True)
class InferenceChain:
    steps: list[InferenceStep]
    final_conclusion: str


@dataclass(frozen=True)
class MemoryEntry:
    key: str
    content: str
    source_trusted: bool
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class MemoryState:
    facts: list[MemoryEntry] = field(default_factory=list)


@dataclass(frozen=True)
class PoisonPatterns:
    instruction_overrides: list[str] = field(default_factory=list)
    role_escalations: list[str] = field(default_factory=list)
    exfiltration_markers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DomainSpec:
    critical_patterns: list[str] = field(default_factory=list)
    required_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryIntent:
    """Models gRPC VerifyWriteRequest from agent sidecar."""

    agent_id: str
    observations: list[Observation]
    chain: InferenceChain
    conclusion: MemoryEntry
    existing: MemoryState
    bound: int
    poison_patterns: PoisonPatterns
    domain_spec: DomainSpec


# --- Proof Witnesses ---


@dataclass(frozen=True)
class ProofCertificate:
    trace_id: str
    content_hash: str
    rule_used: InferenceRule
    properties_satisfied: list[str]
    timestamp: int
    obs_count: int


@dataclass(frozen=True)
class VerificationResponse:
    """Models gRPC VerifyWriteResponse back to agent sidecar."""

    result: WriteResult
    trace_id: str
    properties_satisfied: list[str]
    certificate: ProofCertificate | None = None


def verify_certificate(entry: MemoryEntry, cert: ProofCertificate) -> bool:
    """Check that a stored entry still matches its proof certificate."""
    content_hash = hashlib.sha256(entry.content.encode()).hexdigest()
    return cert.trace_id == entry.trace_id and cert.content_hash == content_hash


# --- Surface 2: Skill Verification (Dafny-as-IL pattern) ---


@dataclass(frozen=True)
class SkillSpec:
    name: str
    inputs: list[str]
    output_type: str
    max_body_size: int
    allowed_tools: list[str]


@dataclass(frozen=True)
class SkillCode:
    name: str
    body: str
    declared_inputs: list[str]
    declared_output: str
    tool_calls: list[str]


def skill_interface_valid(spec: SkillSpec, code: SkillCode) -> bool:
    return (
        code.name == spec.name
        and code.declared_inputs == spec.inputs
        and code.declared_output == spec.output_type
        and len(code.body) <= spec.max_body_size
    )


def skill_tools_within_scope(spec: SkillSpec, code: SkillCode) -> bool:
    return all(tc in spec.allowed_tools for tc in code.tool_calls)


def skill_safe_to_persist(spec: SkillSpec, code: SkillCode, pp: PoisonPatterns) -> bool:
    return (
        skill_interface_valid(spec, code)
        and skill_tools_within_scope(spec, code)
        and _content_safe(code.body, pp)
    )


# --- Surface 3: Tool Invocation Verification (P9/P10) ---


@dataclass(frozen=True)
class ToolDeclaration:
    name: str
    allowed_args: list[str]
    output_type: str
    side_effects: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolCallRecord:
    tool_name: str
    arguments: list[str]


@dataclass(frozen=True)
class ToolResult:
    output: str
    observed_side_effects: list[str] = field(default_factory=list)


def call_within_scope(decl: ToolDeclaration, call: ToolCallRecord) -> bool:
    return call.tool_name == decl.name and all(arg in decl.allowed_args for arg in call.arguments)


def side_effects_contained(decl: ToolDeclaration, call: ToolCallRecord, result: ToolResult) -> bool:
    return all(se in decl.side_effects for se in result.observed_side_effects)


def tool_invocation_safe(decl: ToolDeclaration, call: ToolCallRecord, result: ToolResult) -> bool:
    return call_within_scope(decl, call) and side_effects_contained(decl, call, result)


# --- Surface 4: Temporal Validity ---


@dataclass(frozen=True)
class TemporalCertificate:
    cert: ProofCertificate
    valid_from: int
    valid_until: int


def certificate_valid_at(tc: TemporalCertificate, current_time: int) -> bool:
    return tc.valid_from <= current_time <= tc.valid_until


def certificate_content_matches(cert: ProofCertificate, content_hash: str) -> bool:
    return cert.content_hash == content_hash


def certificate_reverify(tc: TemporalCertificate, content_hash: str, current_time: int) -> bool:
    return certificate_valid_at(tc, current_time) and certificate_content_matches(
        tc.cert, content_hash
    )


# --- Surface 5: Multi-Agent Proof Witness Transport ---


@dataclass(frozen=True)
class ProofWitness:
    source_agent: str
    content_hash: str
    rule_used: InferenceRule
    properties: list[str]
    obs_count: int
    source_trusted: bool


def witness_well_formed(witness: ProofWitness) -> bool:
    return (
        len(witness.source_agent) > 0
        and len(witness.content_hash) > 0
        and witness.obs_count > 0
        and witness.source_trusted
    )


def cross_agent_verify(witness: ProofWitness, stored_content_hash: str) -> bool:
    return witness_well_formed(witness) and witness.content_hash == stored_content_hash


def witness_has_minimum_properties(witness: ProofWitness, required: list[str]) -> bool:
    return all(req in witness.properties for req in required)


# --- Inference Proxy Helpers (mirrors F* InferenceProxy module) ---


def extract_observations_from_messages(messages: list[dict]) -> list[Observation]:
    """Extract observations from OpenAI chat completion messages array.

    LBAC provenance (Zhou et al.): tool results are only trusted when
    they match a declared tool_call in a preceding assistant message.
    Unmatched tool messages receive UNVERIFIED trust — the TACIT
    trust derivation in P3 will reject them.
    """
    declared_tool_calls: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                tc_id = tc.get("id", "")
                if tc_id:
                    declared_tool_calls.add(tc_id)

    observations = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content") or ""
        if role == "tool":
            call_id = msg.get("tool_call_id", "unknown")
            trust = (
                TrustLevel.TOOL_OUTPUT if call_id in declared_tool_calls else TrustLevel.UNVERIFIED
            )
            observations.append(
                Observation(
                    source=f"tool:{call_id}",
                    content=content,
                    trust=trust,
                    tool_call_id=msg.get("tool_call_id"),
                )
            )
        elif role == "user":
            observations.append(
                Observation(
                    source="user",
                    content=content,
                    trust=TrustLevel.EXTERNAL_INPUT,
                )
            )
    return observations


def build_chain_from_proxy(observations: list[Observation], conclusion: str) -> InferenceChain:
    """Build a verified inference chain from proxy-captured observations.

    Premises are selected per rule type to match each validator's
    structural requirements — Identity needs exactly one premise,
    Extraction needs the source premise, Aggregation/Derivation
    use all observations.
    """
    obs_contents = [o.content for o in observations]
    rule = classify_rule(obs_contents, conclusion)
    match rule.kind:
        case RuleKind.IDENTITY:
            premises = [conclusion]
        case RuleKind.EXTRACTION:
            premises = [rule.evidence.source_premise]
        case _:
            premises = obs_contents
    step = InferenceStep(premises=premises, rule=rule, conclusion=conclusion)
    return InferenceChain(steps=[step], final_conclusion=conclusion)


# --- Rule Validators ---


def _identity_valid(step: InferenceStep) -> bool:
    return len(step.premises) == 1 and step.conclusion == step.premises[0]


def _extraction_valid(step: InferenceStep, ev: ExtractionEvidence) -> bool:
    return ev.source_premise in step.premises and step.conclusion in ev.source_premise


def _aggregation_valid(step: InferenceStep, ev: AggregationEvidence) -> bool:
    return (
        all(p in step.premises for p in ev.source_premises)
        and all(sp in ev.source_premises for sp in step.premises)
        and len(step.conclusion) <= sum(len(p) for p in ev.source_premises)
        and _token_subset(step.premises, step.conclusion)
    )


def _tool_result_valid(_step: InferenceStep, ev: ToolEvidence) -> bool:
    return ev.tool_trusted


def _token_subset(premises: list[str], conclusion: str) -> bool:
    premise_words = set()
    for p in premises:
        premise_words.update(w for w in p.split(" ") if w)
    return all(w in premise_words for w in conclusion.split(" ") if w)


def _derivation_valid(step: InferenceStep, ev: DerivationEvidence) -> bool:
    return len(ev.domain_rule_id) > 0 and _token_subset(step.premises, step.conclusion)


def _rule_obligation_met(step: InferenceStep) -> bool:
    rule = step.rule
    match rule.kind:
        case RuleKind.IDENTITY:
            return _identity_valid(step)
        case RuleKind.EXTRACTION:
            return _extraction_valid(step, rule.evidence)
        case RuleKind.AGGREGATION:
            return _aggregation_valid(step, rule.evidence)
        case RuleKind.TOOL_RESULT:
            return _tool_result_valid(step, rule.evidence)
        case RuleKind.DERIVATION:
            return _derivation_valid(step, rule.evidence)
    return False


# --- Chain Well-Formedness (structural + semantic) ---


def _contains_substring_ci(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()


def _contains_any_pattern(content: str, patterns: list[str]) -> bool:
    return any(_contains_substring_ci(content, p) for p in patterns)


def _chain_well_formed(obs_contents: list[str], chain: InferenceChain) -> bool:
    if not chain.steps:
        return False
    known = set(obs_contents)
    for step in chain.steps:
        for premise in step.premises:
            if premise not in known:
                return False
        if not _rule_obligation_met(step):
            return False
        known.add(step.conclusion)
    last_step = chain.steps[-1]
    return last_step.conclusion == chain.final_conclusion


# --- P2: Consistency ---


def _no_contradiction(new_fact: MemoryEntry, existing: MemoryState) -> bool:
    for fact in existing.facts:
        if fact.key == new_fact.key and fact.content != new_fact.content:
            return False
    return True


# --- P3: Poisoning ---


def _content_safe(content: str, pp: PoisonPatterns) -> bool:
    return not (
        _contains_any_pattern(content, pp.instruction_overrides)
        or _contains_any_pattern(content, pp.role_escalations)
        or _contains_any_pattern(content, pp.exfiltration_markers)
    )


# --- P4: Completeness ---


def _is_critical(obs: Observation, spec: DomainSpec) -> bool:
    return any(p in obs.content for p in spec.critical_patterns)


def _covers(fact: MemoryEntry, obs: Observation) -> bool:
    return obs.content in fact.content


def _all_critical_covered(
    observations: list[Observation], memory: MemoryState, spec: DomainSpec
) -> bool:
    for obs in observations:
        if _is_critical(obs, spec):
            if not any(_covers(fact, obs) for fact in memory.facts):
                return False
    return True


def _required_keys_present(memory: MemoryState, spec: DomainSpec) -> bool:
    fact_keys = {f.key for f in memory.facts}
    return all(k in fact_keys for k in spec.required_keys)


def _memory_is_complete(
    observations: list[Observation], memory: MemoryState, spec: DomainSpec
) -> bool:
    return _all_critical_covered(observations, memory, spec) and _required_keys_present(
        memory, spec
    )


# --- Gateway Client ---


class TetherGatewayClient:
    """Mock client mirroring the Tether gRPC gateway verification pipeline.

    Pipeline: P1 → P2 → P3 → P4 → P5 → P6
    F* contract: specs/VerifiedWrite.fst (Pulse separation logic)

    P1  inference_sound     Chain well-formed + rule obligations met
    P2  consistent          No contradiction with existing memory
    P3  not_poisoned        Content safe (OWASP ASI06) + channel trust
                            + TACIT observation provenance trust
    P4  complete            Critical observations covered, required keys present
    P5  bounds_ok           Content within size bound
    P6  ownership           Write executes, certificate issued

    Observation trust is established upstream by extract_observations_from_messages
    via LBAC provenance validation (Zhou et al.): tool messages must match a
    declared tool_call in an assistant message to receive TOOL_OUTPUT trust.
    Unmatched tool messages receive UNVERIFIED trust, which TACIT at P3 rejects.
    """

    def __init__(self, endpoint: str = "localhost:50051"):
        self.endpoint = endpoint
        self._memory_store: dict[str, str] = {}

    def verify_write(self, intent: MemoryIntent) -> VerificationResponse:
        trace_id = intent.conclusion.trace_id
        satisfied: list[str] = []

        obs_contents = [o.content for o in intent.observations]
        p1 = _chain_well_formed(obs_contents, intent.chain)
        if not p1 or intent.chain.final_conclusion != intent.conclusion.content:
            return VerificationResponse(WriteResult.CONTENT_FAILED, trace_id, satisfied)
        satisfied.append("P1:inference_sound")

        p2 = _no_contradiction(intent.conclusion, intent.existing)
        if not p2:
            return VerificationResponse(WriteResult.CONTENT_FAILED, trace_id, satisfied)
        satisfied.append("P2:consistent")

        p3_safe = _content_safe(intent.conclusion.content, intent.poison_patterns)
        p3_channel = intent.conclusion.source_trusted
        # TACIT (Odersky et al.): derive trust from observation provenance.
        # Both declared channel trust AND derived provenance must hold.
        p3_provenance = all(is_trusted(o.trust) for o in intent.observations)
        if not (p3_safe and p3_channel and p3_provenance):
            return VerificationResponse(WriteResult.POISON_DETECTED, trace_id, satisfied)
        satisfied.append("P3:not_poisoned")

        updated_memory = MemoryState(facts=[intent.conclusion, *intent.existing.facts])
        p4 = _memory_is_complete(intent.observations, updated_memory, intent.domain_spec)
        if not p4:
            return VerificationResponse(WriteResult.INCOMPLETE_COVERAGE, trace_id, satisfied)
        satisfied.append("P4:complete")

        if len(intent.conclusion.content) > intent.bound:
            return VerificationResponse(WriteResult.BOUNDS_FAILED, trace_id, satisfied)
        satisfied.append("P5:bounds_ok")

        self._memory_store[intent.conclusion.key] = intent.conclusion.content
        satisfied.append("P6:ownership")

        cert = ProofCertificate(
            trace_id=trace_id,
            content_hash=hashlib.sha256(intent.conclusion.content.encode()).hexdigest(),
            rule_used=intent.chain.steps[-1].rule,
            properties_satisfied=list(satisfied),
            timestamp=0,
            obs_count=len(intent.observations),
        )
        return VerificationResponse(WriteResult.WRITE_OK, trace_id, satisfied, certificate=cert)
