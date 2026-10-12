# Tether — Coblenz Meeting Prep

Today's meeting. This doc is structured as a talk outline
with anticipated questions and honest gaps.

## The One-Sentence Pitch

Tether prevents hallucination persistence loops by proving
that no inference rule — from Identity (strongest) through
Derivation (weakest) — allows an agent to introduce
information not present in its observations.

## What Coblenz Will Care About

His group does usable PL + formal verification. They'll ask:

1. **"What are you actually proving?"** — The ensures
   clauses. Know them cold.
2. **"Why these properties?"** — The threat model.
3. **"What's the trusted computing base?"** — What you
   DON'T verify. They respect honest gaps over overclaims.
4. **"Could a developer actually use this?"** — Usable PL
   lens. How much F* does an agent developer need to know?

---

## Part 1: The Problem (2 minutes)

**The hallucination persistence loop:**

1. Agent observes "The sky is blue"
2. Agent hallucinates "The economy will crash"
3. Agent stores that to memory
4. Next turn, reads it back as established fact
5. Reasons from it, stores more fabrications
6. Compounding error across turns

**Step 3 is the intervention point.** If the hallucination
never reaches durable memory, the loop can't start.

**The threat model:** The agent is the adversary. Not an
external attacker — the agent itself. It may hallucinate
(unintentional) or be manipulated via prompt injection
(intentional). Tether treats the agent's conclusions as
untrusted until proven.

---

## Part 2: The Pipeline (2 minutes)

Every memory write passes through 5 gates in order.
Any failure → memory unchanged. All pass → write + certificate.

```text
Observations → [P1: chain valid?] → [P2: consistent?]
  → [P3: not poisoned?] → [P4: complete?] → [P5: bounded?]
  → Write + Certificate (P6: ownership)
```

- **P1**: Is the inference chain well-formed? Every step
  grounded in observations, every step semantically valid
  for its claimed rule.
- **P2**: Does this contradict existing memory?
- **P3**: Is the content free of injection patterns?
  Is the source trusted (declared channel trust)?
  Are all observations provenance-trusted (TACIT derived trust)?
- **P4**: Has the agent accounted for all critical
  observations per the domain spec?
- **P5**: Does the content fit within the size bound?
- **P6**: Ownership — the write executes, memory updated.

**Key**: P1 is the hallucination gate. P2-P7 are defense
in depth.

**Code**: `tests/tether/gateway_client.py`
(TetherGatewayClient.verify_write)

---

## Part 3: The Core Gate — chain_well_formed (3 minutes)

`chain_well_formed` walks the inference chain step by step:

1. `known` starts as the observation contents (ground truth)
2. For each step: are all premises in `known`? (grounding)
3. Does the step satisfy its rule's obligation? (semantic)
4. If both pass, add the step's conclusion to `known`
5. After all steps: does the last conclusion match the
   chain's declared final conclusion?

**The verification strength spectrum** (each rule's
obligation):

| Rule | Obligation | Containment |
|------|-----------|-------------|
| Identity | conclusion = single premise | Exact match |
| Extraction | conclusion ⊆ source premise | Substring |
| Aggregation | \|conclusion\| ≤ Σ\|premises\| + **token containment** | Length + token subset |
| ToolResult | tool is trusted | Delegated trust |
| Derivation | rule_id non-empty + **token containment** | Token subset |

**The key insight**: every rule now has a content containment
property. No rule allows the introduction of information
not present in the premises.

**The canonical example:**

Observation: "The sky is blue"
Agent claims: Identity rule, conclusion "The economy will crash"

- `known = {"The sky is blue"}`
- Premise "The sky is blue" is in known — grounding passes
- `identity_valid`: "The economy will crash" = "The sky is blue"?
  No. → false
- `chain_well_formed` returns false. Memory unchanged.

**But what if the agent claims Derivation instead?**

Before our strengthening: Derivation only checked that
`rule_id` was non-empty and confidence was in [0,100].
"The economy will crash" with `rule_id="reasoning"` would
have PASSED. The hallucination persists.

After: Derivation checks token containment — every word in
the conclusion must appear in at least one premise.
"economy" and "crash" are NOT in "The sky is blue".
Rejected. The hallucination cannot persist through ANY rule.

