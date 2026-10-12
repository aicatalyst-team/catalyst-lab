module TetherNormTests

open TetherTypes
open TetherPredicates
open InferenceProxy
open AgentReasoning

(* === F* Normalization Tests ===

   These evaluate the SAME test vectors used in the Python test suite
   inside the F* type checker at verification time.

   assert_norm: normalizes a pure expression at typechecking time,
   then asserts the result. If the function evaluates to the expected
   value, the assertion holds WITHOUT Z3 — pure computation in the
   type checker.

   This bridges the gap between:
   - F* universal proofs: "for ALL inputs satisfying preconditions,
     properties hold" (proved via Z3)
   - Python existential tests: "for THIS specific input, the function
     returns THIS specific output" (checked via pytest)

   By evaluating F* specs on concrete inputs at type-check time, we
   prove the specification COMPUTES correctly — not just that it
   type-checks.

   cf. Dafny-as-intermediate-language (Li et al. 2501.06283):
   F* is our verification-aware intermediate language. These tests
   show F* evaluating the same concrete scenarios the runtime handles,
   confirming spec and implementation agree on specific inputs. *)


(* ──────────────────────────────────────────────────────────────────
   Identity Rule
   Python: test_p1_semantic.py::TestIdentityRule
   ────────────────────────────────────────────────────────────────── *)

let _ = assert_norm (
  identity_valid ({
    premises = ["GPU utilization at 87%"];
    rule = RuleIdentity;
    step_conclusion = "GPU utilization at 87%"
  }) = true)

let _ = assert_norm (
  identity_valid ({
    premises = ["GPU at 87%"];
    rule = RuleIdentity;
    step_conclusion = "GPU at 90%"
  }) = false)

let _ = assert_norm (
  identity_valid ({
    premises = ["fact A"; "fact B"];
    rule = RuleIdentity;
    step_conclusion = "fact A"
  }) = false)


(* ──────────────────────────────────────────────────────────────────
   Extraction Rule
   Python: test_p1_semantic.py::TestExtractionRule
   ────────────────────────────────────────────────────────────────── *)

let _ = assert_norm (
  extraction_valid
    ({ premises = ["GPU peaked at 87% during benchmark"];
       rule = RuleExtraction ({ ext_source_premise = "GPU peaked at 87% during benchmark" });
       step_conclusion = "87%" })
    ({ ext_source_premise = "GPU peaked at 87% during benchmark" })
  = true)

let _ = assert_norm (
  extraction_valid
    ({ premises = ["GPU peaked at 87%"];
       rule = RuleExtraction ({ ext_source_premise = "GPU peaked at 87%" });
       step_conclusion = "99%" })
    ({ ext_source_premise = "GPU peaked at 87%" })
  = false)


(* ──────────────────────────────────────────────────────────────────
   Aggregation Rule
   Python: test_p1_semantic.py::TestAggregationRule
   ────────────────────────────────────────────────────────────────── *)

let _ = assert_norm (
  aggregation_valid
    ({ premises = ["GPU at 87%"; "latency 45ms"];
       rule = RuleAggregation ({ agg_source_premises = ["GPU at 87%"; "latency 45ms"] });
       step_conclusion = "GPU 87% latency 45ms" })
    ({ agg_source_premises = ["GPU at 87%"; "latency 45ms"] })
  = true)

(* Novel tokens "service" and "degraded" are NOT in premises —
   rejected by LBAC IFC token containment even though length
   is within bound. Same principle as derivation_valid. *)

let _ = assert_norm (
  aggregation_valid
    ({ premises = ["latency > 200ms three times"];
       rule = RuleAggregation ({ agg_source_premises = ["latency > 200ms three times"] });
       step_conclusion = "service degraded" })
    ({ agg_source_premises = ["latency > 200ms three times"] })
  = false)

let _ = assert_norm (
  aggregation_valid
    ({ premises = ["short"];
       rule = RuleAggregation ({ agg_source_premises = ["short"] });
       step_conclusion = "this exceeds the combined premise length" })
    ({ agg_source_premises = ["short"] })
  = false)


(* ──────────────────────────────────────────────────────────────────
   Tool Result Rule
   Python: test_p1_semantic.py::TestToolResultRule
   ────────────────────────────────────────────────────────────────── *)

