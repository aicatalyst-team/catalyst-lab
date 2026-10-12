module ToolScope

open FStar.List.Tot
open FStar.String

(* --- P9: Tool Scope ---
   The agent's tool call arguments must be within the
   declared API surface of the tool. This prevents an
   agent from invoking a tool with fabricated arguments
   that the tool wasn't designed to handle.

   cf. LBAC/TypeGuard: tool access requires matching the
   declared interface. Here, the declaration IS the type. *)

let call_within_scope
  (decl: tool_declaration)
  (call: tool_call)
  : Pure bool (requires True) (ensures fun b -> b ==> True)
= call.tc_tool_name = decl.td_name &&
  List.Tot.for_all
    (fun arg -> List.Tot.existsb (fun allowed -> allowed = arg) decl.td_allowed_args)
    call.tc_arguments


(* --- P10: Side-effect Containment ---
   The observed side effects of a tool invocation must be
   a subset of the declared side effects. An undeclared
   side effect indicates the tool behaved unexpectedly —
   its output should not be trusted.

   cf. TACIT: capture checking ensures capabilities don't
   leak. Here, side-effect declarations are the capabilities
   — undeclared effects are leaks. *)

let side_effects_contained
  (decl: tool_declaration)
  (_call: tool_call)
  (result: tool_result)
  : Pure bool (requires True) (ensures fun b -> b ==> True)
= List.Tot.for_all
    (fun observed ->
      List.Tot.existsb (fun declared -> declared = observed) decl.td_side_effects)
    result.tr_observed_side_effects


(* --- Combined check --- *)

let tool_invocation_safe
  (decl: tool_declaration)
  (call: tool_call)
  (result: tool_result)
  : Pure bool (requires True) (ensures fun b -> b ==> True)
= call_within_scope decl call &&
  side_effects_contained decl call result
