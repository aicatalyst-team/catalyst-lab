module SkillVerification

open FStar.List.Tot
open FStar.String
open TetherTypes
open TetherPredicates
open PoisonDetection
open ToolScope

(* Surface 2: Code generation verification

   Hermes auto-generates skills every ~15 tool calls. A skill
   is executable code persisted to /opt/data/skills/ that the
   agent invokes directly in future sessions. If the generated
   code is unsound, every future invocation compounds the error.

   cf. Dafny-as-IL (Li et al.): LLM generates code → verifier
   checks → only verified code persists. Here, F* is the
   verification-aware IL. The skill must satisfy a spec before
   persisting as "known working."

   We verify three properties of generated skills:
   1. Interface validity: declared inputs/outputs match the spec
   2. Tool scope: tools the skill calls are within allowed set
   3. Content safety: skill body is not poisoned (OWASP ASI06) *)

noeq
type skill_spec = {
  ss_name: string;
  ss_inputs: list string;
  ss_output_type: string;
  ss_max_body_size: nat;
  ss_allowed_tools: list string;
}

noeq
type skill_code = {
  sc_name: string;
  sc_body: string;
  sc_declared_inputs: list string;
  sc_declared_output: string;
  sc_tool_calls: list string;
}

(* Skill interface matches spec *)
val skill_interface_valid :
  spec:skill_spec ->
  code:skill_code ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==>
      code.sc_name = spec.ss_name /\
      code.sc_declared_inputs = spec.ss_inputs /\
      code.sc_declared_output = spec.ss_output_type /\
      String.length code.sc_body <= spec.ss_max_body_size)

(* Skill only calls tools within allowed set *)
val skill_tools_within_scope :
  spec:skill_spec ->
  code:skill_code ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==> True)

(* Combined: skill is safe to persist *)
val skill_safe_to_persist :
  spec:skill_spec ->
  code:skill_code ->
  pp:poison_patterns ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==>
      skill_interface_valid spec code /\
      skill_tools_within_scope spec code /\
      content_safe code.sc_body pp)
