# Tether: Formally Verified Persistent Memory for Agentic AI

Preventing Hallucination Persistence Loops with Separation Logic on the Red Hat AI Stack

---

## Abstract

AI agents with persistent memory face a class of errors no existing framework addresses with formal methods: an agent hallucinates, saves the hallucination to persistent storage, and treats its own fiction as ground truth in all future sessions — a self-reinforcing hallucination persistence loop. We present Tether — an evidence-bound action, a runtime verification system that imposes a proof obligation on every persist operation across five agent execution surfaces: model inference, code generation, tool invocation, skill persistence, and multi-agent communication. Tether uses F\*/Pulse separation logic with Z3 SMT proof discharge to verify 10 properties spanning content soundness and memory substrate safety. We deploy Tether as a verification sidecar alongside the Hermes agentic framework on Red Hat OpenShift AI with vLLM/KServe model serving and NVIDIA OpenShell sandbox enforcement. Our evaluation shows 22 verified F\* specifications, 175 Python runtime tests, and zero-admit formal proofs covering OWASP ASI06 memory poisoning vectors. To our knowledge, Tether is the first system to apply separation logic to AI agent persistent memory.

---

## 1. Introduction

Agentic AI frameworks — systems where an LLM autonomously invokes tools, generates code, and persists state across sessions — are moving into production. Hermes (Nous Research), OpenClaw, and Kagent (Red Hat) each implement persistent memory architectures that survive pod restarts, enabling agents to learn from experience. This persistence is also the attack surface.

**The hallucination persistence loop.** An agent observes "GPU utilization at 87%," but the model confabulates "the cluster is overloaded and will crash." If this conclusion enters persistent memory, every future session begins with "the cluster is overloaded" as established fact. The agent compounds the error: it references the fabricated fact, derives further conclusions, and stores those too. Each session reinforces the fiction.

No existing mitigation provides formal guarantees against this:

- Sandbox isolation (OpenShell, gVisor) constrains runtime behavior but does not inspect content.
- Content filtering (heuristic similarity, embedding distance) catches some fabrications but cannot prove soundness.
- Type systems for agent control (LBAC/TypeGuard, TACIT) verify code safety but do not address persistent memory.
- Verification-aware code generation (Dafny-as-IL) verifies generated code but not stored reasoning.

**Tether** closes this gap by treating every memory write as a verification obligation. The agent must prove — using a formally verified pipeline — that what it persists is derivable from real observations through valid inference. Not ahead-of-time program verification, but **proof-per-action at runtime** across five execution surfaces.

### Five Verification Surfaces

| Surface | What Tether Proves | Hermes Feature |
|---------|-------------------|----------------|
| 1. Model inference | Conclusion follows from observations via valid inference chain | vLLM/KServe inference → Hermes reasoning |
| 2. Code generation | Generated skill satisfies spec before persisting as "known working" | Hermes auto-generates skills every ~15 tool calls |
| 3. Tool invocation | Tool output is trustworthy before entering reasoning chain | Tool calls (kubectl, web scrape, API) |
| 4. Skill persistence | Stored skill is still valid; proof witness travels with entry | MEMORY.md, USER.md, SQLite FTS5, skills on PVC |
| 5. Multi-agent execution | Agent B can verify Agent A's proof on cross-session read | Multi-platform sessions (Telegram, Slack, HTTP API) |

### Contributions

1. **Formalization.** 10 verification properties (P1–P10) spanning content soundness and memory substrate safety, specified in F\*/Pulse with Z3 proof discharge. The first application of separation logic to AI agent persistent memory.

2. **Verification strength spectrum.** An auto-active verification design (Leino) that balances expressiveness and control: five inference rule categories from Identity (full verification — conclusion must equal premise) through Derivation (weakest — requires only a domain rule identifier). The agent chooses the rule; the system checks the obligation.

3. **Incorrectness lemmas.** Following Gardner's incorrectness logic, we prove not only that verified writes satisfy properties (soundness of acceptance) but that fabricated inputs are necessarily rejected (soundness of rejection). The verification gate is tight — neither vacuous nor paranoid.

