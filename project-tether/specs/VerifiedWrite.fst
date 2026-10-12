module VerifiedWrite
#lang-pulse
open Pulse.Lib.Pervasives
open FStar.List.Tot
open TetherTypes
open TetherPredicates
open PoisonDetection
open CompletenessCheck
open AgentReasoning
open AgentState

type write_result =
  | WriteOk
  | ContentFailed
  | PoisonDetected
  | IncompleteCoverage
  | BoundsFailed

fn verified_write
  (agent: agent_id)
  (region: memory_region)
  (observations: list observation)
  (chain: inference_chain)
  (conclusion: memory_entry)
  (existing: memory_state)
  (bound: nat)
  (pp: poison_patterns)
  (spec: domain_spec)
  (#v: erased string)
  requires region |-> v
  returns r: write_result
  ensures (match r with
           | WriteOk -> region |-> conclusion.me_content **
                        pure (chain_well_formed (List.Tot.map (fun (o: observation) -> o.obs_content) observations) chain /\
                              chain.final_conclusion = conclusion.me_content /\
                              no_contradiction conclusion existing /\
                              content_safe conclusion.me_content pp /\
                              conclusion.me_source_trusted /\
                              all_observations_trusted observations /\
                              memory_is_complete observations ({ facts = conclusion :: existing.facts }) spec /\
                              String.length conclusion.me_content <= bound)
           | ContentFailed -> region |-> v
           | PoisonDetected -> region |-> v
           | IncompleteCoverage -> region |-> v
           | BoundsFailed -> region |-> v)
{
  let p1 = inference_sound observations chain conclusion;
  let p2 = consistent_with conclusion existing;
  if not (p1 && p2)
  {
    ContentFailed
  }
  else
  {
    let p3 = not_poisoned conclusion pp observations;
    if not p3
    {
      PoisonDetected
    }
    else
    {
      let updated = { facts = conclusion :: existing.facts };
      let p4 = memory_complete observations updated spec;
      if not p4
      {
        IncompleteCoverage
      }
      else
      {
        let wrote = persist_bounded agent region conclusion.me_content bound;
        if wrote
        {
          WriteOk
        }
        else
        {
          BoundsFailed
        }
      }
    }
  }
}
