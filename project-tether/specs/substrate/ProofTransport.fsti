module ProofTransport

open FStar.List.Tot
open FStar.String
open TetherTypes

(* Surface 5: Multi-agent proof witness transport

   When Agent A persists a fact with a proof certificate and
   Agent B reads it in a different session, B must be able to
   verify A's proof without access to A's private state.

   The proof witness is self-contained: it carries the content
   hash, the rule used, the properties satisfied, and the
   source agent identity. B verifies the witness against the
   stored content — if the hash matches and the witness is
   well-formed, B can trust the fact at the level A proved.

   cf. Gay (OPLSS 2026, Session Types): the agent→persist→read
   protocol is a session type. The proof witness is the message
   payload that must conform to the session protocol.

   cf. TACIT (Odersky et al.): cross-agent proof transport
   parallels their MCP server capability delegation. The proof
   witness is a delegated capability — B receives A's proof
   as a capability to trust the stored fact. *)

noeq
type proof_witness = {
  pw_source_agent: string;
  pw_content_hash: string;
  pw_rule_used: inference_rule;
  pw_properties: list string;
  pw_obs_count: nat;
  pw_source_trusted: bool;
}

(* Witness is well-formed: has required fields *)
val witness_well_formed :
  witness:proof_witness ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==>
      String.length witness.pw_source_agent > 0 /\
      String.length witness.pw_content_hash > 0 /\
      witness.pw_obs_count > 0 /\
      witness.pw_source_trusted)

(* Cross-agent verification: witness matches stored content *)
val cross_agent_verify :
  witness:proof_witness ->
  stored_content_hash:string ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==>
      witness_well_formed witness /\
      witness.pw_content_hash = stored_content_hash)

(* Witness carries minimum properties for trust *)
val witness_has_minimum_properties :
  witness:proof_witness ->
  required:list string ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==> True)
