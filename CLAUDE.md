You must adhere to the following non-negotiable standards:

Prioritise clarity, rigour, and scalability over brevity.

LANGUAGE AND STYLE REQUIREMENTS

Use British English spelling throughout (e.g. "optimisation", "initialisation", "colour"), except where American spelling appears in official protocol names, technical standards, header fields, or library-defined identifiers.

When a colon introduces a complete independent clause — one that could stand as a sentence in its own right — capitalise the first word of that clause. When the colon introduces a phrase, subordinate clause, or list that is grammatically dependent on what precedes it, do not capitalise. Avoid the construction '[noun phrase] is: [full clause]'; instead restructure to make the clause the direct complement of its governing verb, or lead directly with the normative subject (e.g. not 'The normative behaviour for X is: the service shall return…' but 'For X, the service shall return…').

CODE AND NAMING REQUIREMENTS

All code must be self-documenting.

No abbreviations or acronyms are permitted in variable names, function names, class names, inline comments, or import aliases. E.g. no 'img' instead of 'image', no 'llm' instead of 'large_language_model', etc. The only exceptions to this are 'ID', 'KB', 'MB', 'GB', 'CPU', 'GPU', 'I/O', 'DevOps', 'HTTP', 'URL', 'JSON', 'API', 'UUID', 'NSFW', 'NFR', 'FR', 'RO', 'PNG', 'JPG', 'JPEG', 'IP', 'CORS', 'CUDA', 'TCP', 'CLIP', 'GGUF', all file extension abbreviations, 'VRAM', 'RAM', 'GDPR', 'WSL2', 'WSL', 'JIT', 'HPA', 'ASGI', 'WSGI'. No other exceptions, apart from the following which must never be touched:

- Python built-ins (max, min, len, id, etc.)
- Magic methods (__init__, __str__, etc.)
- Dunder attributes
- Decorators required by frameworks
- Protocol method names
- Reserved keywords
- Third-party library symbols
- Standard library symbols

You may introduce additional libraries if justified architecturally.

Imported libraries must not be aliased (e.g. never use "import numpy as np").

Variable and function names must be fully descriptive, even if excessively verbose. These rules apply to all text without exception: variable names, function names, class names, import aliases, inline comments, prose descriptions, section headings, diagram labels, table cells, and configuration examples. No abbreviations or acronyms are permitted in any of these contexts. Sometimes, excessive verbosity may be necessary since the lack of abbreviations or acronyms can introduce vagueness, such as 'client software development kit generation' or 'out-of-memory process termination restarts' or 'Service Level Objective Name' or 'Service Level Indicator Definition'. Whenever there is even the slightest vagueness, I want to prioritise clarity above all else by inserting relational words to group the noun phrase explicitly. So 'client software development kit generation' should be restructured as 'generation of client software development kits'. Similarly: 'out-of-memory process termination restarts' should be restructured as 'restarts triggered by out-of-memory process terminations'; 'Service Level Objective Name' should be restructured as 'Name of the Service Level Objective' (notice how the lack of abbreviations gives rise to this). Unconventional phrasing is not only permitted but required when it eliminates ambiguity — do not avoid a construction merely because it looks unusual. In cases where eliminating ambiguity would violate a naming convention such as the Prometheus {scope}{measurement}{unit} pattern, violate the convention. For example, current_resident_set_size_bytes should be restructured as current_number_of_bytes_of_resident_set_size: the double 'of' is deliberate — number_of_bytes names precisely what is being counted, and of_resident_set_size binds that count to the intact noun phrase, leaving no room for any alternative parse.

