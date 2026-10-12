module ProofTransport

open FStar.List.Tot
open FStar.String
open TetherTypes

(* --- Witness well-formedness ---
   A proof witness must identify its source agent, carry
   a non-empty content hash, reference at least one
   observation, and come from a trusted source.

   An empty source_agent means the witness is orphaned —
   no agent claims responsibility for the proof. *)

let witness_well_formed
  (witness: proof_witness)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==>
      String.length witness.pw_source_agent > 0 /\
      String.length witness.pw_content_hash > 0 /\
      witness.pw_obs_count > 0 /\
      witness.pw_source_trusted)
=
  String.length witness.pw_source_agent > 0 &&
  String.length witness.pw_content_hash > 0 &&
  witness.pw_obs_count > 0 &&
  witness.pw_source_trusted


(* --- Cross-agent verification ---
   Agent B reads a fact stored by Agent A. The witness
   carries A's proof evidence. B checks:
   1. Witness is well-formed (has source, hash, trust)
   2. Content hash matches the stored content

   If both hold, B can trust the fact at the level A proved.
   B does NOT need access to A's observations or inference
   chain — the witness is self-contained. *)

let cross_agent_verify
  (witness: proof_witness)
  (stored_content_hash: string)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==>
      witness_well_formed witness /\
      witness.pw_content_hash = stored_content_hash)
=
  witness_well_formed witness &&
  witness.pw_content_hash = stored_content_hash


(* --- Minimum property check ---
   The witness must satisfy a minimum set of properties
   for the reading agent's trust policy. For example,
   a strict agent might require P1+P2+P3, while a
   permissive agent might accept P1 alone. *)

let witness_has_minimum_properties
  (witness: proof_witness)
  (required: list string)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==> True)
=
  List.Tot.for_all
    (fun req ->
      List.Tot.existsb (fun prop -> prop = req) witness.pw_properties)
    required
