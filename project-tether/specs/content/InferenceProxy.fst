module InferenceProxy

open FStar.List.Tot
open FStar.String
open TetherTypes
open TetherPredicates

(* --- OpenAI Chat Completion API Types ---

   Models the message structure of the OpenAI chat completion API
   as used by the inference proxy. Only the role and content fields
   are relevant for provenance tracking — other fields (model,
   temperature, etc.) do not affect the inference chain. *)

type message_role =
  | RoleTool
  | RoleUser
  | RoleSystem
  | RoleAssistant

noeq
type chat_message = {
  cm_role: message_role;
  cm_content: string;
  cm_tool_calls: list string;
  cm_tool_call_id: option string;
}

(* --- LBAC Provenance Helpers (Zhou et al. 2605.12863) ---

   Pass 1: collect declared tool_call IDs from assistant messages.
   Pass 2: for each tool message, check if its tool_call_id matches
   a declared ID. Matched → ToolOutput trust. Unmatched → Unverified.

   This models the OpenAI chat completion API contract: a tool
   message is only meaningful if the preceding assistant message
   declared a tool_call with a matching ID. An injected tool
   response with a fabricated ID has no provenance chain. *)

let collect_declared_tool_calls (messages: list chat_message) : list string =
  List.Tot.concatMap (fun (m: chat_message) ->
    if m.cm_role = RoleAssistant then m.cm_tool_calls
    else []) messages

let msg_to_obs_lbac (declared: list string) (m: chat_message) : list observation =
  match m.cm_role with
  | RoleTool ->
    let call_id = (match m.cm_tool_call_id with | Some id -> id | None -> "unknown") in
    let trust = (if List.Tot.mem call_id declared then ToolOutput else Unverified) in
    [{ obs_source = "tool";
       obs_content = m.cm_content;
       obs_trust = trust;
       obs_tool_call_id = m.cm_tool_call_id }]
  | RoleUser -> [{ obs_source = "user";
                   obs_content = m.cm_content;
                   obs_trust = ExternalInput;
                   obs_tool_call_id = None }]
  | _ -> []

(* --- Observation Extraction ---

   Two-pass LBAC provenance validation:
   1. Collect all tool_call IDs declared by assistant messages
   2. For each tool/user message, produce an observation with
      trust level determined by provenance matching

   System and assistant messages produce no observations —
   they are instructions or prior completions, not evidence. *)

let extract_observations (messages: list chat_message) : list observation =
  let declared = collect_declared_tool_calls messages in
  List.Tot.concatMap (msg_to_obs_lbac declared) messages

(* --- Automatic Inference Rule Classification ---

   Given a set of observation contents and a conclusion (the LLM's
   response), classifies the inference rule that best describes how
   the conclusion relates to the available evidence:

   1. Identity:    conclusion matches an observation verbatim
                   (faithful relay of tool/user content)
   2. Extraction:  conclusion is a substring of some observation
                   (selected portion of evidence)
   3. Aggregation: conclusion length <= total observation length
                   (synthesis from multiple observations)
   4. Derivation:  fallback — novel content exceeding the available
                   evidence

   The classification is conservative: it assigns the STRONGEST
   rule whose structural precondition is met. Identity is strongest
   (exact match), derivation is weakest (no structural evidence). *)

let classify_rule (obs_contents: list string) (conclusion: string) : inference_rule =
  if List.Tot.existsb (fun o -> o = conclusion) obs_contents then
    RuleIdentity
  else
    match List.Tot.find (fun o -> contains_substring o conclusion) obs_contents with
    | Some matching ->
      RuleExtraction ({ ext_source_premise = matching })
    | None ->
      if String.length conclusion <= total_string_length obs_contents then
        RuleAggregation ({ agg_source_premises = obs_contents })
      else
        RuleDerivation ({ de_domain_rule_id = "llm-inference" })
