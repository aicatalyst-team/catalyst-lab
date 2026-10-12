module PoisonDetection

open FStar.List.Tot
open TetherTypes
open TetherPredicates

let contains_any_pattern (content: string) (patterns: list string) : bool =
  List.Tot.existsb (fun p -> contains_substring_ci content p) patterns

let contains_instruction_override (content: string) (pp: poison_patterns) : bool =
  contains_any_pattern content pp.instruction_overrides

let contains_role_escalation (content: string) (pp: poison_patterns) : bool =
  contains_any_pattern content pp.role_escalations

let contains_exfiltration_pattern (content: string) (pp: poison_patterns) : bool =
  contains_any_pattern content pp.exfiltration_markers

let content_safe
  (content: string)
  (pp: poison_patterns)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==>
      ~(contains_instruction_override content pp) /\
      ~(contains_role_escalation content pp) /\
      ~(contains_exfiltration_pattern content pp))
=
  not (contains_instruction_override content pp) &&
  not (contains_role_escalation content pp) &&
  not (contains_exfiltration_pattern content pp)