This does not mean that every element requires its own relational connector. A leading modifier — whether an adjective or a classifying noun — may appear without a connector of its own, but only when the word it immediately precedes is itself immediately followed by a relational connector. A classifying noun is any word that functions as a noun in other contexts and is used here attributively to name the type or category of the head noun — for example, 'request' in 'request pipeline', 'image' in 'image format', 'service' in 'service error'. An adjective describes a quality or property of the head noun and cannot stand alone as a noun without a change of meaning — for example, 'minimum', 'viable', 'rapid'. When a word could plausibly be read as either (for example, 'structured', 'automated', 'upstream'), treat it as a classifying noun and apply the connector requirement. Relational connectors are prepositions that make a semantic relationship explicit: of, for, by, from, via, under, through, at, in, on, to, with, during, without, per, after, before, between, against, across, into, since, and until all qualify; a comma, a parenthetical, or simple juxtaposition does not. A connector is structurally valid when it is present, but it is semantically valid only when it accurately represents the actual relationship between the two elements it joins. Choosing a generic connector (such as 'for' or 'of') when a more precise one is available is a violation. When selecting a relational connector, test every candidate connector against the relationship before committing. Do not stop at the first plausible option. Each connector carries a distinct meaning and must be selected accordingly:

- 'of' — possession, composition, or membership (size_of_connection_pool)
- 'for' — purpose or intended recipient (system_prompt_for_large_language_model)
- 'by' — agency or production (tokens_generated_by_large_language_model)
- 'from' — origin or source (response_body_from_large_language_model)
- 'to' — direction or destination (requests_to_large_language_model)
- 'via' — medium or protocol used to transmit (message_sent_via_websocket); distinct from 'through', which names a traversed intermediary rather than the transmission medium
- 'under' — condition, governance, or constraint (behaviour_under_load, retries_under_failure)
- 'through' — traversal of an intermediary or stage in a pipeline (requests_routed_through_reverse_proxy); distinct from 'via', which names the medium
- 'at' — specific point, threshold, or rate (latency_at_95th_percentile, timeout_at_seconds)
- 'in' — containment within a boundary or context (field_in_schema, error_in_response_body)
- 'on' — trigger event or mounting surface (handler_on_startup, action_on_failure)
- 'during' — temporal containment within a period or phase (errors_during_shutdown, latency_during_initialisation); distinct from 'in', which denotes structural containment, and from 'on', which denotes a trigger event rather than a sustained period
- 'with' — accompaniment or pairing (request_with_correlation_id, response_with_warnings)
- 'without' — absence of something (request_without_authentication, response_without_body); the semantic inverse of 'with'
- 'per' — rate, ratio, or distribution (requests_per_second, observations_per_endpoint, tokens_per_image)
- 'after' — temporal sequence, subsequent to an event (cleanup_after_shutdown, state_after_recovery); distinct from 'on', which denotes a trigger event rather than sequencing
- 'before' — temporal precedence, prior to an event (validation_before_submission, snapshot_before_migration); the temporal counterpart of 'after'
- 'between' — spanning or relating two endpoints (latency_between_request_and_response, mapping_between_keys_and_values)
- 'against' — comparison or validation (validation_against_schema, check_against_threshold)
- 'across' — spanning multiple discrete instances or boundaries (aggregation_across_endpoints, consistency_across_replicas); distinct from 'through', which denotes traversal of a single intermediary
- 'into' — transformation or insertion (conversion_into_base64, insertion_into_queue); distinct from 'to', which denotes direction or destination without implying transformation
- 'since' — temporal origin, continuously from a past point until the present (elapsed_number_of_seconds_since_last_failure); distinct from 'after', which denotes sequence subsequent to an event, and from 'from', which denotes general origin without implying continuity to the present
- 'until' — temporal endpoint, up to the point when a future event occurs (remaining_number_of_seconds_until_recovery); distinct from 'before', which denotes precedence without implying a countdown, and from 'to', which denotes direction without implying a temporal boundary

Before proposing or committing to a connector, you must explicitly evaluate every connector in the list above against the specific relationship being expressed. For each connector, state whether it fits and why. Only after completing this full evaluation may you select the most precise connector. Skipping candidates or stopping at the first plausible match is a violation, even if the first candidate happens to be correct — the evaluation must still be performed to confirm that no other connector is more precise.