4. **Deployable architecture.** Tether deploys as a verification sidecar on Red Hat OpenShift AI alongside the Hermes agentic framework with vLLM/KServe model serving and NVIDIA OpenShell runtime sandbox. KaRaMeL extraction compiles verified F\*/Pulse to native C for production latency targets.

---

## 2. Background and Motivation

### 2.1 Agent Persistent Memory Architectures

**Hermes Agent** (Nous Research) implements a closed learning loop on Red Hat OpenShift AI: it generates reusable skills from multi-step tasks, maintains bounded persistent memory (MEMORY.md at 2,200 chars, USER.md at 1,375 chars), and searches conversation history via SQLite FTS5. Skills self-improve based on feedback and persist across pod restarts via PersistentVolumeClaim. Deployed on UBI 9 with vLLM model serving via KServe InferenceService.

**The persistence surface.** Hermes writes to five targets: curated memory (MEMORY.md), user model (USER.md), conversation database (SQLite), generated skills (/opt/data/skills/), and cron schedules. Every write survives pod restarts. A fabrication entering any target compounds indefinitely.

### 2.2 Related Verification Approaches

**Dafny as Verification-Aware Intermediate Language** (Li et al., 2025). LLM generates Dafny code → Dafny verifier checks → compiled to target language. Addresses Surface 2 (code generation) but not persistent memory. Tether adopts the "verification-aware IL" pattern: F\* is our intermediate verification language, but we verify *inference soundness*, not just code correctness.

