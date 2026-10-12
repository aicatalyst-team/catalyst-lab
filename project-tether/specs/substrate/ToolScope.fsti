module ToolScope

open FStar.List.Tot
open FStar.String

(* Surface 3: Tool invocation verification

   When the agent invokes a tool and observes the result,
   is the observation trustworthy? Untrusted tool output
   entering memory is equivalent to hallucination.

   cf. TACIT (Odersky et al.): tracked capabilities prevent
   capability leakage. Here, tool declarations are capabilities
   — the agent must present a matching declaration to trust
   the output. *)

noeq
type tool_declaration = {
  td_name: string;
  td_allowed_args: list string;
  td_output_type: string;
  td_side_effects: list string;
}

noeq
type tool_call = {
  tc_tool_name: string;
  tc_arguments: list string;
}

noeq
type tool_result = {
  tr_output: string;
  tr_observed_side_effects: list string;
}

(* P9: Tool Scope — call arguments within declared API surface *)
val call_within_scope :
  decl:tool_declaration ->
  call:tool_call ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==> True)

(* P10: Side-effect Containment — observed effects ⊆ declared effects *)
val side_effects_contained :
  decl:tool_declaration ->
  call:tool_call ->
  result:tool_result ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==> True)

(* Combined: tool invocation is safe to trust *)
val tool_invocation_safe :
  decl:tool_declaration ->
  call:tool_call ->
  result:tool_result ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==> True)