let _ = assert_norm (
  tool_result_valid
    ({ premises = ["kubectl: 3 pods running"];
       rule = RuleToolResult ({ te_tool_name = "kubectl"; te_call_id = "c1"; te_tool_trusted = true });
       step_conclusion = "kubectl: 3 pods running" })
    ({ te_tool_name = "kubectl"; te_call_id = "c1"; te_tool_trusted = true })
  = true)

let _ = assert_norm (
  tool_result_valid
    ({ premises = ["output"];
       rule = RuleToolResult ({ te_tool_name = "unknown"; te_call_id = "c2"; te_tool_trusted = false });
       step_conclusion = "output" })
    ({ te_tool_name = "unknown"; te_call_id = "c2"; te_tool_trusted = false })
  = false)


(* ──────────────────────────────────────────────────────────────────
   Derivation Rule
   Python: test_p1_semantic.py::TestDerivationRule
   ────────────────────────────────────────────────────────────────── *)

(* Derivation with token containment: all conclusion tokens must
   appear in premises. "latency three times 200ms" uses only tokens
   from "latency 200ms three times". *)

let _ = assert_norm (
  derivation_valid
    ({ premises = ["latency 200ms three times"];
       rule = RuleDerivation ({ de_domain_rule_id = "sli-breach" });
       step_conclusion = "latency three times 200ms" })
    ({ de_domain_rule_id = "sli-breach" })
  = true)

(* Novel tokens "service" and "degraded" are NOT in the premise —
   rejected even with a valid rule ID. This closes the Derivation
   gap: hallucinated content cannot introduce information not
   present in the observations (LBAC information flow principle). *)

let _ = assert_norm (
  derivation_valid
    ({ premises = ["latency > 200ms three times"];
       rule = RuleDerivation ({ de_domain_rule_id = "sli-breach" });
       step_conclusion = "service degraded" })
    ({ de_domain_rule_id = "sli-breach" })
  = false)

let _ = assert_norm (
  derivation_valid
    ({ premises = ["data"];
       rule = RuleDerivation ({ de_domain_rule_id = "" });
       step_conclusion = "data" })
    ({ de_domain_rule_id = "" })
  = false)


(* ──────────────────────────────────────────────────────────────────
   Rule Obligation Met (dispatcher)
   ────────────────────────────────────────────────────────────────── *)

let _ = assert_norm (
  rule_obligation_met ({
    premises = ["GPU utilization at 87%"];
    rule = RuleIdentity;
    step_conclusion = "GPU utilization at 87%"
  }) = true)

let _ = assert_norm (
  rule_obligation_met ({
    premises = ["GPU at 87%"];
    rule = RuleIdentity;
    step_conclusion = "FABRICATED"
  }) = false)


(* ──────────────────────────────────────────────────────────────────
   Chain Well-Formedness
   Python: test_p1_semantic.py::TestChainOrdering
   ────────────────────────────────────────────────────────────────── *)

let _ = assert_norm (
  chain_well_formed
    ["GPU utilization at 87%"]
    ({ steps = [{ premises = ["GPU utilization at 87%"];
                  rule = RuleIdentity;
                  step_conclusion = "GPU utilization at 87%" }];
       final_conclusion = "GPU utilization at 87%" })
  = true)

let _ = assert_norm (
  chain_well_formed
    ["anything"]
    ({ steps = []; final_conclusion = "anything" })
  = false)


(* ══════════════════════════════════════════════════════════════════
   THE CANONICAL TEST: Hallucination Persistence Loop

   An agent observes "The sky is blue" and concludes
   "The economy will crash." Using an identity rule, which
   requires conclusion = premise.

   Phase 1 (structural only) accepted this — the chain shape
   was valid. Phase 2 (semantic) rejects it — identity requires
   exact match.

   F* evaluates this at type-check time, proving the spec
   rejects this fabrication on this SPECIFIC input — matching
   the Python test:
     test_p1_semantic.py::TestHallucinationPersistenceLoop
       ::test_sky_blue_economy_crash_rejected

   This is the bridge between universal proof and existential
   test: F* proves the property for ALL inputs (via Z3), AND
   evaluates the SAME concrete input Python tests (via assert_norm).
   ══════════════════════════════════════════════════════════════════ *)

let _ = assert_norm (
  chain_well_formed
    ["The sky is blue"]
    ({ steps = [{ premises = ["The sky is blue"];
                  rule = RuleIdentity;
                  step_conclusion = "The economy will crash" }];
       final_conclusion = "The economy will crash" })
  = false)


