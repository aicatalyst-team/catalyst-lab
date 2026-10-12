module AgentState
#lang-pulse
open Pulse.Lib.Pervasives

let agent_id = string
let memory_region = ref string
let tier1_bound : nat = 2200

(* P5: Ownership — agent owns the memory region it writes to *)
val persist (agent: agent_id) (region: memory_region) (content: string) (#v: erased string)
  : stt unit
    (requires region |-> v)
    (ensures fun _ -> region |-> content)

(* P7: Bounds Enforcement — write only if content fits within bound *)
val persist_bounded (agent: agent_id) (region: memory_region) (content: string) (bound: nat) (#v: erased string)
  : stt bool
    (requires region |-> v)
    (ensures fun b ->
      if b then region |-> content ** pure (String.length content <= bound)
      else region |-> v)
