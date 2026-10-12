module CompletenessCheck

open FStar.List.Tot
open TetherTypes
open TetherPredicates

let is_critical (obs: observation) (spec: domain_spec) : bool =
  List.Tot.existsb (fun p -> contains_substring obs.obs_content p) spec.critical_patterns

let covers (fact: memory_entry) (obs: observation) : bool =
  contains_substring fact.me_content obs.obs_content

let all_critical_covered
  (observations: list observation)
  (memory: memory_state)
  (spec: domain_spec)
  : bool
= List.Tot.for_all
    (fun obs ->
      if is_critical obs spec then
        List.Tot.existsb (fun fact -> covers fact obs) memory.facts
      else
        true)
    observations

let required_keys_present
  (memory: memory_state)
  (spec: domain_spec)
  : bool
= List.Tot.for_all
    (fun key -> List.Tot.existsb (fun fact -> fact.me_key = key) memory.facts)
    spec.required_keys

let memory_is_complete
  (observations: list observation)
  (memory: memory_state)
  (spec: domain_spec)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==>
      all_critical_covered observations memory spec /\
      required_keys_present memory spec)
=
  all_critical_covered observations memory spec &&
  required_keys_present memory spec
