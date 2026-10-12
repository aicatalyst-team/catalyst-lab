module VerifiedSkillWrite
#lang-pulse
open Pulse.Lib.Pervasives
open FStar.List.Tot
open FStar.String
open TetherTypes
open PoisonDetection
open SkillVerification
open AgentState

(* Surface 2: Verified Skill Persistence (Pulse/separation logic)

   Hermes auto-generates skills every ~15 tool calls and persists
   them to /opt/data/skills/. A generated skill that is unsound
   will compound errors on every future invocation.

   This module composes the Surface 2 verification checks with
   Pulse separation logic for memory safety:
     - skill_interface_valid (contract match)
     - skill_tools_within_scope (capability check)
     - content_safe (OWASP ASI06)
     - persist_bounded (P5 ownership + P7 bounds)

   The postcondition on SkillWriteOk proves all four properties
   hold AND the skill region now contains the verified code body.
   On failure, the region is unchanged (frame rule).

   cf. Li et al. (Dafny as Verification-Aware IL): F* is the
   verification-aware IL for generated skills. The skill spec
   is the contract; only verified code persists.

   Surface 3 (ToolScope) is NOT integrated here: tool_invocation_safe
   operates at call time (needs a tool_result), not at skill
   persistence time. skill_tools_within_scope already checks
   tool scope at the skill level.

   Surfaces 4-5 are read-path verifications (TemporalValidity,
   ProofTransport) — they verify on read, not on write. *)

type skill_write_result =
  | SkillWriteOk
  | SkillInterfaceFailed
  | SkillScopeFailed
  | SkillPoisoned
  | SkillBoundsFailed

fn verified_skill_write
  (agent: agent_id)
  (region: memory_region)
  (spec: skill_spec)
  (code: skill_code)
  (pp: poison_patterns)
  (bound: nat)
  (#v: erased string)
  requires region |-> v
  returns r: skill_write_result
  ensures (match r with
           | SkillWriteOk -> region |-> code.sc_body **
                            pure (skill_interface_valid spec code /\
                                  skill_tools_within_scope spec code /\
                                  content_safe code.sc_body pp /\
                                  String.length code.sc_body <= bound)
           | SkillInterfaceFailed -> region |-> v
           | SkillScopeFailed -> region |-> v
           | SkillPoisoned -> region |-> v
           | SkillBoundsFailed -> region |-> v)
{
  let p_iface = skill_interface_valid spec code;
  if not p_iface
  {
    SkillInterfaceFailed
  }
  else
  {
    let p_scope = skill_tools_within_scope spec code;
    if not p_scope
    {
      SkillScopeFailed
    }
    else
    {
      let p_safe = content_safe code.sc_body pp;
      if not p_safe
      {
        SkillPoisoned
      }
      else
      {
        let wrote = persist_bounded agent region code.sc_body bound;
        if wrote
        {
          SkillWriteOk
        }
        else
        {
          SkillBoundsFailed
        }
      }
    }
  }
}