When a bare preposition does not unambiguously convey the nature of the relationship, a participial modifier must be inserted immediately before the preposition to make the semantic relationship explicit. For example, 'maximum_tokens_by_large_language_model' is ambiguous because 'by' alone does not specify what action the large language model performs on the tokens; 'maximum_tokens_generated_by_large_language_model' is unambiguous because 'generated' names the action. The participial modifier is required whenever omitting it would leave the reader unable to determine the specific relationship from the preposition alone. That connector after the word being modified does two things simultaneously: it makes the relationship between the modified word and what follows explicit, and it unambiguously closes the leading modifier's scope at the modified word. In current_number_of_bytes_of_resident_set_size, 'current' is acceptable as a bare leading prefix precisely because 'number' is immediately followed by 'of': the 'of' closes the scope of 'current' at 'number' — confirming that 'current' modifies only 'number' and nothing beyond — while also explicitly connecting 'number' to 'bytes'. Without the 'of' after 'number', the scope of 'current' would be indeterminate: it would be unclear whether 'current' modifies 'number' alone, number_of_bytes as a compound, or number_of_bytes_of_resident_set_size as a whole. The same principle applies in prose: 'categorisation guide for new requirements' is acceptable because 'guide' is immediately followed by 'for', which closes the scope of 'categorisation' at 'guide'; 'verification requirements of the infrastructure' is acceptable because 'requirements' is immediately followed by 'of'. The counterexample makes the rule concrete: 'infrastructure verification requirements' is not acceptable because 'verification' is not terminal — the nominal 'requirements' follows it — and has no connector after it, leaving the scope of 'infrastructure' indeterminate — it cannot be established whether 'infrastructure' modifies 'verification' alone or 'verification requirements' as a compound. Note that 'verification requirements' in isolation would be acceptable under the terminal-element rule stated below; it is specifically 'infrastructure' before a non-terminal 'verification' that creates the violation. Remove the connector from either of the acceptable examples while leaving a further nominal element after the head noun, and the same ambiguity arises immediately; but if removal also makes the head noun terminal, no ambiguity arises.

There is one further case in which a leading modifier may appear without a connector: when the word it immediately precedes is the terminal element of the phrase or identifier — that is, when no further nominal elements (nouns, gerunds, or nominal phrases) follow it. In this position the scope of the leading modifier is unambiguous by construction, since there is only one element it can attach to. 'service logs' and 'load-testing tool' are therefore acceptable: 'logs' and 'tool' are terminal elements with nothing nominal following them.

When a sequence of pure adjectives — not classifying nouns — collectively precede a single head noun, they form a compound adjectival modifier and are evaluated as a unit; no connectors are required between the individual adjectives within the compound, only at the point where the head noun meets what follows it. For example, 'minimum viable implementation' contains two adjectives ('minimum', 'viable') and one head noun ('implementation'): the two adjectives form a compound modifier and require no connector between them. Restructuring 'minimum viable implementation scope' as 'scope of the minimum viable implementation' is therefore sufficient — 'of' connects 'scope' to the compound-modified noun, and within 'minimum viable implementation' no further connectors are needed. When restructuring is required to satisfy the connector rule, use relational prepositions to reorder the phrase; do not convert an adjective to an adverb — for example, if 'automated scaling policy' must be restructured, write 'policy for automated scaling', not 'policy for scaling automatically'. A classifying noun appearing anywhere in the chain reintroduces the full connector requirement, because noun-to-noun and noun-to-adjective relationships are not structurally self-evident in the way that adjective-to-adjective relationships are.

Established technical compound terms whose meaning is not compositionally derivable from their components are treated as atomic noun phrases: no connectors are required between their internal components. Examples include large language model, natural language processing, machine learning, neural network, deep learning, and response body. The criterion for this exemption is that the compound is recognised as a single concept in the field's literature or standards, and that restructuring its internals would produce a phrase with a different or non-standard meaning. The exemption covers only the internal structure of the established term. At the boundary where such a compound acts as a leading modifier before a further noun, the connector requirement applies in full: large language model inference still requires restructuring to inference of large language models, and machine learning pipeline to pipeline for machine learning. When restructuring a phrase to satisfy the connector rules, an established technical compound must never be broken apart. The compound must be kept intact and treated as a single terminal or non-terminal unit during restructuring. For example, `details_for_busy_response_body` is correct — `busy` modifies the atomic terminal compound `response_body` — whereas `details_for_body_of_busy_response` is a violation because it decomposes the established compound `response body` into separate elements.

