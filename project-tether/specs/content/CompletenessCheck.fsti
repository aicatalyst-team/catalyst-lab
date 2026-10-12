module CompletenessCheck

open FStar.List.Tot
open TetherTypes
open TetherPredicates

val is_critical : obs:observation -> spec:domain_spec -> bool

val covers : fact:memory_entry -> obs:observation -> bool

val all_critical_covered :
  observations:list observation ->
  memory:memory_state ->
  spec:domain_spec ->
  bool

val required_keys_present :
  memory:memory_state ->
  spec:domain_spec ->
  bool

val memory_is_complete :
  observations:list observation ->
  memory:memory_state ->
  spec:domain_spec ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==>
      all_critical_covered observations memory spec /\
      required_keys_present memory spec)
