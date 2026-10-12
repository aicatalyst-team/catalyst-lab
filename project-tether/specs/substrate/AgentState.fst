module AgentState
#lang-pulse
open Pulse.Lib.Pervasives

(* P5: Ownership — separation logic proof that agent owns the region *)
fn persist (agent: agent_id) (region: memory_region) (content: string) (#v: erased string)
  requires region |-> v
  ensures  region |-> content
{
  region := content
}

(* P7: Bounds Enforcement — write only if content fits within bound *)
fn persist_bounded (agent: agent_id) (region: memory_region) (content: string) (bound: nat) (#v: erased string)
  requires region |-> v
  returns b: bool
  ensures (if b then region |-> content ** pure (String.length content <= bound)
           else region |-> v)
{
  if (String.length content <= bound)
  {
    region := content;
    true
  }
  else
  {
    false
  }
}
