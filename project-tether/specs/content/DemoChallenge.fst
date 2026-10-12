module DemoChallenge

open FStar.List.Tot
open FStar.String
open TetherTypes
open TetherPredicates

(* ═══════════════════════════════════════════════════════════════
   Demo Challenge — Professor Coblenz, July 25, 2026

   Three fully proved lemmas. Originally presented with admit()
   holes for a live demo; all proofs completed July 2026.

   Each lemma proves a SAFETY property about the Tether
   verification pipeline — these are incorrectness lemmas
   in the style of Gardner (OPLSS 2026): they show that
   specific attack patterns are NECESSARILY rejected.

   Difficulty: progressive.
   ═══════════════════════════════════════════════════════════════ *)


(* ─── L_demo1: Identity requires a premise ───

   The identity rule means "conclusion = observation."
   It requires EXACTLY one premise. If an agent claims
   identity with zero premises, it has no observation to
   ground the conclusion — pure fabrication.

   Prove: identity with empty premises is always rejected. *)

let identity_no_premises_rejected (step: inference_step)
  : Lemma
    (requires RuleIdentity? step.rule /\ step.premises == [])
    (ensures rule_obligation_met step = false)
= ()


(* ─── L_demo2: Identity is exact ───

   The REVERSE direction: if identity_valid SUCCEEDS, then
   the conclusion is EXACTLY the sole premise. No transformation,
   no synthesis, no summarization — pure relay.

   This is the core guarantee preventing hallucination
   persistence: what enters memory is literally what was
   observed.

   Prove: identity_valid = true implies conclusion equals
   the single premise. *)

let identity_is_exact (step: inference_step)
  : Lemma
    (requires
      RuleIdentity? step.rule /\
      identity_valid step = true)
    (ensures
      (match step.premises with
       | [single] -> step.step_conclusion = single
       | _ -> False))
= ()


(* ─── L_demo3: Novel tokens are rejected ───

   Even at the weakest verification level (RuleDerivation —
   domain-specific reasoning), the system enforces content
   containment. An agent cannot introduce tokens in its
   conclusion that do not appear in any premise.

   This adopts the LBAC/TypeGuard (Zhou et al.) information
   flow principle: untrusted synthesis cannot introduce novel
   content without passing through a trusted boundary.

   Prove: derivation with novel tokens is rejected,
   even when the domain rule ID is valid. *)

let derivation_novel_tokens_rejected (step: inference_step)
  : Lemma
    (requires
      (match step.rule with
       | RuleDerivation ev ->
           String.length ev.de_domain_rule_id > 0 /\
           token_subset step.premises step.step_conclusion = false
       | _ -> False))
    (ensures rule_obligation_met step = false)
= ()
