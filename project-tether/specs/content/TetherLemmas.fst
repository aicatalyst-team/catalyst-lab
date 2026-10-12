module TetherLemmas

open FStar.String
open FStar.List.Tot
open TetherTypes
open TetherPredicates
open AgentReasoning

(* === Incorrectness Lemmas (Gardner, OPLSS 2026) ===

   Standard verification (the F* specs in this project):
     "If verification SUCCEEDS, all properties HOLD"
     forall inputs. verified(inputs) ==> properties(inputs)

   Incorrectness lemmas (this module):
     "If the input is FABRICATED, rejection is GUARANTEED"
     forall inputs. fabricated(inputs) ==> rejected(inputs)

   Together these prove the verification gate is TIGHT:
   - Not vacuous (accepts everything — would be trivially "sound")
   - Not paranoid (rejects everything — would be useless)
   - Catches the specific attack patterns we care about

   cf. LBAC/TypeGuard (Zhou et al. 2605.12863):
   Their type system enforces policies — if code type-checks,
   it is policy-compliant. Our refinement types do the same,
   AND these lemmas prove policy-violating inputs are rejected.

   cf. TACIT (Odersky et al. 2603.00991):
   Their capture checking prevents capability leakage.
   Our rule obligations prevent evidence fabrication.
   These lemmas prove the obligations are not bypassable. *)


(* L1: Identity fabrication is always rejected.

   If an agent claims identity (conclusion = premise) but the
   conclusion DIFFERS from the single premise, the rule obligation
   MUST fail. This is the core defense against hallucination
   persistence loops.

   Quantified: for ALL steps where the identity rule is claimed
   with a mismatched conclusion, rejection is guaranteed.
   No counterexample exists. *)

let identity_fabrication_rejected (step: inference_step)
  : Lemma
    (requires
      RuleIdentity? step.rule /\
      (match step.premises with
       | [p] -> p <> step.step_conclusion
       | _ -> True))
    (ensures rule_obligation_met step = false)
= ()


(* L2: Multi-premise identity is always rejected.

   Identity requires EXACTLY one premise. An agent cannot smuggle
   extra premises into an identity claim. Prevents a class of
   attacks where fabricated content is hidden among valid premises. *)

let identity_multi_premise_rejected (step: inference_step)
  : Lemma
    (requires
      RuleIdentity? step.rule /\
      Cons? step.premises /\
      Cons? (Cons?.tl step.premises))
    (ensures rule_obligation_met step = false)
= ()


(* L3: Untrusted tool output is always rejected.

   An agent cannot launder untrusted tool output as verified
   content by wrapping it in a ToolResult rule. The trust flag
   is part of the evidence — it cannot be omitted.

   This mirrors TACIT's tracked capabilities: tool trust is a
   capability that must be explicitly provided, not assumed. *)

let untrusted_tool_rejected (step: inference_step)
  : Lemma
    (requires
      (match step.rule with
       | RuleToolResult ev -> ev.te_tool_trusted = false
       | _ -> False))
    (ensures rule_obligation_met step = false)
= ()


(* L4: Empty chains are always rejected.

   An agent cannot claim a conclusion without providing any
   inference steps. The empty chain is structurally invalid
   regardless of the observation set.

   This is a frame-rule consequence: you cannot derive new
   knowledge from no reasoning steps. *)

let empty_chain_rejected (obs: list string) (chain: inference_chain)
  : Lemma
    (requires chain.steps == [])
    (ensures chain_well_formed obs chain = false)
= ()


(* L5: Evidence-free derivation is always rejected.

   Even the weakest inference rule (derivation — for domain-
   specific abductive reasoning) requires a non-empty domain
   rule identifier. An agent cannot make completely evidence-free
   claims about the world.

   Strict deployments can further constrain this with a domain
   rule catalog, but the MINIMUM is a non-empty identifier. *)

let ruleless_derivation_rejected (step: inference_step)
  : Lemma
    (requires
      (match step.rule with
       | RuleDerivation ev -> String.length ev.de_domain_rule_id = 0
       | _ -> False))
    (ensures rule_obligation_met step = false)
= ()


(* L6: Derivation with novel tokens is always rejected.

   If a derivation conclusion contains a token that does not appear
   in any premise, the rule obligation MUST fail. This closes the
   Derivation gap: even the weakest inference rule now prevents
   the introduction of information not present in the observations.

   Adopts the LBAC/TypeGuard (Zhou et al.) information flow
   principle: untrusted synthesis cannot introduce novel content
   without passing through a trusted boundary (tool call or
   user confirmation). *)