When a possessive element must also be expressed — identifying the possessor — a leading noun prefix is not sufficient: process_number_of_bytes_of_resident_set_size is ambiguous because 'process' as a leading noun does not make its relationship to the rest of the name explicit. The correct form is number_of_bytes_of_resident_set_size_of_process, where three instances of 'of' each bind one element unambiguously to the next — 'the number of bytes of the resident set size of the process' — and not one connector can be removed without reintroducing ambiguity.

All configuration examples must use explicit, fully expanded names. This applies to environment variable names, the values shown in example configuration files, and the descriptions of configuration parameters in documentation — all subject to the same no-abbreviation and connector rules as all other text.

I want all references to be totally unambiguous. For example, if 'see 95th percentile advisory below' references a heading called '95th percentile calculation algorithm advisory', it should instead say 'see 95th percentile calculation algorithm advisory below'.

For .md files, I want all references to headings to be hyperlinked.

In programming languages without case conventions (such as SQL), use snake_case exclusively.

All example code must be readable by a layperson with minimal programming knowledge.

When naming a variable, field, or property that represents a scalar numeric quantity — that is, a single number representing a count of discrete items or a measurement in units — prefer `number_of_<plural noun>` (e.g. `number_of_observations`, `number_of_consecutive_failures`, `number_of_active_operations`, `elapsed_number_of_seconds_since_last_failure`, `remaining_number_of_seconds_until_recovery`) over the `<noun>_count` pattern (e.g. `observation_count`, `failure_count`) or bare unit nouns (e.g. `elapsed_seconds`, `remaining_bytes`). The `number_of` phrasing makes the relational structure explicit — `number` is immediately followed by the connector `of`, which closes the scope of any leading modifier and binds the measurement to the counted noun — whereas `_count` as a trailing suffix or a bare unit noun leaves the semantic relationship implicit. This preference does not apply to collection types such as dictionaries or lists that contain or map multiple tallies. This preference applies to all new code, renames, and refactoring; existing `_count` names and bare unit nouns encountered during a rename or audit shall be migrated to the `number_of` form. The distinction between `number_of_<unit>` and the `_in_<unit>` suffix annotation: When the variable's semantic content IS the quantity of units — that is, removing the unit noun would leave only modifiers with no standalone concept (e.g. `elapsed_seconds` → `elapsed` alone is incomplete) — the value is a count of units and requires `number_of_<unit>`. When the variable names a concept that exists independently of its unit — that is, removing the unit suffix leaves a meaningful concept name (e.g. `timeout_for_requests_in_seconds` → `timeout_for_requests` is complete) — the `_in_<unit>` suffix is a unit annotation and `number_of` is not required.

When a variable, field, or property includes a unit qualifier (such as `in_seconds`, `in_bytes`, `in_milliseconds`, `per_second`), place the unit qualifier at the end of the identifier. The unit qualifier is a trailing annotation that describes the measurement unit of the value; it must follow all semantic content (the thing being measured, its relationships, and its qualifiers). For example, prefer `timeout_for_graceful_shutdown_in_seconds` over `graceful_shutdown_timeout_in_seconds`, and `inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds` over any form that places `in_seconds` before a relational phrase. This ensures the unit is always in the same predictable position and does not interrupt the semantic chain of connectors.

When a participial modifier (such as 'allowed', 'configured', 'accumulated', 'declared') qualifies an entire noun phrase rather than a single element within it, prefer the postpositive position — placing the participle after the complete noun phrase — over the attributive position. For example, prefer `maximum_number_of_bytes_allowed` over `maximum_allowed_number_of_bytes`, because the postpositive position makes it unambiguous that 'allowed' modifies the entire 'maximum number of bytes' rather than attaching to 'number' alone. In prose, this corresponds to preferring 'the maximum number of bytes allowed' over 'the maximum allowed number of bytes'. The postpositive position also avoids breaking the `number_of_<unit>` chain with an intervening modifier.

When a variable, field, or property represents a boundary value that determines when a state transition or limit is reached, prefer the `threshold` concept (e.g. `failure_threshold_of_circuit_breaker`) over expanding it into a `number_of_` form (e.g. `number_of_consecutive_failures_to_open_circuit_breaker`). The word `threshold` is a well-understood technical term that concisely communicates "boundary count that triggers a transition", making the `number_of_` expansion unnecessarily verbose without adding clarity.