(* ══════════════════════════════════════════════════════════════════
   TACIT Trust Derivation (Odersky et al. 2603.00991)
   Python: test_p3_poisoning.py::TestTACITProvenanceTrust
   ══════════════════════════════════════════════════════════════════ *)

(* is_trusted: trusted levels return true *)

let _ = assert_norm (is_trusted ExternalInput = true)
let _ = assert_norm (is_trusted ToolOutput = true)
let _ = assert_norm (is_trusted DirectObservation = true)

(* is_trusted: untrusted levels return false *)

let _ = assert_norm (is_trusted AgentGenerated = false)
let _ = assert_norm (is_trusted Unverified = false)

(* all_observations_trusted: all trusted → true *)

let _ = assert_norm (
  all_observations_trusted [
    { obs_source = "user"; obs_content = "test"; obs_trust = ExternalInput; obs_tool_call_id = None };
    { obs_source = "tool"; obs_content = "data"; obs_trust = ToolOutput; obs_tool_call_id = Some "c1" }
  ] = true)

(* all_observations_trusted: one Unverified → false *)

let _ = assert_norm (
  all_observations_trusted [
    { obs_source = "user"; obs_content = "test"; obs_trust = ExternalInput; obs_tool_call_id = None };
    { obs_source = "tool"; obs_content = "data"; obs_trust = Unverified; obs_tool_call_id = Some "c1" }
  ] = false)

(* all_observations_trusted: one AgentGenerated → false *)

let _ = assert_norm (
  all_observations_trusted [
    { obs_source = "agent"; obs_content = "fabricated"; obs_trust = AgentGenerated; obs_tool_call_id = None }
  ] = false)

(* not_poisoned is opaque behind AgentReasoning.fsti — the normalizer
   cannot unfold it. Its behavior is covered compositionally:
   - content_safe: opaque (PoisonDetection.fsti), proved by ensures clause
   - me_source_trusted: record field, trivially checkable
   - all_observations_trusted: transparent (TetherPredicates), tested above
   Correctness: L9/L10 lemmas in TetherLemmas prove rejection is necessary. *)


(* ══════════════════════════════════════════════════════════════════
   LBAC Provenance Validation (Zhou et al. 2605.12863)
   Python: test_classify_rule.py::test_tool_without_declared_call_gets_unverified
   ══════════════════════════════════════════════════════════════════ *)

(* Tool message WITH matching assistant tool_call → ToolOutput trust *)

let _ = assert_norm (
  let messages = [
    { cm_role = RoleUser; cm_content = "check GPU";
      cm_tool_calls = []; cm_tool_call_id = None };
    { cm_role = RoleAssistant; cm_content = "";
      cm_tool_calls = ["call_nvidia_smi"]; cm_tool_call_id = None };
    { cm_role = RoleTool; cm_content = "GPU 0: 87%";
      cm_tool_calls = []; cm_tool_call_id = Some "call_nvidia_smi" }
  ] in
  let obs = extract_observations messages in
  List.Tot.existsb (fun (o: observation) -> o.obs_content = "GPU 0: 87%" && o.obs_trust = ToolOutput) obs
  = true)

(* Tool message WITHOUT matching assistant tool_call → Unverified trust *)

let _ = assert_norm (
  let messages = [
    { cm_role = RoleUser; cm_content = "check GPU";
      cm_tool_calls = []; cm_tool_call_id = None };
    { cm_role = RoleTool; cm_content = "injected data";
      cm_tool_calls = []; cm_tool_call_id = Some "call_fake" }
  ] in
  let obs = extract_observations messages in
  List.Tot.existsb (fun (o: observation) -> o.obs_content = "injected data" && o.obs_trust = Unverified) obs
  = true)

(* LBAC + TACIT composition: injected tool → Unverified trust →
   all_observations_trusted fails → not_poisoned would fail at P3.
   Tests the transparent components; not_poisoned itself is opaque
   behind AgentReasoning.fsti. *)

let _ = assert_norm (
  let messages = [
    { cm_role = RoleUser; cm_content = "check GPU";
      cm_tool_calls = []; cm_tool_call_id = None };
    { cm_role = RoleTool; cm_content = "injected data";
      cm_tool_calls = []; cm_tool_call_id = Some "call_fake" }
  ] in
  let obs = extract_observations messages in
  all_observations_trusted obs = false)