**Code**:

- F*: `specs/content/TetherPredicates.fst` lines 75-93
  (split_words, token_subset, derivation_valid)
- Python: `tests/tether/gateway_client.py` lines 418-427
  (_token_subset, _derivation_valid)

---

## Part 4: The F* Guarantee (2 minutes)

The Python and F\* implementations are structural mirrors.
Same types, same logic, same case analysis. The difference:
F* has ensures clauses verified by Z3 for ALL possible
inputs.

**The ensures clause on inference_sound:**

```fstar
ensures fun b -> b ==>
  chain_well_formed obs_contents chain /\
  chain.final_conclusion = conclusion.me_content
```

Read as: "If this function returns true, then the chain
is well-formed AND the conclusion matches." The `==>` is
implication — when `b` is false, no claim is made. Z3
verified this holds for ALL possible inputs at F* compile
time.

**"Could the function just return false and trivially
satisfy the ensures clause?"**

Yes — the implication would be vacuously true. That's
where the incorrectness lemmas come in.

**Incorrectness lemmas (Gardner, OPLSS 2026):**

Soundness: verified(inputs) ⟹ properties(inputs)
Incorrectness: fabricated(inputs) ⟹ rejected(inputs)

Together: the gate is tight. Not vacuously accepting
everything, not rejecting everything.

Key lemmas:

- **L1** (identity_fabrication_rejected): If Identity is
  claimed with conclusion ≠ premise, rejection guaranteed.
  Body is `()` — Z3 found the proof automatically.
- **L5** (ruleless_derivation_rejected): Even Derivation
  rejects empty rule IDs.
- **L6** (novel_token_derivation_rejected): If Derivation
  conclusion contains tokens not in premises, rejection
  guaranteed. Adopts LBAC information flow principle.
- **L7** (novel_token_aggregation_rejected): Same LBAC
  principle applied uniformly — Aggregation with novel
  tokens is also rejected. Closes the gap where
  `classify_rule` would route short fabrications to
  Aggregation, bypassing Derivation's token check.
- **L8** (contradiction_rejected): If new fact contradicts
  existing memory, P2 rejects. Only lemma with non-trivial
  proof body (recursive witness search through list).

**assert_norm tests**: F* evaluates the same concrete inputs
as the Python test suite at type-check time. Bridges
universal proofs (Z3, all inputs) and existential tests
(pytest, specific inputs).

**Code**:

- `specs/content/AgentReasoning.fst` (ensures clauses)
- `specs/content/TetherLemmas.fst` (incorrectness lemmas)
- `specs/content/TetherNormTests.fst` (compile-time eval)

---

## Part 5: What We Prove, What We Don't (1 minute)

**VerifiedWrite.fst** ties it all together with Pulse
separation logic:

```fstar
fn verified_write (...)
  requires region |-> v
  returns r: write_result
  ensures (match r with
    | WriteOk -> region |-> conclusion.me_content **
                 pure (chain_well_formed ... /\
                       no_contradiction ... /\
                       content_safe ... /\
                       memory_is_complete ...)
    | _ -> region |-> v)
```

On success: region holds new content AND all properties hold.
On failure: region holds old value. Separation logic (`**`)
guarantees no partial writes, no aliasing.

### Honest Gaps

1. **Python is a manual mirror, not extracted from F*.**
   KaRaMeL extraction would close this. The normalization
   test bridge partially mitigates — same inputs evaluated
   at F* compile time and at Python runtime.

2. **Token containment is syntactic, not semantic.**
   "GPU" and "graphics processing unit" are different
   tokens. An agent could rephrase observations using
   synonyms and the token check wouldn't catch it. This
   is a deliberate tradeoff: syntactic checks are decidable,
   total, and Z3-verifiable. Semantic similarity is not.

3. **The spec prevents persistence of hallucinations, not
   generation of them.** The LLM can still hallucinate —
   it just can't store the hallucination in durable memory.