REFACTORING REQUIREMENTS

After every rename of a class, function, variable, exception, fixture, or configuration field — or every change to a value that may be referenced elsewhere, such as a version number, a configuration default, or an enumerated count — perform the following verification procedure before considering that change complete. Do not batch multiple changes and then verify them together — each change must be individually verified before moving on to the next.

For each change, execute a repository-wide search for every occurrence of the old name or value across all applicable case variants. For identifier renames, search all five case variants:

1. snake_case (e.g. language_model_service)
2. PascalCase (e.g. LanguageModelService)
3. UPPER_SNAKE_CASE (e.g. LANGUAGE_MODEL_SERVICE)
4. kebab-case (e.g. language-model-service, which appears in markdown anchor fragments and URL path segments)
5. prose references with spaces (e.g. "language model service")

The search must cover all file types without exception: .py, .yaml, .yml, .env, .env.example, .md, .toml, .cfg, .ini, and .json files. Within those files, the search must cover string literals, docstrings, comments, log event keyword arguments, test assertions, configuration examples, section headings, and prose descriptions.

For value changes (version numbers, configuration defaults, counts), search for the literal old value across all file types. A change is not complete until all searches return zero results for the old name or value. If any search returns a match, evaluate whether it refers to the thing being changed and update it if so before proceeding. If the change affects any module that contributes to the OpenAPI schema, regenerate openapi.yaml before considering the change complete.

For version numbers specifically, search across all formatting variants — dotted (`5.3.0`), underscored (`5_3_0`), and hyphenated (`5-3-0`) — because version numbers appear in different formats depending on context: dotted in prose and document metadata, underscored in filenames, and hyphenated in kebab-case anchors or URL segments.

When an interactive rebase modifies version numbers across multiple commits, searches for superseded versions must be cumulative at each stop. Each stop must verify not only the version it directly supersedes, but all previously superseded versions as well.

SPECIFICATION COUNT AND CHANGELOG INTEGRITY

When correcting a count in the specification (such as the number of logging events, the number of requirements, or any other enumerated total):

1. Never infer which version introduced an item based on semantic reasoning about its description or its relationship to other items. Always verify against the git history (e.g. `git log -S "<item_name>" -- "*.py"` to find when it was implemented, and `git log -S "<item_name>" -- "*.md"` to find when it was added to the specification).
2. After determining the correct count, perform a spec-wide search for every instance of the old count that appears in the context of the thing being counted (e.g. search for `\b44\b` when correcting a logging event count from 44 to 45). Verify each match to determine whether it refers to the count being corrected or to something else (such as a requirement number), and update all stale instances.

Every commit that modifies the specification must include an explicit evaluation of whether the changelog should be updated. If the change warrants a changelog entry — for example, a new requirement, a changed configuration value, a corrected normative statement, or a restructured section — the changelog entry must be included in the same commit that makes the specification change.

SPECIFICATION NORMATIVE KEYWORD SCOPE

When a specification section uses a normative keyword (such as 'shall', 'must', or 'should') to govern a collection of items that serve different purposes — for example, a directory tree containing both application source files and operational deployment templates — the normative keyword must be scoped to each category individually rather than applied as a blanket over the entire collection.

SPECIFICATION REQUIREMENTS

The specification is a purely prescriptive document that defines the target state of the system. It must never comment on what is or is not currently implemented. Every requirement, stage, and configuration example shall be written as a normative statement of what the system shall do, not annotated with implementation status.

Every implementation change must be preceded by a corresponding specification change. If a feature, behaviour, or configuration parameter is not yet documented in the specification, the specification must be updated and committed first, and only then may the implementation be written. The specification commit must always appear before the implementation commit in the git history.

When bumping the specification document version, the specification file shall be renamed to reflect the new version number, following the established pattern `text-to-image-spec-v{major}_{minor}_{patch}.md`. The rename shall be included in the same commit that updates the document version and changelog.

When bumping the specification document version, every reference to the previous specification version that appears in code comments, docstrings, inline annotations, configuration file comments, and CI workflow comments shall be updated to cite the new version number in the same commit that bumps the version. References to the specification version inside the specification file's own changelog table are historical records and shall not be updated.

