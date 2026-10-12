module ProxyLemmas

open FStar.String
open FStar.List.Tot
open TetherTypes
open TetherPredicates
open InferenceProxy

(* === Proxy Incorrectness Lemmas ===

   Content properties (LP1-LP3): classify_rule correctly identifies
   verbatim relays, rejects novel content, defaults to derivation.

   Provenance properties (LP4-LP5): extract_observations assigns
   trust levels based on LBAC tool_call matching — unmatched tool
   responses are not trusted, matched ones are trusted.

   Together with L9/L10 in TetherLemmas (TACIT), these ensure the
   proxy cannot bypass the verification gate. *)


(* --- Helpers to avoid hasEq issues on noeq types --- *)

let is_role_tool (m: chat_message) : bool =
  match m.cm_role with RoleTool -> true | _ -> false

let is_role_system_or_assistant (m: chat_message) : bool =
  match m.cm_role with RoleSystem | RoleAssistant -> true | _ -> false

let has_call_id (m: chat_message) (call_id: string) : bool =
  match m.cm_tool_call_id with
  | Some id -> id = call_id
  | None -> false


(* --- Content Auxiliary Lemmas --- *)


let rec tool_msg_in_obs
  (declared: list string)
  (messages: list chat_message)
  (conclusion: string)
  : Lemma
    (requires existsb (fun m -> is_role_tool m && m.cm_content = conclusion) messages)
    (ensures existsb (fun (s: string) -> s = conclusion)
               (map (fun (o: observation) -> o.obs_content)
                    (concatMap (msg_to_obs_lbac declared) messages)))
    (decreases messages)
= match messages with
  | [] -> ()
  | m :: rest ->
    if is_role_tool m && m.cm_content = conclusion then ()
    else tool_msg_in_obs declared rest conclusion


let rec novel_not_in_obs
  (declared: list string)
  (messages: list chat_message)
  (conclusion: string)
  : Lemma
    (requires for_all (fun m -> not (m.cm_content = conclusion)) messages)
    (ensures existsb (fun (s: string) -> s = conclusion)
               (map (fun (o: observation) -> o.obs_content)
                    (concatMap (msg_to_obs_lbac declared) messages)) = false)
    (decreases messages)
= match messages with
  | [] -> ()
  | m :: rest ->
    novel_not_in_obs declared rest conclusion


let rec system_assistant_no_obs
  (declared: list string)
  (messages: list chat_message)
  : Lemma
    (requires for_all (fun m -> is_role_system_or_assistant m) messages)
    (ensures concatMap (msg_to_obs_lbac declared) messages == [])
    (decreases messages)
= match messages with
  | [] -> ()
  | m :: rest -> system_assistant_no_obs declared rest


(* --- Content Classification Lemmas (LP1-LP3) --- *)


let verbatim_relay_verified (messages: list chat_message) (conclusion: string)
  : Lemma
    (requires List.Tot.existsb (fun m -> is_role_tool m && m.cm_content = conclusion) messages)
    (ensures (let obs = extract_observations messages in
              let obs_c = List.Tot.map (fun (o: observation) -> o.obs_content) obs in
              RuleIdentity? (classify_rule obs_c conclusion)))
= let declared = collect_declared_tool_calls messages in
  tool_msg_in_obs declared messages conclusion


let novel_content_not_identity (messages: list chat_message) (conclusion: string)
  : Lemma
    (requires List.Tot.for_all (fun m -> not (m.cm_content = conclusion)) messages)
    (ensures (let obs = extract_observations messages in
              let obs_c = List.Tot.map (fun (o: observation) -> o.obs_content) obs in
              RuleIdentity? (classify_rule obs_c conclusion) = false))
= let declared = collect_declared_tool_calls messages in
  novel_not_in_obs declared messages conclusion


let no_evidence_means_derivation (messages: list chat_message) (conclusion: string)
  : Lemma
    (requires List.Tot.for_all (fun m -> is_role_system_or_assistant m) messages /\
             String.length conclusion > 0)
    (ensures (let obs = extract_observations messages in
              let obs_c = List.Tot.map (fun (o: observation) -> o.obs_content) obs in
              List.Tot.length obs_c = 0 /\
              RuleDerivation? (classify_rule obs_c conclusion)))
= let declared = collect_declared_tool_calls messages in
  system_assistant_no_obs declared messages


(* --- LBAC Provenance Helpers ---

   existsb distributes over append (left introduction), and
   msg_to_obs_lbac trust-level helpers that pattern-match on
   the message to give Z3 concrete constructor shapes.

   msg_to_obs_lbac uses List.Tot.mem (first-order) internally to
   check declared tool_call membership. Using mem in the preconditions
   here lets Z3 apply congruence closure to connect the precondition
   with the trust determination inside msg_to_obs_lbac, avoiding the
   closure comparison issue that arises with existsb-with-lambda. *)