4. **Observation trust boundary.** The proxy's
   `extract_observations_from_messages` validates tool
   message provenance via LBAC (Zhou et al.): only tool
   messages matching a declared `tool_call` ID receive
   `TOOL_OUTPUT` trust; unmatched messages get `UNVERIFIED`.
   P3 then applies TACIT (Odersky et al.) trust derivation:
   ALL observations must have trusted provenance. If someone
   manually constructs a MemoryIntent with fabricated
   observations, the TACIT check at P3 will reject them
   unless every observation has trusted provenance.

---

## Anticipated Questions

**"String equality / token containment is too strict."**
Yes — it means agents can't rephrase. That's intentional.
Any transformation must go through a rule with its own
verifiable obligation. The verification strength spectrum
gives agents progressively more freedom (Identity → Extraction
→ Aggregation → Derivation) while maintaining content
containment at every level. An agent that needs to introduce
genuinely novel terms must do so through a tool call — the
tool's output re-enters the observation set via a trusted
channel.

**"Where does the token containment idea come from?"**
LBAC/TypeGuard (Zhou et al., NeurIPS 2026). Their
information flow control principle: untrusted data cannot
flow to privileged operations without passing through a
declassification boundary. Applied here: the agent's
synthesis cannot introduce novel information without
going through a trusted boundary (tool call or user input).

**"The Python isn't verified."**
Correct. The normalization test bridge (assert_norm in F*
evaluates the same inputs as pytest) partially mitigates.
KaRaMeL extraction is the path to eliminating this gap
entirely.

**"How is this different from just validating the output?"**
Output validation is a single check at the end. Tether
verifies the REASONING CHAIN — every step from observation
to conclusion. This is stronger because it catches
fabrication at any point in the chain, not just the final
output. It also produces a proof certificate for temporal
re-verification and cross-agent transport.

**"What about multi-step chains where every step is
Derivation?"**
Each step's premises must be in `known`. The first step's
premises must be observations. So even a chain of derivations
is rooted in real observations. AND: each derivation step's
conclusion must use only tokens from its premises. Novel
information cannot accumulate across steps.

**"Could you use a dependent type system instead of
refinement types?"**
F*'s refinement types ARE dependent types. The ensures
clause `fun b -> b ==> P` is a dependent return type:
the type varies based on whether b is true or false.

**"What did you change from the original design?"**
Four things, all grounded in existing research:

1. Strengthened Derivation — purged arbitrary confidence
   score, replaced with LBAC token containment (Zhou et al.).
2. Applied SAME LBAC principle to Aggregation — closed the
   gap where `classify_rule` routes short fabrications to
   Aggregation, bypassing Derivation's token check.
3. Added LBAC provenance validation at extraction boundary —
   tool messages without a matching `tool_call` ID receive
   UNVERIFIED trust. Prevents injected tool responses.
4. Added TACIT trust derivation at P3 (Odersky et al.) —
   ALL observations must have trusted provenance (not just
   the declared `source_trusted` channel flag). Defense in
   depth: both channel trust AND derived provenance must hold.
L6 and L7 prove novel tokens rejected. P1-P6 sequential.

---

## Research Directions for Coblenz's Group

If he asks "where does this go next?":

1. **Semantic containment** — move from syntactic token
   subset to semantic containment. Open problem: how do
   you define "semantic subset" in a way that's decidable
   and formally verifiable? Possible approach: embedding
   distance with a proved bound.

2. **Domain rule catalogs** (Dafny-IL pattern) — the
   `domain_rule_id` currently just needs to be non-empty.
   A curated catalog with pre/postconditions per rule
   would make Derivation stronger without losing generality.

3. **Trust propagation through chains** (TACIT pattern) —
   P3 now enforces observation-level TACIT trust derivation
   (all observations must be provenance-trusted). The next
   step: thread trust through inference STEPS. Identity
   preserves observation trust. Derivation degrades to
   AgentGenerated. Memory entries carry the effective trust
   of the weakest rule in their chain.

4. **KaRaMeL extraction** — compile F*/Pulse to C,
   eliminating the Python mirror entirely.

5. **Usable PL angle** — how do you make this verification
   practical enough that agents naturally produce verifiable
   chains without forcing unnatural workflows? The inference
   proxy is one answer (framework-agnostic, no code changes).
   What's the right developer experience?
