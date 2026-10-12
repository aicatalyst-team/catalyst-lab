module TemporalValidity

open FStar.String
open TetherTypes

(* --- Temporal validity check ---
   The certificate was issued at tc_valid_from and expires
   at tc_valid_until. A read at current_time must fall
   within this window. Outside the window, the certificate
   is stale — the agent must re-verify or re-derive. *)

let certificate_valid_at
  (cert: temporal_certificate)
  (current_time: nat)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==>
      cert.tc_valid_from <= current_time /\
      current_time <= cert.tc_valid_until)
=
  cert.tc_valid_from <= current_time &&
  current_time <= cert.tc_valid_until


(* --- Content integrity check ---
   SHA-256 of stored content must match the hash recorded
   in the certificate at write time. A mismatch means the
   content was modified after verification — tampering. *)

let certificate_content_matches
  (cert: proof_certificate)
  (content_hash: string)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==>
      cert.pc_content_hash = content_hash)
=
  cert.pc_content_hash = content_hash


(* --- Combined re-verification ---
   Both temporal and content checks must pass. *)

let certificate_reverify
  (tc: temporal_certificate)
  (content_hash: string)
  (current_time: nat)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==>
      certificate_valid_at tc current_time /\
      certificate_content_matches tc.tc_cert content_hash)
=
  certificate_valid_at tc current_time &&
  certificate_content_matches tc.tc_cert content_hash