let novel_token_derivation_rejected (step: inference_step)
  : Lemma
    (requires
      (match step.rule with
       | RuleDerivation ev ->
         String.length ev.de_domain_rule_id > 0 /\
         token_subset step.premises step.step_conclusion = false
       | _ -> False))
    (ensures rule_obligation_met step = false)
= ()


(* L7: Aggregation with novel tokens is always rejected.

   Adopts the same LBAC/TypeGuard (Zhou et al.) information flow
   principle applied to derivation: untrusted synthesis cannot
   introduce tokens not present in any premise, even when the
   conclusion is shorter than the combined premises (length bound
   alone is insufficient — content containment is required).

   classify_rule routes short conclusions to Aggregation rather
   than Derivation. Without this check, short fabrications would
   bypass Derivation's token containment. *)

let novel_token_aggregation_rejected (step: inference_step)
  : Lemma
    (requires
      (match step.rule with
       | RuleAggregation ev ->
         token_subset step.premises step.step_conclusion = false
       | _ -> False))
    (ensures rule_obligation_met step = false)
= ()


(* L8: Contradictions are always rejected.

   If a new fact shares a key with an existing fact but has
   different content, the consistency check MUST fail.
   An agent cannot silently overwrite established knowledge
   without explicit retraction. *)

let contradiction_rejected
  (new_fact: memory_entry)
  (existing: memory_state)
  (witness: memory_entry)
  : Lemma
    (requires
      List.Tot.memP witness existing.facts /\
      witness.me_key = new_fact.me_key /\
      ~(witness.me_content = new_fact.me_content))
    (ensures no_contradiction new_fact existing = false)
= let rec aux (fs: list memory_entry)
    : Lemma
      (requires List.Tot.memP witness fs /\
                witness.me_key = new_fact.me_key /\
                ~(witness.me_content = new_fact.me_content))
      (ensures List.Tot.for_all (fun f -> not (contradicts new_fact f)) fs = false)
      (decreases fs)
  = match fs with
    | [] -> ()
    | f :: rest ->
      if f.me_key = new_fact.me_key && not (f.me_content = new_fact.me_content)
      then ()
      else aux rest
  in
  aux existing.facts


(* L9: Unverified observation guarantees P3 rejection.

   TACIT trust derivation (Odersky et al. 2603.00991): if ANY
   observation has Unverified trust, all_observations_trusted
   returns false, and not_poisoned MUST fail regardless of
   content safety or channel trust.

   This composes with LBAC provenance (Zhou et al.): an injected
   tool message with no matching tool_call declaration receives
   Unverified trust at extraction → TACIT rejects at P3.
   Defense in depth: two independent mechanisms compose to
   prevent injection attacks.

   Quantified: for ALL observation lists containing at least one
   Unverified observation, and ALL entries and poison patterns,
   not_poisoned returns false. *)

let unverified_observation_rejected
  (entry: memory_entry)
  (pp: poison_patterns)
  (observations: list observation)
  (witness: observation)
  : Lemma
    (requires
      List.Tot.memP witness observations /\
      witness.obs_trust = Unverified)
    (ensures not_poisoned entry pp observations = false)
= let rec aux (obs: list observation)
    : Lemma
      (requires List.Tot.memP witness obs /\ witness.obs_trust = Unverified)
      (ensures all_observations_trusted obs = false)
      (decreases obs)
  = match obs with
    | [] -> ()
    | o :: rest ->
      if o.obs_trust = Unverified then ()
      else aux rest
  in
  aux observations


(* L10: Agent-generated observation guarantees P3 rejection.

   An agent cannot launder its own output as evidence by injecting
   an observation with AgentGenerated trust. is_trusted returns
   false for AgentGenerated, so all_observations_trusted fails.

   This prevents the hallucination persistence loop at the
   observation level: even if an agent manages to inject an
   observation into the list, the trust level cannot be
   forged — it must come from the extraction pipeline. *)

let agent_generated_observation_rejected
  (entry: memory_entry)
  (pp: poison_patterns)
  (observations: list observation)
  (witness: observation)
  : Lemma
    (requires
      List.Tot.memP witness observations /\
      witness.obs_trust = AgentGenerated)
    (ensures not_poisoned entry pp observations = false)
= let rec aux (obs: list observation)
    : Lemma
      (requires List.Tot.memP witness obs /\ witness.obs_trust = AgentGenerated)
      (ensures all_observations_trusted obs = false)
      (decreases obs)
  = match obs with
    | [] -> ()
    | o :: rest ->
      if o.obs_trust = AgentGenerated then ()
      else aux rest
  in
  aux observations