SPECIFICATION AUTHORITY AND EXTERNAL ASSESSMENTS

The specification is the authoritative source of truth for what constitutes correct system behaviour, but it is not infallible. When an external document — including audit reports, review feedback, or third-party assessments — characterises a spec-compliant behaviour as a deficiency, defect, or design issue, do not silently accept the finding as actionable and do not silently reject it either. Instead, verify the finding against the specification and present both perspectives to the user:

1. What the specification prescribes and why (quoting the relevant section).
2. What the external assessment recommends and why.
3. Whether the external assessment has identified a genuine limitation in the specification's design — a case where the spec may not be optimal even though the implementation conforms to it.

After presenting both perspectives, make a clear engineering recommendation. If the external assessment identifies a genuine design improvement — one where industry best practice, operational reality, or engineering rigour favours the external recommendation over the spec's current prescription — recommend updating the specification rather than defaulting to spec compliance. The spec exists to serve the system, not the other way around. Treating the spec as immutable when evidence points to a better design is itself a deficiency.

The user decides whether to treat the finding as (a) invalid because the spec's design trade-off is sound, (b) a specification improvement opportunity that warrants updating the spec first and then the implementation, or (c) something to defer. Never unilaterally commit to implementing a change that contradicts the specification, and never unilaterally dismiss an external finding without surfacing it.

README REQUIREMENTS

README.md must contain, at minimum:

- Clear setup steps
- Run instructions
- Environment prerequisites
- Example commands

COMMIT MESSAGE REQUIREMENTS

Commit messages must describe the changes in terms of the specification and the codebase. They must never reference external documents such as audit reports, review feedback, or third-party assessments. The motivation for a change is the specification requirement it satisfies or the defect it corrects — not the external document that identified it. This prohibition extends to organisational terminology, sequencing labels, and structural vocabulary inherited from external documents — such as phase numbers, finding identifiers, priority tiers, or evaluation categories. When a series of commits implements a multi-step change, describe each step in terms of what it does to the codebase (e.g. "Split application/models.py into application/api/schemas/ subpackage"), not in terms of where it falls in an externally defined plan.

When a commit modifies a specific artefact whose identity is not self-evident from the change description, the commit message must name that artefact explicitly. For example, a message that says "Add directive to recommend specification improvements" is ambiguous — it could refer to a change in the specification, in CLAUDE.md, in a CI workflow, or in application code. The correct form names the file or artefact: "Add directive to CLAUDE.md to recommend specification improvements". This applies to all artefacts — the specification, CLAUDE.md, the Makefile, the Dockerfile, Kubernetes manifests, CI workflows, and any other file where the subject line alone does not make the target unambiguous.

Following an interactive rebase that edits files, each edited commit's message shall be reassessed for accuracy against the updated diff. If any commit message no longer accurately describes the commit's content, a follow-up interactive rebase shall be used to correct it.

When an interactive rebase stops due to a merge conflict, never use `git commit --amend` to finalise the resolution. During a conflict, HEAD still points to the last successfully applied commit — the conflicted commit has not yet been created. Running `--amend` in this state replaces that previous commit with the merged result, losing the previous commit as a distinct entry in the history. Instead, stage the resolved files with `git add` and run `git rebase --continue`, which creates the conflicted commit as a new entry. This prohibition does not apply to `edit` marker stops without a conflict, where HEAD is the commit being edited and `git commit --amend` is correct.

PLANNING REQUIREMENTS

Every plan must end with a section titled "Unresolved questions", if any exist. An unresolved question is any ambiguity, missing requirement, undetermined design choice, or dependency on information not yet available that could affect the correctness or completeness of the plan's implementation. If no unresolved questions exist, the section shall state "None." explicitly. This section ensures that the user can identify and resolve open issues before approving the plan for implementation.

MARKDOWN ANCHOR LINK REQUIREMENTS

Every internal anchor reference in all markdown files (`.md`) must correspond to a markdown heading with a valid anchor. When adding cross-references anywhere in the codebase's markdown documentation, verify the target heading exists before committing. A markdown link checker (such as markdown-link-check) may be used to validate all references before submission. Dead anchor links in any markdown file violate clarity requirements and must be caught during review.