let rec existsb_append_intro_l (#a: Type) (p: a -> bool) (l1 l2: list a)
  : Lemma (requires existsb p l1) (ensures existsb p (l1 @ l2))
= match l1 with
  | [] -> ()
  | hd :: tl -> if p hd then () else existsb_append_intro_l p tl l2


(* Tool message with unmatched call_id produces an untrusted observation.
   Pattern matching on m.cm_role and m.cm_tool_call_id gives Z3 the
   concrete constructor shapes needed to unfold msg_to_obs_lbac. *)
let tool_obs_untrusted
  (declared: list string) (m: chat_message) (call_id: string)
  : Lemma
    (requires is_role_tool m /\ has_call_id m call_id /\
              not (mem call_id declared))
    (ensures existsb
               (fun (o: observation) -> o.obs_content = m.cm_content && not (is_trusted o.obs_trust))
               (msg_to_obs_lbac declared m))
= match m.cm_role, m.cm_tool_call_id with
  | RoleTool, Some _ -> ()
  | _, _ -> ()


(* Tool message with matched call_id produces a trusted observation. *)
let tool_obs_trusted
  (declared: list string) (m: chat_message) (call_id: string)
  : Lemma
    (requires is_role_tool m /\ has_call_id m call_id /\
              mem call_id declared)
    (ensures existsb
               (fun (o: observation) -> o.obs_content = m.cm_content && is_trusted o.obs_trust)
               (msg_to_obs_lbac declared m))
= match m.cm_role, m.cm_tool_call_id with
  | RoleTool, Some _ -> ()
  | _, _ -> ()


(* --- LBAC Provenance Lemmas (LP4-LP5, Zhou et al. 2605.12863) ---

   These use is_trusted / not (is_trusted ...) rather than equality
   on trust_level, which:
   1. Avoids hasEq issues with noeq enum types
   2. Composes directly with L9 (all_observations_trusted)

   The precondition uses List.Tot.mem (first-order) rather than
   existsb-with-lambda because msg_to_obs_lbac also uses mem
   internally. This lets Z3 apply congruence closure to connect
   the precondition with the trust determination inside
   msg_to_obs_lbac. *)


(* LP4: Unmatched tool message produces an untrusted observation.

   If a tool message has tool_call_id matching call_id, and call_id
   does not appear in the declared tool_calls set, the observation
   for that message is NOT trusted (is_trusted returns false).

   End-to-end composition:
   LP4 (untrusted obs) -> L9 (all_observations_trusted = false)
   -> not_poisoned = false -> P3 rejects -> write blocked. *)

let rec unmatched_tool_not_trusted
  (declared: list string)
  (messages: list chat_message)
  (call_id: string)
  (content: string)
  : Lemma
    (requires
      List.Tot.existsb (fun (m: chat_message) ->
        is_role_tool m && has_call_id m call_id && m.cm_content = content) messages /\
      not (List.Tot.mem call_id declared))
    (ensures
      List.Tot.existsb
        (fun (o: observation) -> o.obs_content = content && not (is_trusted o.obs_trust))
        (concatMap (msg_to_obs_lbac declared) messages))
    (decreases messages)
= match messages with
  | [] -> ()
  | m :: rest ->
    if is_role_tool m && has_call_id m call_id && m.cm_content = content
    then begin
      tool_obs_untrusted declared m call_id;
      existsb_append_intro_l
        (fun (o: observation) -> o.obs_content = content && not (is_trusted o.obs_trust))
        (msg_to_obs_lbac declared m)
        (concatMap (msg_to_obs_lbac declared) rest)
    end
    else unmatched_tool_not_trusted declared rest call_id content

let unmatched_tool_gets_unverified
  (messages: list chat_message)
  (call_id: string)
  (content: string)
  : Lemma
    (requires
      List.Tot.existsb (fun (m: chat_message) ->
        is_role_tool m && has_call_id m call_id && m.cm_content = content) messages /\
      not (List.Tot.mem call_id (collect_declared_tool_calls messages)))
    (ensures
      List.Tot.existsb
        (fun (o: observation) -> o.obs_content = content && not (is_trusted o.obs_trust))
        (extract_observations messages))
= unmatched_tool_not_trusted (collect_declared_tool_calls messages) messages call_id content


(* LP5: Matched tool message produces a trusted observation.

   If a tool message has tool_call_id matching call_id, and call_id
   appears in the declared tool_calls set, the observation is
   trusted (is_trusted returns true).

   This is the legitimate provenance chain: assistant declares
   tool_call -> tool responds -> LBAC matches -> trusted. *)

let rec matched_tool_is_trusted
  (declared: list string)
  (messages: list chat_message)
  (call_id: string)
  (content: string)
  : Lemma
    (requires
      List.Tot.existsb (fun (m: chat_message) ->
        is_role_tool m && has_call_id m call_id && m.cm_content = content) messages /\
      List.Tot.mem call_id declared)
    (ensures
      List.Tot.existsb
        (fun (o: observation) -> o.obs_content = content && is_trusted o.obs_trust)
        (concatMap (msg_to_obs_lbac declared) messages))
    (decreases messages)
= match messages with
  | [] -> ()
  | m :: rest ->
    if is_role_tool m && has_call_id m call_id && m.cm_content = content
    then begin
      tool_obs_trusted declared m call_id;
      existsb_append_intro_l
        (fun (o: observation) -> o.obs_content = content && is_trusted o.obs_trust)
        (msg_to_obs_lbac declared m)
        (concatMap (msg_to_obs_lbac declared) rest)
    end
    else matched_tool_is_trusted declared rest call_id content

let matched_tool_gets_trusted
  (messages: list chat_message)
  (call_id: string)
  (content: string)
  : Lemma
    (requires
      List.Tot.existsb (fun (m: chat_message) ->
        is_role_tool m && has_call_id m call_id && m.cm_content = content) messages /\
      List.Tot.mem call_id (collect_declared_tool_calls messages))
    (ensures
      List.Tot.existsb
        (fun (o: observation) -> o.obs_content = content && is_trusted o.obs_trust)
        (extract_observations messages))
= matched_tool_is_trusted (collect_declared_tool_calls messages) messages call_id content