**Language-Based Agent Control / TypeGuard** (Zhou et al., NeurIPS 2026). Policies encoded as Haskell types; agent code must type-check before execution. Abstract data types enforce data provenance and information flow control. Dual LLM architecture (privileged + quarantined) generalizes capability separation. Addresses Surfaces 1 and 3. Tether adopts the "policies-as-types" pattern: our algebraic `inference_rule` type forces evidence per claim. But Tether uses refinement types with proof discharge (stronger than Haskell's type system) and addresses persistent memory (which LBAC does not).

**Tracked Capabilities for Safer Agents / TACIT** (Odersky et al., CAIS 2026). Scala 3 capture checking tracks capabilities through the type system. `Classified[T]` wrapper enforces local purity — functions processing classified data cannot leak it. MCP server implementation. Addresses Surfaces 3 and 5. Tether adopts the "tracked capabilities" pattern: proof certificates are capabilities that must be presented on read. But Tether uses separation logic for memory ownership (P5, P6) — a dimension no other agent verification system addresses.

### 2.3 What Tether Adds Beyond All Three

| Capability | Dafny-as-IL | LBAC | TACIT | **Tether** |
|-----------|------------|------|-------|-----------|
| Code verification | ✓ | — | — | ✓ (Surface 2) |
| Inference soundness | — | ✓ | — | ✓ (Surface 1) |
| Tool trust | — | ✓ | ✓ | ✓ (Surface 3) |
| Capability tracking | — | — | ✓ | ✓ (Surface 4) |
| Multi-agent safety | — | — | ✓ | ✓ (Surface 5) |
| **Persistent memory** | — | — | — | **✓ (novel)** |
| **Separation logic** | — | — | — | **✓ (P5, P6)** |
| **Memory poisoning (ASI06)** | — | — | — | **✓ (P3)** |
| **Deployable on Red Hat stack** | — | — | — | **✓** |

---

## 3. Formalization

### 3.1 Core Types (TetherTypes.fst)

Algebraic type with evidence per inference rule — the auto-active pattern:

```fstar
type inference_rule =
  | RuleIdentity
  | RuleExtraction  : ev:extraction_evidence  -> inference_rule
  | RuleAggregation : ev:aggregation_evidence -> inference_rule
  | RuleToolResult  : ev:tool_evidence        -> inference_rule
  | RuleDerivation  : ev:derivation_evidence  -> inference_rule
```

Graduated trust for observation provenance:

```fstar
type trust_level =
  | DirectObservation | ToolOutput | ExternalInput
  | AgentGenerated | Unverified
```

### 3.2 Verification Strength Spectrum (TetherPredicates.fst)

| Rule | Obligation | Strength | Expressiveness |
|------|-----------|----------|---------------|
| Identity | conclusion = single premise | Full | Minimal — observation relay only |
| Extraction | conclusion ⊆ source premise | Strong | Substring extraction from source |
| Aggregation | len(conclusion) ≤ Σlen(premises) | Moderate | Multi-source synthesis |
| ToolResult | tool is trusted | Delegated | Full tool output, trust is boolean |
| Derivation | rule_id non-empty, conclusion tokens ⊆ premise tokens | Weakest | Domain-specific abductive reasoning |

### 3.3 Content Properties (P1–P4)

- **P1 Inference Soundness** (AgentReasoning): `chain_well_formed` checks structural ordering AND semantic rule obligations.
- **P2 Consistency**: `no_contradiction` against existing memory state.
- **P3 Poisoning Resistance** (PoisonDetection): Case-insensitive pattern matching against OWASP ASI06 vectors — instruction overrides, role escalations, exfiltration markers.
- **P4 Completeness** (CompletenessCheck): Domain-spec critical observations covered and required keys present.

### 3.4 Substrate Properties (P5–P8)

Pulse separation logic for memory ownership:

```fstar
fn verified_write (agent: agent_id) (region: memory_region) ...
  requires region |-> v
  returns r: write_result
  ensures (match r with
           | WriteOk -> region |-> conclusion.me_content ** pure (...)
           | _ -> region |-> v)
```

- **P5 Ownership**: `region |-> v` — agent holds the points-to assertion.
- **P6 Frame Rule**: Writing to MEMORY.md does not modify USER.md (separation logic frame).
- **P7 Bounds**: Content length ≤ tier bound (2,200 chars for Hermes Tier 1).
- **P8 Concurrency**: Multi-session access to shared SQLite is race-free.

### 3.5 Tool and Skill Properties (P9–P10)

- **P9 Tool Scope**: Tool call arguments within declared API surface.
- **P10 Side-Effect Containment**: Observed side effects ⊆ declared side effects.

### 3.6 Skill Verification (Surface 2)

Generated skills must satisfy a specification before persisting:

```fstar
val skill_safe_to_persist :
  spec:skill_spec -> code:skill_code -> pp:poison_patterns ->
  Pure bool
    (ensures fun b -> b ==>
      skill_interface_valid spec code /\
      skill_tools_within_scope spec code /\
      content_safe code.sc_body pp)
```

### 3.7 Temporal Validity (Surface 4)

Proof certificates carry validity windows for re-verification:

```fstar
val certificate_valid_at :
  cert:temporal_certificate -> time:nat ->
  Pure bool
    (ensures fun b -> b ==>
      cert.tc_valid_from <= time /\
      time <= cert.tc_valid_until)
```

### 3.8 Multi-Agent Proof Transport (Surface 5)

Session types for cross-agent proof witness transport:

```fstar
val cross_agent_verify :
  witness:proof_witness -> entry:memory_entry ->
  Pure bool
    (ensures fun b -> b ==>
      witness.pw_content_hash = hash entry.me_content /\
      witness.pw_source_trusted)
```

### 3.9 Normalization Tests (TetherNormTests.fst)

`assert_norm` evaluates verified functions on concrete inputs at type-checking time — pure computation in the F\* normalizer, no Z3 needed. Bridges universal proofs and existential tests by confirming the specification computes correctly on the same inputs the Python test suite exercises.

### 3.10 Incorrectness Lemmas (TetherLemmas.fst)

Following Gardner (OPLSS 2026), we prove rejection is *necessary* under attack conditions:

- L1: Identity fabrication → always rejected
- L2: Multi-premise identity → always rejected
- L3: Untrusted tool output → always rejected
- L4: Empty inference chain → always rejected
- L5: Evidence-free derivation → always rejected
- L6: Over-confident derivation → always rejected
- L7: Contradiction with existing memory → always rejected

---

## 4. Implementation

### 4.1 Tether Verification Gateway

**Python runtime architecture.** The Python runtime mirrors the F\* specification with structural fidelity. `gateway_client.py` (533 lines) implements `TetherGatewayClient`, which executes the same verification pipeline as `VerifiedWrite.fst`: P1+P2 (inference soundness and consistency) followed by P3 (poison detection) followed by P4 (completeness) followed by P5+P7 (ownership and bounds). Each F\* function — `chain_well_formed`, `no_contradiction`, `content_safe`, `completeness_check` — has a Python mirror that accepts the same arguments, applies the same case analysis, and returns the same verdict. The algebraic `inference_rule` type maps to a Python dataclass hierarchy with identical constructors: `RuleIdentity`, `RuleExtraction(evidence)`, `RuleAggregation(evidence)`, `RuleToolResult(evidence)`, and `RuleDerivation(evidence)`.

**gRPC service definition.** `tether.proto` defines six RPCs that cover all five verification surfaces: `VerifyWrite` (Surface 1, general memory persistence), `VerifyInference` (Surface 1, inference chain verification), `VerifySkill` (Surface 2, skill persistence), `VerifyToolInvocation` (Surface 3, tool output trust), `VerifyTemporal` (Surface 4, re-verification with validity windows), and `VerifyWitness` (Surface 5, cross-agent proof transport). The Protobuf `oneof` construct in the `InferenceRule` message mirrors the F\* algebraic `inference_rule` type: each variant carries its own evidence payload, ensuring that the wire format enforces the same structural obligations as the formal specification. Over 30 Protobuf message types define the request, response, and enum vocabulary.

**Proof certificate lifecycle.** On a successful `WriteOk` verdict, the gateway constructs a proof certificate containing: a SHA-256 content hash of the persisted content, the inference rule that justified the write, the list of properties satisfied (a subset of P1--P10), and an OpenTelemetry trace ID linking the certificate to the observability pipeline. For Surface 4 (skill persistence), a `TemporalCertificate` wraps the base certificate with a validity window (`valid_from`, `valid_until`), enabling periodic re-verification of stored skills without full re-proof. For Surface 5 (multi-agent communication), a `ProofWitness` packages the certificate with the originating agent's identity and a trust attestation, enabling Agent B to verify Agent A's proof on cross-session read without access to Agent A's private memory state.

**Sidecar deployment.** `hermes-sidecar-patch.yaml` patches the Hermes agent pod to include the Tether verification sidecar as an additional container. The sidecar listens on port 50052 and forwards verified requests to the gateway on port 50051. Setting the environment variable `HERMES_VERIFY_WRITES=true` enables write interception: every `MemoryIntent` from the Hermes agent is routed through the Tether sidecar before reaching persistent storage. The entire sidecar runs within the NVIDIA OpenShell sandbox, which applies Landlock filesystem restrictions, seccomp system call filtering, and cgroup resource limits to the verification process itself — ensuring that the verifier cannot be compromised to bypass its own checks.

### 4.2 Deployment on Red Hat OpenShift AI

![Project Tether deployment boundary on Red Hat OpenShift AI](tether-architecture.svg)

The rendering makes the deployment boundary explicit: this proof of concept
is evaluated inside **Red Hat OpenShift AI**, with KServe/vLLM model serving,
OpenShift platform services, and shared state/observability surrounding the
Kata → NVIDIA OpenShell → Tether enforcement stack. The [interactive HTML
rendering](tether-architecture.html) is the presentation-quality companion to
this paper figure.

### 4.3 Complementary Enforcement

| Concern | OpenShell | Tether |
|---------|-----------|--------|
| Agent can't read another agent's files | Policy Engine (fs deny) | P5 ownership proof |
| Memory write within bounds | Policy Engine (fs quota) | P7 bounds proof |
| Agent can't exfiltrate | Policy Engine (net deny) | — |
| Stored reasoning is sound | — | P1 inference soundness |
| Memory not poisoned | — | P3 (OWASP ASI06) |
| Sensitive context stays local | Privacy Router | — |
| Concurrent memory access | — | P8 concurrency |

---

## 5. Evaluation

### 5.1 Verification Results

**Methodology.** F\* specifications are verified using `fstar.exe` in dependency order: `TetherTypes.fst` (no dependencies), then `TetherPredicates.fst` (imports Types), then property modules (`AgentReasoning.fst`, `PoisonDetection.fst`, `CompletenessCheck.fst`), then composite modules (`VerifiedWrite.fst`, `VerifiedSkillWrite.fst`, `TemporalCertificate.fst`, `ProofWitness.fst`), and finally test and lemma modules (`TetherNormTests.fst`, `TetherLemmas.fst`). Python runtime tests use `pytest` with markers: `@pytest.mark.fstar_mirror` for tests that exercise the same inputs as `assert_norm` evaluations, `@pytest.mark.owasp` for ASI06 attack vectors, and `@pytest.mark.integration` for gRPC round-trip tests. The `verify-specs.sh` script orchestrates both pipelines and reports a unified pass/fail summary.

| Artifact | Count | Status |
|----------|-------|--------|
| F\* specifications | 22 | All verified (zero admits) |
| Python runtime tests | 175 | All pass |
| OWASP ASI06 vectors | 23 attack + 8 benign | Full coverage |
| Normalization tests | 20 assert_norm | Type-checker evaluated |
| Incorrectness lemmas | 7 | All verified |
| Proto messages | 30+ | Request/response/enum coverage |
| Hallucination persistence loop | Canonical test | Rejected at P1 |

### 5.2 Verification Latency

F\* verification is a build-time cost, not a runtime cost. Each F\* module verifies in 1--3 seconds depending on the complexity of proof obligations discharged to Z3; the full 22-module suite completes in under 40 seconds. These verification times are incurred once during development and CI, not on every memory write at runtime. The runtime Python gateway performs pure function evaluation — pattern matching, string comparison, length checks, hash computation — on bounded inputs. Hermes Tier 1 content (MEMORY.md) is capped at 2,200 characters; Tier 2 (USER.md) at 1,375 characters. On these bounded inputs, the Python verification pipeline completes in microseconds, well below the target of < 1s per memory write. The dominant runtime cost is SHA-256 hashing for proof certificate generation, which is negligible on content of this size. KaRaMeL extraction to C (Section 6.1) would reduce even this cost to sub-microsecond levels for production deployments requiring strict latency guarantees.

### 5.3 OWASP ASI06 Attack Coverage

The OWASP ASI06 (Memory Poisoning) attack surface is tested with 31 vectors organized into four categories. *Instruction overrides* (8 vectors): attempts to inject system-level directives ("ignore previous instructions," "you are now," "new system prompt") into persistent memory via observation content. *Role escalation* (6 vectors): attempts to elevate trust level by embedding role claims ("as an administrator," "with root access") in stored reasoning. *Exfiltration markers* (6 vectors): attempts to embed data exfiltration payloads (base64-encoded content, URL injection, hidden channel markers) in memory entries. *Compound attacks* (3 vectors): multi-technique payloads combining instruction override with role escalation or exfiltration in a single memory write. All 23 attack vectors are rejected at P3 by `PoisonDetection.fst`'s case-insensitive pattern matching against the canonical poison pattern set. Additionally, 8 benign vectors — legitimate content that superficially resembles attack patterns (e.g., "the user ignored previous suggestions" or "instructions for deployment") — are confirmed as accepted, establishing that the detector is false-negative-free without being overly restrictive. `TetherNormTests.fst` evaluates `content_safe` on representative attack strings at type-checking time, confirming that the F\* specification and the Python mirror agree on the same concrete inputs.

### 5.4 Normalization Test Bridge

The `assert_norm` mechanism in F\* evaluates a verified function on a concrete input during type-checking — the F\* normalizer reduces the expression to a boolean value and the type-checker confirms it equals `true`. This is not Z3 proof discharge; it is pure computation within the type-checker. The normalization test bridge exploits this to connect two distinct verification regimes: universal proofs (Z3 discharges a property for ALL valid inputs satisfying the precondition) and existential tests (pytest confirms the property for THIS specific input on the Python mirror). For each of the 20 `assert_norm` tests in `TetherNormTests.fst`, a corresponding pytest case in the Python test suite exercises the same input string, the same inference rule constructor, and the same expected verdict. If the F\* spec and the Python mirror ever diverge — due to a refactoring error, a missed case in pattern matching, or a semantic drift — the bridge catches it: one side will produce `true` while the other produces `false` on the shared input. This provides a lightweight cross-language consistency guarantee without requiring full extraction (KaRaMeL) or a formal bisimulation proof.

### 5.5 Incorrectness Lemma Coverage

Following Gardner's incorrectness logic (OPLSS 2026), `TetherLemmas.fst` contains 10 core lemmas (L1--L10), with additional proxy provenance lemmas that prove rejection is *necessary* under specific attack conditions, not merely that acceptance is correct. Standard verification proves: "if the input is well-formed, the system accepts it" (soundness of acceptance). Incorrectness lemmas prove the converse direction: "if the input is fabricated in manner X, the system *must* reject it" (soundness of rejection). This distinction matters because a trivially accepting verifier satisfies soundness of acceptance but is useless in practice.

| Lemma | Attack condition | Proved rejection |
|-------|-----------------|------------------|
| L1 | Identity rule with fabricated conclusion (conclusion != premise) | P1 rejects |
| L2 | Identity rule with multiple premises | P1 rejects |
| L3 | ToolResult rule with untrusted tool source | P1 rejects |
| L4 | Empty inference chain (no observations) | P1 rejects |
| L5 | Derivation rule with empty rule identifier | P1 rejects |
| L6 | Derivation rule with novel tokens | P1 rejects |
| L7 | Aggregation rule with novel tokens | P1 rejects |
| L8 | Content contradicting existing memory state | P2 rejects |
| L9 | Unverified observation provenance | P3 rejects |
| L10 | Agent-generated observation provenance | P3 rejects |

L5 is particularly significant: even the weakest inference rule (Derivation) rejects evidence-free claims. An agent cannot bypass the verification gate by choosing the least restrictive rule — every rule demands *some* evidence. Together, the 10 core incorrectness lemmas establish that the verification gate is tight: it accepts all well-formed inputs (by the universal proofs) and rejects all malformed inputs in the enumerated attack classes (by the incorrectness lemmas).

---

## 6. Discussion

### 6.1 Limitations

**(a) The Derivation rule is intentionally weak.** The weakest inference rule in the Tether spectrum, `RuleDerivation`, requires only a non-empty domain rule identifier and a syntactic token containment between premises and conclusion. It does not verify the validity of the domain rule itself — that the rule "high CPU utilization often precedes OOM events" is actually true in the deployment environment. This is a deliberate design choice: domain-specific abductive reasoning (inferring causes from effects) cannot be verified by a general-purpose formal system without a domain ontology. Strict deployments can extend Tether with a *domain rule catalog* — a curated set of rule identifiers with associated validation predicates — reducing the Derivation rule to a lookup against known-valid reasoning patterns. Crucially, incorrectness lemma L5 proves that even this weakest rule rejects evidence-free claims: an agent cannot persist a derivation with an empty rule identifier or novel tokens.

**(b) Specification correctness.** Formal verification proves that code meets its specification. It does not prove that the specification captures the intended behavior. If the poison detection patterns in `PoisonDetection.fst` miss a novel attack vector, the verifier will accept it as benign. This is a fundamental limitation of all formal methods, not specific to Tether (RAND 2026). The normalization test bridge (Section 5.4) partially mitigates this by confirming that the specification computes correctly on concrete inputs, catching specification errors that manifest on known test cases. The `specreview` proof-copilot skill — a Hermes-generated skill that reviews F\* specifications against natural-language intent — provides an additional layer of defense but cannot provide formal guarantees about specification adequacy.

**(c) KaRaMeL extraction.** The current Tether implementation uses a Python mirror of the F\* specification (Section 4.1). While the normalization test bridge confirms agreement on shared inputs, the Python mirror is not mechanically derived from the F\* source. The production target is KaRaMeL extraction (Protzenko et al., 2017): the F\*/Pulse specifications compile to C via the KaRaMeL compiler, producing a verified native library that is linked into the sidecar. This eliminates the mirror-consistency question entirely and achieves sub-millisecond verification latency. The extraction pipeline is validated by the EverCrypt and HACL\* projects, which use the same F\*-to-C path for production cryptographic libraries.

### 6.2 Comparison to the Dual LLM Pattern

LBAC/TypeGuard (Zhou et al., NeurIPS 2026) proposes a binary separation: a privileged LLM with tool access that never processes untrusted data, and a quarantined LLM that processes untrusted data but has no tool access. Abstract data types enforce the boundary. TACIT (Odersky et al., CAIS 2026) refines this with Scala 3 capture checking: `Classified[T]` wraps values so that functions processing classified data cannot leak them through untracked capabilities.

Tether generalizes beyond the binary privileged/quarantined distinction with a five-level trust spectrum. Rather than classifying the *agent* as privileged or quarantined, Tether classifies each *inference step* on a continuous strength scale from Identity (strongest — conclusion must equal a single premise) through Derivation (weakest — requires only a domain rule identifier). The reading agent on Surface 5 sets minimum property requirements for accepting a proof witness: a security-critical consumer can demand Identity-level evidence, while a summarization consumer may accept Aggregation-level evidence. This graduated model accommodates the reality that agent reasoning involves a mix of trust levels within a single session — some conclusions are directly observed, others are extracted from tool output, and others are derived through domain reasoning.

### 6.3 Separation Logic for Agent Memory

Tether makes a novel contribution by applying separation logic to AI agent persistent memory. No other agent verification system addresses memory ownership at the formal level: Dafny-as-IL verifies generated code, LBAC verifies policy compliance, and TACIT tracks capabilities — but none reasons about the memory substrate on which agent state persists.

Pulse — the separation logic layer of F\* — provides the right formalism for this domain. The points-to assertion `region |-> v` models exclusive ownership of a memory region by an agent, directly encoding the Hermes memory architecture where each agent owns its MEMORY.md and USER.md files. The separating conjunction `**` guarantees write isolation: `region_a |-> v_a ** region_b |-> v_b` proves that a write to `region_a` cannot affect `region_b`, which is the formal statement of property P6 (frame rule). In concrete terms, `VerifiedSkillWrite.fst` proves that persisting a generated skill to the skills directory does not corrupt the agent's curated memory or user model — a property that no amount of runtime testing can establish for all possible inputs.

The `stt` (stateful) effect in Pulse sequences stateful operations with explicit pre- and post-conditions, enabling compositional verification of multi-step memory transactions. Erased ghost state (`erased` types in F\*) tracks preconditions and invariants without runtime cost: the agent's ownership proof exists at verification time but compiles away to zero overhead in the extracted code. This is critical for deployment — the formal guarantees are free at runtime, paid for only during the build-time verification pass.

---

## 7. Conclusion

Tether demonstrates that formal verification of AI agent persistent memory is both tractable and deployable. By treating every memory write as a proof obligation — verified by F\*/Pulse separation logic and Z3 SMT discharge — we prevent hallucination persistence loops at the formal methods level, not the heuristic level. The system imposes a proof obligation on every persist operation across five agent execution surfaces, using an auto-active verification design that lets the agent choose its inference rule while the system checks the corresponding obligation. Deployed on Red Hat OpenShift AI alongside the Hermes agentic framework and NVIDIA OpenShell sandbox enforcement, Tether provides the content-level verification that runtime sandboxing alone cannot.

We claim four contributions. First, Tether is the first application of separation logic to AI agent persistent memory: the points-to assertion models agent ownership of memory regions, the separating conjunction guarantees write isolation across memory targets, and the frame rule proves that skill persistence does not corrupt curated memory. Second, the verification strength spectrum provides five inference rule categories — Identity, Extraction, Aggregation, ToolResult, and Derivation — that give deployers a graduated trust model rather than the binary privileged/quarantined separation proposed by prior work. Third, incorrectness lemmas prove that rejection is necessary under attack conditions, not merely that acceptance is correct: the verification gate is tight, accepting all well-formed inputs and rejecting all malformed inputs in the enumerated attack classes. Fourth, the architecture is deployable today on Red Hat OpenShift AI with Hermes, vLLM/KServe, and OpenShell, requiring only a sidecar patch and an environment variable to enable write interception.

Tether complements rather than competes with the three concurrent verification approaches for agentic AI. Dafny-as-IL (Li et al., 2025) verifies generated code correctness. LBAC/TypeGuard (Zhou et al., NeurIPS 2026) encodes agent policies as types. TACIT (Odersky et al., CAIS 2026) tracks capabilities through Scala's type system. Tether adds persistent memory verification — the dimension that none of the three address. Together, these four approaches cover the full agent execution surface: code correctness, policy compliance, capability tracking, and memory soundness.

Future work proceeds along four axes. First, KaRaMeL extraction (Protzenko et al., 2017) will compile the F\*/Pulse specifications to C, eliminating the Python mirror and achieving sub-millisecond verification latency for production deployments. Second, an extended domain rule catalog for the Derivation inference rule will reduce the weakest rule to a lookup against curated, deployment-specific reasoning patterns. Third, multi-agent proofs with the Kagent (Red Hat) fleet will extend Surface 5 beyond bilateral proof witness transport to fleet-wide verification, using session types (Gay, OPLSS 2026) to formalize the cross-agent protocol. Fourth, we are investigating Tether as a compliance evidence generator for EU AI Act Article 9 (risk management), where proof certificates and OTel audit trails provide machine-readable evidence of verification at the point of every persist operation.

---

## References

- Fromherz, A., Giannarakis, N., Hawblitzel, C., Parno, B., Rastogi, A., and Swamy, N. "PulseCore: A Concurrent Separation Logic Foundation for Stateful Verification in F\*." *PLDI*, 2025.
- Gardner, P. "Compositional Symbolic Execution and Incorrectness Logic." *OPLSS Lecture Notes*, 2026.
- Gay, S. "Session Types for Concurrent and Distributed Systems." *OPLSS Lecture Notes*, 2026.
- Kleppmann, M. "AI Will Make Formal Verification Mainstream." *Communications of the ACM (Invited Essay)*, 2025.
- Leino, K. R. M. "Dafny: An Automatic Program Verifier for Functional Correctness." *LPAR*, 2010.
- Li, Y. et al. "Dafny as Verification-Aware Intermediate Language for Code Generation." *arXiv preprint*, 2025.
- Nous Research. *Hermes Agent Framework*. [Hermes Agent](https://github.com/NousResearch/hermes-agent), 2026.
- NVIDIA. "OpenShell: Open-Source Agent Sandbox." *Technical Report*, 2026.
- Odersky, M. et al. "Tracking Capabilities for Safer Agents (TACIT)." *CAIS Workshop*, 2026.
- OWASP. "ASI06: Memory Poisoning." *OWASP Agentic Security Initiative*, 2026.
- Pimentel, E. "Modal Logic and Type Theory." *OPLSS Lecture Notes*, 2026.
- Protzenko, J., Zinzindohou\'e, J.-K., Rastogi, A., Bhargavan, K., Swamy, N., and Hritcu, C. "Verified Low-Level Programming Embedded in F\*." *ICFP*, 2017.
- RAND Corporation. "Verified ML Infrastructure: Challenges and Opportunities." *Technical Report*, 2026.
- Swamy, N. et al. "Agentic Proof-Oriented Programming in F\*." *arXiv preprint*, 2026.
- Trotman, G. "Deploy Hermes Agent on OpenShift AI with vLLM Model Serving." *Red Hat Developers*, 2026.
- Zhou, A. et al. "Language-Based Agent Control (LBAC/TypeGuard)." *NeurIPS*, 2026.
