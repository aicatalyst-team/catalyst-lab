module SkillVerification

open FStar.List.Tot
open FStar.String
open TetherTypes
open TetherPredicates
open PoisonDetection
open ToolScope

(* --- Skill interface validity ---
   The generated skill's declared interface must match the
   spec: same name, same inputs, same output type, and body
   within the size bound. This is the Dafny-as-IL pattern:
   the spec is the contract, the generated code must conform. *)

let skill_interface_valid
  (spec: skill_spec)
  (code: skill_code)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==>
      code.sc_name = spec.ss_name /\
      code.sc_declared_inputs = spec.ss_inputs /\
      code.sc_declared_output = spec.ss_output_type /\
      String.length code.sc_body <= spec.ss_max_body_size)
=
  code.sc_name = spec.ss_name &&
  code.sc_declared_inputs = spec.ss_inputs &&
  code.sc_declared_output = spec.ss_output_type &&
  String.length code.sc_body <= spec.ss_max_body_size


(* --- Skill tool scope ---
   Every tool the skill calls must be in the spec's allowed
   tool set. Prevents a generated skill from calling tools
   the agent shouldn't have access to — capability escalation
   via code generation. *)

let skill_tools_within_scope
  (spec: skill_spec)
  (code: skill_code)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==> True)
=
  List.Tot.for_all
    (fun tool_call ->
      List.Tot.existsb (fun allowed -> allowed = tool_call) spec.ss_allowed_tools)
    code.sc_tool_calls


(* --- Combined skill verification ---
   A skill is safe to persist if and only if:
   1. Its interface matches the spec (Dafny-as-IL contract)
   2. Its tool calls are within scope (TACIT capability check)
   3. Its body is not poisoned (OWASP ASI06)

   All three must hold. If any fails, the skill is rejected
   and not written to /opt/data/skills/. *)

let skill_safe_to_persist
  (spec: skill_spec)
  (code: skill_code)
  (pp: poison_patterns)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==>
      skill_interface_valid spec code /\
      skill_tools_within_scope spec code /\
      content_safe code.sc_body pp)
=
  skill_interface_valid spec code &&
  skill_tools_within_scope spec code &&
  content_safe code.sc_body pp
