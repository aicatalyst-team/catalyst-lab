module TemporalValidity

open FStar.String
open TetherTypes

(* Surface 4: Skill persistence — temporal re-verification

   A skill proven valid at time T may become invalid at time
   T+n if the environment changed. Proof certificates carry
   validity windows. On future reads, the certificate must be
   re-verified for both content integrity (hash match) and
   temporal validity (within the window).

   cf. Pimentel (OPLSS 2026, Modal Logic): temporal validity
   models the difference between knowledge ("I know P holds")
   and belief ("I believe P holds because it held at time T").
   A certificate with an expired window downgrades from
   knowledge to belief. *)

noeq
type temporal_certificate = {
  tc_cert: proof_certificate;
  tc_valid_from: nat;
  tc_valid_until: nat;
}

(* Certificate is within its temporal validity window *)
val certificate_valid_at :
  cert:temporal_certificate ->
  current_time:nat ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==>
      cert.tc_valid_from <= current_time /\
      current_time <= cert.tc_valid_until)

(* Content hash matches — detects post-write tampering *)
val certificate_content_matches :
  cert:proof_certificate ->
  content_hash:string ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==>
      cert.pc_content_hash = content_hash)

(* Combined: certificate is fully valid for re-verification *)
val certificate_reverify :
  tc:temporal_certificate ->
  content_hash:string ->
  current_time:nat ->
  Pure bool
    (requires True)
    (ensures fun b -> b ==>
      certificate_valid_at tc current_time /\
      certificate_content_matches tc.tc_cert content_hash)
