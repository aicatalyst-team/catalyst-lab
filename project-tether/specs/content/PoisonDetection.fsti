module PoisonDetection

open FStar.List.Tot
open TetherTypes
open TetherPredicates

val contains_any_pattern : content:string -> patterns:list string -> bool

val contains_instruction_override : content:string -> pp:poison_patterns -> bool
val contains_role_escalation : content:string -> pp:poison_patterns -> bool
val contains_exfiltration_pattern : content:string -> pp:poison_patterns -> bool

val content_safe :
  content:string ->
  pp:poison_patterns ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==>
      ~(contains_instruction_override content pp) /\
      ~(contains_role_escalation content pp) /\
      ~(contains_exfiltration_pattern content pp))
