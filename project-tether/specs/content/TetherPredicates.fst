module TetherPredicates

open FStar.List.Tot
open FStar.String
open TetherTypes

(* --- Trust helpers --- *)

let is_trusted (t: trust_level) : bool =
  match t with
  | DirectObservation -> true
  | ToolOutput -> true
  | ExternalInput -> true
  | AgentGenerated -> false
  | Unverified -> false

let all_observations_trusted (observations: list observation) : bool =
  List.Tot.for_all (fun (o: observation) -> is_trusted o.obs_trust) observations

(* --- Structural chain helpers --- *)

let step_premises_valid
  (known: list string)
  (step: inference_step)
  : bool
= List.Tot.for_all (fun premise -> List.Tot.existsb (fun k -> k = premise) known) step.premises

(* --- String matching --- *)

let rec contains_substring_aux
  (haystack: string)
  (needle: string)
  (len_h: nat{len_h = String.length haystack})
  (len_n: nat{len_n = String.length needle})
  (i: nat{i <= len_h})
  : Tot bool (decreases (len_h - i))
= if i + len_n > len_h then false
  else if String.sub haystack i len_n = needle then true
  else if i + 1 > len_h then false
  else contains_substring_aux haystack needle len_h len_n (i + 1)

let contains_substring (haystack needle: string) : bool =
  let len_n = String.length needle in
  if len_n = 0 then true
  else contains_substring_aux haystack needle (String.length haystack) len_n 0

let contains_substring_ci (haystack needle: string) : bool =
  contains_substring (String.lowercase haystack) (String.lowercase needle)

(* --- Rule validators --- *)

let rec total_string_length (strs: list string) : Tot nat (decreases strs) =
  match strs with
  | [] -> 0
  | s :: rest -> String.length s + total_string_length rest

let identity_valid (step: inference_step) : bool =
  match step.premises with
  | [single] -> step.step_conclusion = single
  | _ -> false

let extraction_valid (step: inference_step) (ev: extraction_evidence) : bool =
  List.Tot.existsb (fun p -> p = ev.ext_source_premise) step.premises &&
  contains_substring ev.ext_source_premise step.step_conclusion

let tool_result_valid (_step: inference_step) (ev: tool_evidence) : bool =
  ev.te_tool_trusted

let split_words (s: string) : list string =
  List.Tot.filter (fun w -> String.length w > 0) (String.split [' '] s)

let rec collect_words (strs: list string) : Tot (list string) (decreases strs) =
  match strs with
  | [] -> []
  | s :: rest -> split_words s @ collect_words rest

let token_subset (premises: list string) (conclusion: string) : bool =
  let premise_words = collect_words premises in
  let conclusion_words = split_words conclusion in
  List.Tot.for_all
    (fun w -> List.Tot.existsb (fun pw -> pw = w) premise_words)
    conclusion_words

let aggregation_valid (step: inference_step) (ev: aggregation_evidence) : bool =
  List.Tot.for_all
    (fun p -> List.Tot.existsb (fun sp -> sp = p) step.premises)
    ev.agg_source_premises &&
  List.Tot.for_all
    (fun sp -> List.Tot.existsb (fun p -> p = sp) ev.agg_source_premises)
    step.premises &&
  String.length step.step_conclusion <= total_string_length ev.agg_source_premises &&
  token_subset step.premises step.step_conclusion

let derivation_valid (step: inference_step) (ev: derivation_evidence) : bool =
  String.length ev.de_domain_rule_id > 0 &&
  token_subset step.premises step.step_conclusion

let rule_obligation_met (step: inference_step) : bool =
  match step.rule with
  | RuleIdentity -> identity_valid step
  | RuleExtraction ev -> extraction_valid step ev
  | RuleAggregation ev -> aggregation_valid step ev
  | RuleToolResult ev -> tool_result_valid step ev
  | RuleDerivation ev -> derivation_valid step ev

(* --- Chain well-formedness (structural + semantic) --- *)

let rec chain_well_formed_aux
  (known: list string)
  (steps: list inference_step)
  : Tot bool (decreases steps)
= match steps with
  | [] -> true
  | s :: rest ->
    step_premises_valid known s &&
    rule_obligation_met s &&
    chain_well_formed_aux (s.step_conclusion :: known) rest

let chain_well_formed
  (obs_contents: list string)
  (chain: inference_chain)
  : bool
= match chain.steps with
  | [] -> false
  | _ ->
    let last_step = List.Tot.last chain.steps in
    chain_well_formed_aux obs_contents chain.steps &&
    last_step.step_conclusion = chain.final_conclusion

(* --- Memory predicates --- *)

let contradicts (a b: memory_entry) : bool =
  a.me_key = b.me_key && not (a.me_content = b.me_content)

let no_contradiction
  (new_fact: memory_entry)
  (existing: memory_state)
  : bool
= List.Tot.for_all (fun f -> not (contradicts new_fact f)) existing.facts

let rec total_size (entries: list memory_entry) : Tot nat (decreases entries) =
  match entries with
  | [] -> 0
  | e :: rest -> String.length e.me_content + total_size rest

let memory_size (st: memory_state) : nat = total_size st.facts
