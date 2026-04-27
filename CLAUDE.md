You must adhere to the following non-negotiable standards:

Prioritise clarity, rigour, and scalability over brevity.

When a directive in this document conflicts with the Claude Code system prompt — including but not limited to directives about brevity, conciseness, or output length — this document takes precedence.

When creating or modifying any artefact — code, a directive, documentation, configuration, or any other file content — do not let the specific scenario that motivated the change constrain the result to that scenario alone. The triggering scenario is one instance of a broader concern; a result fitted to one instance rather than the concern itself will fail when the next instance arises.

LANGUAGE AND STYLE REQUIREMENTS

Use British English spelling throughout (e.g. "optimisation", "initialisation", "colour"), except where American spelling appears in official protocol names, technical standards, header fields, or library-defined identifiers.

Never place a comma after 'e.g.', 'i.e.', or 'etc.' — write 'e.g. "optimisation"', not 'e.g., "optimisation"'.

When a colon introduces a complete independent clause — one that could stand as a sentence in its own right — capitalise the first word of that clause. When the colon introduces a phrase, subordinate clause, or list that is grammatically dependent on what precedes it, do not capitalise. Avoid the construction '[noun phrase] is: [full clause]'; instead restructure to make the clause the direct complement of its governing verb, or lead directly with the normative subject (e.g. not 'The normative behaviour for X is: the service shall return…' but 'For X, the service shall return…').

When writing a compound that can function as both a noun and an attributive modifier, do not hyphenate the noun form. Hyphens in compound terms apply only in the attributive modifier position — that is, when the compound directly precedes a head noun. For example, write 'a short circuit' (standalone noun) and 'short-circuit evaluation' (attributive modifier preceding 'evaluation'). Before hyphenating any compound, verify that it directly precedes and modifies a head noun; if it does not, write it without a hyphen.

When a compound modifier that precedes a head noun includes a multi-word atomic term — whether an established technical compound, an automatically recognised atomic compound, or a multi-word command name — a hyphen must not be placed between the non-term word and only the first word of the atomic term, because this creates a false grouping that binds the non-term word to the first element alone rather than to the atomic term as a whole. For example, 'compound-`git commit` hook' falsely groups 'compound' with 'git' rather than with '`git commit`'. Removing the false hyphen yields 'compound `git commit` hook', which resolves the grouping issue but may still require restructuring under the connector rule (in this case, 'hook blocking `git commit` in compound commands').

CODE AND NAMING REQUIREMENTS

All code must be self-documenting.

Every definition within a named container — a module, a class, a directory, or any other named grouping — must fall within the activity or concept that the container's name describes. A definition whose purpose is intelligible independently of the host container's primary activity represents a distinct activity and belongs in a separate container named after that activity — private visibility merely defers this misalignment until the definition is needed elsewhere.

No abbreviations or acronyms are permitted in code identifiers (variable names, function names, class names, import aliases, filenames) or in prose (inline comments, docstrings, commit messages, documentation, section headings, diagram labels, table cells, configuration examples, and user-facing output strings) unless they appear in the "Approved abbreviations" list at the end of this document. Each entry in that list records two independent decisions: whether the abbreviation remains abbreviated in code identifiers, and whether it remains abbreviated in prose. When you encounter an abbreviation or acronym that does not yet have an entry in the list, prompt the user to decide which list it belongs in, then record the decisions. Abbreviations in the list marked as "expanded" shall always use the expanded form in the corresponding context. Conversely, abbreviations in the list marked as "abbreviated" shall always use the abbreviated form in the corresponding context. The following categories of symbols must never be modified regardless of whether they contain abbreviations:

- Python built-ins (max, min, len, id, and others)
- Magic methods (__init__, __str__, and others)
- Dunder attributes
- Decorators required by frameworks
- Protocol method names
- Reserved keywords
- Third-party library symbols
- Standard library symbols
- Standard Python single-letter loop variables (`i`, `j`, `k` as loop indices; `f`, `b`, `d`, `m`, `s`, `p` as element-of-collection iterators; `e` as an exception variable in `except ... as e` clauses) — these are idiomatic Python conventions whose meaning is established by their syntactic position rather than by their name

You may introduce additional libraries if justified architecturally.

Variable and function names must be fully descriptive, even if excessively verbose. These rules apply to all text without exception: variable names, function names, class names, import aliases, inline comments, commit messages, prose descriptions, section headings, diagram labels, table cells, configuration examples, and user-facing output strings. Abbreviations and acronyms must be used in accordance with the approved abbreviations list at the end of this document. Sometimes, excessive verbosity may be necessary since the lack of abbreviations or acronyms can introduce vagueness, such as 'client software development kit generation' or 'out-of-memory process termination restarts' or 'Service Level Objective Name' or 'Service Level Indicator Definition'. Whenever there is even the slightest vagueness, I want to prioritise clarity above all else by inserting relational words to group the noun phrase explicitly. So 'client software development kit generation' should be restructured as 'generation of client software development kits'. Similarly: 'out-of-memory process termination restarts' should be restructured as 'restarts triggered by out-of-memory process terminations'; 'Service Level Objective Name' should be restructured as 'Name of the Service Level Objective' (notice how the lack of abbreviations gives rise to this). Unconventional phrasing is not only permitted but required when it eliminates ambiguity — do not avoid a construction merely because it looks unusual. In cases where eliminating ambiguity would violate a naming convention such as the Prometheus {scope}{measurement}{unit} pattern, violate the convention. For example, current_resident_set_size_bytes should be restructured as current_number_of_bytes_of_resident_set_size: The double 'of' is deliberate — number_of_bytes names precisely what is being counted, and of_resident_set_size binds that count to the intact noun phrase, leaving no room for any alternative parse.

This does not mean that every element requires its own relational connector. A leading modifier — whether an adjective or a classifying noun — may appear without a connector of its own, but only when the word it immediately precedes is itself immediately followed by a relational connector. A classifying noun is any word that functions as a noun in other contexts and is used here attributively to name the type or category of the head noun — for example, 'request' in 'request pipeline', 'image' in 'image format', 'service' in 'service error'. An adjective describes a quality or property of the head noun and cannot stand alone as a noun without a change of meaning — for example, 'minimum', 'viable', 'rapid'. When a word could plausibly be read as either (for example, 'structured', 'automated', 'upstream'), treat it as a classifying noun and apply the connector requirement. Hyphenated compound modifiers — multi-word phrases joined by hyphens to form a single attributive unit (for example, 'change-to-directory' from 'change to directory', 'load-testing' from 'load testing') — are adjectives, not classifying nouns. The hyphens explicitly signal that the phrase functions as a single adjectival modifier; the unhyphenated components cannot be used as a standalone noun in that form. The ambiguity test does not apply to hyphenated compounds because the hyphenation itself resolves the ambiguity. Determiners — the articles 'a', 'an', 'the'; the demonstratives 'this', 'that', 'these', 'those'; and the quantifiers 'every', 'each', 'all', 'any', 'no', 'some', 'many', 'few', 'several', 'most', 'both', 'either', 'neither', 'enough', 'another', 'other' — are not governed by this rule. They are neither adjectives (which describe a quality or property) nor classifying nouns (which name a type or category). Because a determiner always scopes over the entire noun phrase it introduces, no structural ambiguity of modifier attachment can arise, and no connector is required after a determiner regardless of what follows it. Relational connectors are prepositions that make a semantic relationship explicit: of, for, by, from, via, under, through, at, in, on, to, with, during, without, per, after, before, between, against, across, into, since, and until all qualify; a comma, a parenthetical, or simple juxtaposition does not. A connector is structurally valid when it is present, but it is semantically valid only when it accurately represents the actual relationship between the two elements it joins. Choosing a generic connector (such as 'for' or 'of') when a more precise one is available is a violation. When selecting a relational connector, test every candidate connector against the relationship before committing. Do not stop at the first plausible option. Each connector carries a distinct meaning and must be selected accordingly:

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

When a preposition without a participial modifier does not unambiguously convey the nature of the relationship, a participial modifier must be inserted immediately before the preposition to make the semantic relationship explicit. For example, 'maximum_tokens_by_large_language_model' is ambiguous because 'by' alone does not specify what action the large language model performs on the tokens; 'maximum_tokens_generated_by_large_language_model' is unambiguous because 'generated' names the action. The participial modifier is required whenever omitting it would leave the reader unable to determine the specific relationship from the preposition alone. That connector after the word being modified does two things simultaneously: it makes the relationship between the modified word and what follows explicit, and it unambiguously closes the leading modifier's scope at the modified word. In current_number_of_bytes_of_resident_set_size, 'current' is acceptable as a leading prefix without a connector precisely because 'number' is immediately followed by 'of': The 'of' closes the scope of 'current' at 'number' — confirming that 'current' modifies only 'number' and nothing beyond — while also explicitly connecting 'number' to 'bytes'. Without the 'of' after 'number', the scope of 'current' would be indeterminate: it would be unclear whether 'current' modifies 'number' alone, number_of_bytes as a compound, or number_of_bytes_of_resident_set_size as a whole. The same principle applies in prose: 'categorisation guide for new requirements' is acceptable because 'guide' is immediately followed by 'for', which closes the scope of 'categorisation' at 'guide'; 'verification requirements of the infrastructure' is acceptable because 'requirements' is immediately followed by 'of'. The counterexample makes the rule concrete: 'infrastructure verification requirements' is not acceptable because 'verification' is not terminal — the nominal 'requirements' follows it — and has no connector after it, leaving the scope of 'infrastructure' indeterminate — it cannot be established whether 'infrastructure' modifies 'verification' alone or 'verification requirements' as a compound. Note that 'verification requirements' in isolation would be acceptable under the terminal-element rule stated below; it is specifically 'infrastructure' before a non-terminal 'verification' that creates the violation. Remove the connector from either of the acceptable examples while leaving a further nominal element after the head noun, and the same ambiguity arises immediately; but if removal also makes the head noun terminal, no ambiguity arises.

There is one further case in which a leading modifier may appear without a connector: when the word it immediately precedes is the terminal element of the phrase or identifier — that is, when no further nominal elements (nouns, gerunds, or nominal phrases) follow it. In this position the scope of the leading modifier is unambiguous by construction, since there is only one element it can attach to. 'service logs' and 'load-testing tool' are therefore acceptable: 'logs' and 'tool' are terminal elements with nothing nominal following them.

When evaluating whether a classifying noun requires restructuring, you must evaluate the complete identifier or phrase — never a fragment in isolation. Whether the connector-follows exception or the terminal-element rule applies to a given classifying noun depends entirely on what follows the word it modifies in the complete phrase. A classifying noun that appears non-compliant in a two-word fragment may be fully compliant in the complete phrase. Before concluding that a classifying noun requires restructuring, verify by inspecting the complete identifier that neither the connector-follows exception nor the terminal-element rule already resolves it. The following negative example illustrates the mistake:

- WRONG analysis: Evaluating the fragment 'output tokens' in isolation → 'output' is a classifying noun before 'tokens' → no connector after 'tokens' visible → conclude restructuring to 'tokens of output' is required.
- CORRECT analysis: Evaluating the complete identifier `maximum_number_of_output_tokens_for_API` → 'output' is a classifying noun before 'tokens' → 'tokens' is immediately followed by 'for' (a relational connector) → the connector-follows exception applies → 'output tokens' requires no restructuring.

The error in the wrong analysis is fragmentary evaluation: the connector 'for' that resolves the classifying noun 'output' is invisible when only 'output tokens' is examined. This class of error can only be prevented by evaluating every classifying noun against the complete phrase.

When a sequence of pure adjectives — not classifying nouns — collectively precede a single head noun, they form a compound adjectival modifier and are evaluated as a unit; no connectors are required between the individual adjectives within the compound, only at the point where the head noun meets what follows it. For example, 'minimum viable implementation' contains two adjectives ('minimum', 'viable') and one head noun ('implementation'): The two adjectives form a compound modifier and require no connector between them. Restructuring 'minimum viable implementation scope' as 'scope of the minimum viable implementation' is therefore sufficient — 'of' connects 'scope' to the compound-modified noun, and within 'minimum viable implementation' no further connectors are needed. When restructuring is required to satisfy the connector rule, use relational prepositions to reorder the phrase; do not convert an adjective to an adverb — for example, if 'automated scaling policy' must be restructured, write 'policy for automated scaling', not 'policy for scaling automatically'. A classifying noun appearing anywhere in the chain reintroduces the full connector requirement, because noun-to-noun and noun-to-adjective relationships are not structurally self-evident in the way that adjective-to-adjective relationships are.

When `maximum` or `minimum` precedes a classifying noun followed by a counted noun in any text (identifiers or prose), `number of` must be inserted after the boundary qualifier to satisfy the connector rule. For example, 'maximum output tokens' violates the connector rule because 'output' (classifying noun) is not immediately followed by a connector; 'maximum number of output tokens' is compliant because 'number' is immediately followed by 'of'. This is not an optional stylistic preference — it is required by the connector rule whenever a classifying noun appears in the chain after a boundary qualifier.

Established technical compound terms whose meaning is not compositionally derivable from their components are treated as atomic noun phrases: no connectors are required between their internal components. Examples include large language model, natural language processing, machine learning, neural network, deep learning, and response body. The definitive list of established compounds is maintained in the "Established technical compound terms" section at the end of this document, including terms whose meaning is compositionally derivable but that nonetheless function as fixed lexical units in their domain. When you encounter a multi-word term that you suspect may be an established compound but that does not appear in the list, prompt the user to decide whether it should be added, then record the decision. The exemption covers only the internal structure of the established term. At the boundary where such a compound acts as a leading modifier before a further noun, the connector requirement applies in full: large language model inference still requires restructuring to inference of large language models, and machine learning pipeline to pipeline for machine learning. When restructuring a phrase to satisfy the connector rules, an established technical compound must never be broken apart. The compound must be kept intact and treated as a single terminal or non-terminal unit during restructuring. For example, `details_for_busy_response_body` is correct — `busy` modifies the atomic terminal compound `response_body` — whereas `details_for_body_of_busy_response` is a violation because it decomposes the established compound `response body` into separate elements.

When a symbol that is exempt from modification, or that is marked as "abbreviated" in the list of approved abbreviations, directly precedes a noun (singular or plural) — or a term from the list of established technical compound terms — that names a domain-specific category, and the symbol specifies the noun — narrowing it to a particular type, format, protocol, channel, platform, or variant within that category — the combination is automatically treated as an atomic compound. Examples: "PreToolUse hook" (PreToolUse specifies a type of hook), "HTTP request" (HTTP specifies a protocol of request), "JSON body" (JSON specifies a format of body), "systemMessage output" (systemMessage specifies a channel of output), "Docker container" (Docker specifies a platform of container). The symbol must be functioning as a technical identifier, not as a common English word that happens to coincide with a symbol name. These automatically recognised atomic compounds do not require individual entries in the list because the set of such pairings is open-ended. They inherit all obligations of listed atomic compounds: The boundary rule applies in full when such a compound precedes a further noun, and the compound must never be broken apart during restructuring.

When a possessive element must also be expressed — identifying the possessor — a leading noun prefix is not sufficient: process_number_of_bytes_of_resident_set_size is ambiguous because 'process' as a leading noun does not make its relationship to the rest of the name explicit. The correct form is number_of_bytes_of_resident_set_size_of_process, where three instances of 'of' each bind one element unambiguously to the next — 'the number of bytes of the resident set size of the process' — and not one connector can be removed without reintroducing ambiguity.

All configuration examples must use explicit, fully expanded names. This applies to environment variable names, the values shown in example configuration files, and the descriptions of configuration parameters in documentation — all subject to the same no-abbreviation rules as all other text and to the same connector rules as all other text, with one exception: environment variable names that use an organisational namespace prefix — a leading component that scopes the variable to a specific application, pipeline, or service (e.g. `AUDIT_`, `REMEDIATION_`, `KUBERNETES_`) — are exempt from the connector rule at the boundary between the namespace prefix and the rest of the identifier. The namespace prefix is an organisational scoping mechanism, not a semantic modifier, and requiring a connector at that boundary would eliminate the grouping and discoverability benefits (shell tab-completion, `env | grep PREFIX_`) that namespace prefixes provide. The exemption applies only to the prefix boundary; all naming rules apply in full to the portion of the identifier that follows the prefix.

I want all references to be totally unambiguous. For example, if 'see 95th percentile advisory below' references a heading called '95th percentile calculation algorithm advisory', it should instead say 'see 95th percentile calculation algorithm advisory below'.

In programming languages without case conventions (such as SQL), use snake_case exclusively.

All example code must be readable by a layperson with minimal programming knowledge.

When naming a variable, field, or property that represents a scalar numeric quantity — that is, a single number representing a count of discrete items or a measurement in units — prefer `number_of_<plural noun>` (e.g. `number_of_observations`, `number_of_consecutive_failures`, `number_of_active_operations`, `elapsed_number_of_seconds_since_last_failure`, `remaining_number_of_seconds_until_recovery`) over the `<noun>_count` pattern (e.g. `observation_count`, `failure_count`) or unit nouns without the `number_of_` prefix (e.g. `elapsed_seconds`, `remaining_bytes`). The `number_of` phrasing makes the relational structure explicit — `number` is immediately followed by the connector `of`, which closes the scope of any leading modifier and binds the measurement to the counted noun — whereas `_count` as a trailing suffix or a bare unit noun leaves the semantic relationship implicit. This preference does not apply to collection types such as dictionaries or lists that contain or map multiple tallies. This preference applies to all new code, renames, and refactoring; existing `_count` names and unit nouns without the `number_of_` prefix encountered during a rename or audit shall be migrated to the `number_of` form. The distinction between `number_of_<unit>` and the `_in_<unit>` suffix annotation: When the variable's semantic content IS the quantity of units — that is, removing the unit noun would leave only modifiers with no standalone concept (e.g. `elapsed_seconds` → `elapsed` alone is incomplete) — the value is a count of units and requires `number_of_<unit>`. When the variable names a concept that exists independently of its unit — that is, removing the unit suffix leaves a meaningful concept name (e.g. `timeout_for_requests_in_seconds` → `timeout_for_requests` is complete) — the `_in_<unit>` suffix is a unit annotation and `number_of` is not required.

When a variable, field, or property includes a unit qualifier (such as `in_seconds`, `in_bytes`, `in_milliseconds`, `per_second`), place the unit qualifier at the end of the identifier. The unit qualifier is a trailing annotation that describes the measurement unit of the value; it must follow all semantic content (the thing being measured, its relationships, and its qualifiers). For example, prefer `timeout_for_graceful_shutdown_in_seconds` over `graceful_shutdown_timeout_in_seconds`, and `inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds` over any form that places `in_seconds` before a relational phrase. This ensures the unit is always in the same predictable position and does not interrupt the semantic chain of connectors.

When a participial modifier (such as 'allowed', 'configured', 'accumulated', 'declared') qualifies an entire noun phrase rather than a single element within it, prefer the postpositive position — placing the participle after the complete noun phrase — over the attributive position. For example, prefer `maximum_number_of_bytes_allowed` over `maximum_allowed_number_of_bytes`, because the postpositive position makes it unambiguous that 'allowed' modifies the entire 'maximum number of bytes' rather than attaching to 'number' alone. In prose, this corresponds to preferring 'the maximum number of bytes allowed' over 'the maximum allowed number of bytes'. The postpositive position also avoids breaking the `number_of_<unit>` chain with an intervening modifier.

When a variable, field, or property represents a boundary value or constrained quantity — even one that could be expressed using a well-understood scalar-boundary term such as `threshold`, `limit`, `capacity`, `quota`, `budget`, `ceiling`, or `floor` — prefer the `number_of_` form. For example, prefer `number_of_consecutive_failures_to_open_circuit_breaker` over `failure_threshold_of_circuit_breaker`, and `maximum_number_of_connections_allowed` over `connection_limit`.

When two or more variables of the same kind are distinguished only by ordinal position (e.g. two input strings, two lengths), a trailing `_1`, `_2` suffix is permitted. The suffix implicitly binds the variable to the correspondingly numbered peer (e.g. `length_1` refers to the length of `string_1`); this relationship need not be restated in the name.

When correcting a violation in a phrase, follow this procedure:

1. Fix the violation that was identified.
2. Re-evaluate the updated phrase against every rule in this document — not only the rule that triggered the original correction. Each rule applies independently and simultaneously; satisfying one rule does not discharge the obligation to satisfy every other rule that governs the same text.
3. If any new violation is found, fix it and return to step 2.
4. Stop only when the phrase satisfies every applicable rule simultaneously.

A structural fix (such as reordering words to satisfy the connector rule) that leaves an abbreviation, an unclear modifier, or an imprecise word choice is incomplete.

Worked example — correcting the prose phrase 'bare ``cd`` invocations' in a docstring:

- Iteration 1 (connector rule): 'bare ``cd`` invocations' is restructured to 'invocations of bare ``cd``'.
- Iteration 2 (no-abbreviation rule): '``cd``' is an abbreviation of 'change directory' and must be expanded to '``cd`` (change-to-directory)' on first use. Note: This expansion applies only in prose contexts such as docstrings and comments. In code, ``cd`` is the literal shell command name and cannot be renamed.
- Iteration 3 (fully descriptive naming requirement): 'bare' is jargon whose meaning depends on context. It must be replaced with an explicit description: 'not wrapped in a subshell'.
- Iteration 4 (fully descriptive naming requirement): 'invocations' may not accurately describe what is being detected — 'commands' is more precise for a string scanner.
- Final result: '``cd`` (change-to-directory) commands not wrapped in a subshell'.

REQUIREMENTS FOR MODULE NAMING

Individual modules (Python files containing code) shall be named after the specific activity or concept they encapsulate. Generic bucket names such as "utilities", "helpers", "common", or "misc" are not permitted for modules, because they describe nothing about the module's content and invite unbounded scope creep. Directories that group individually well-named subordinate modules may use role-based names such as "helpers" when the directory is an organisational container rather than a code unit — for example, `hooks/helpers/` is acceptable because each module within it (such as `deny_then_allow.py`) is individually named after its specific activity, and "helpers" describes the role of those modules relative to the parent `hooks/` directory.

When a module houses functions that perform an action — constructing, validating, logging, extracting, resolving — the module name shall describe the activity rather than the artefact. For example, `content_type_validation` (not `content_type`), `request_logging` (not `request_log`), `asgi_error_response_construction` (not `asgi_error_response`). Naming a module after the artefact is ambiguous — it could refer to an object, a class, a definition, or a builder — whereas naming it after the activity makes the module's purpose self-evident.

REFACTORING REQUIREMENTS

After every rename of a class, function, variable, exception, fixture, or configuration field — or every change to a value that may be referenced elsewhere, such as a version number, a configuration default, or an enumerated count — perform the following verification procedure before considering that change complete. Do not batch multiple changes and then verify them together — each change must be individually verified before moving on to the next.

For each change, execute a repository-wide search for every occurrence of the old name or value across all applicable case variants. For identifier renames, search all five case variants:

1. snake_case (e.g. language_model_service)
2. PascalCase (e.g. LanguageModelService)
3. UPPER_SNAKE_CASE (e.g. LANGUAGE_MODEL_SERVICE)
4. kebab-case (e.g. language-model-service, which appears in markdown anchor fragments and URL path segments)
5. prose references with spaces (e.g. "language model service")

The search must cover all file types without exception: .py, .yaml, .yml, .env, .env.example, .md, .toml, .cfg, .ini, and .json files. Within those files, the search must cover string literals, docstrings, comments, keyword arguments of log events, test assertions, configuration examples, section headings, and prose descriptions.

When the identifier being renamed participates in a convention-over-configuration derivation — where a framework computes a runtime identifier from the code identifier through transformations such as case conversion, pluralisation, prefix stripping, or namespace prepending — the five case variants listed above are necessary but not sufficient. The derived form of the runtime identifier may not match any of the five case variants listed above. For each framework that derives a runtime identifier from the code identifier being renamed, determine the old derived identifier by applying the derivation rules of the framework, and search for it across all file types — including migration files, schema definitions, seed data, API specifications, message schemas, and configuration files. Verify that each match is either updated to reflect the new derived identifier or protected by an explicit override that pins the runtime identifier independently of the code identifier (see REQUIREMENTS FOR CONSISTENCY BETWEEN CODE IDENTIFIERS AND RUNTIME IDENTIFIERS DERIVED BY FRAMEWORKS).

For value changes (version numbers, configuration defaults, counts), search for the literal old value across all file types. A change is not complete until all searches return zero results for the old name or value. If any search returns a match, evaluate whether it refers to the thing being changed and update it if so before proceeding. If the change affects any module whose output contributes to auto-generated artefacts (e.g. a module from whose definitions an API schema (such as openapi.yaml) is auto-generated), regenerate those artefacts before considering the change complete.

For version numbers specifically, search across all formatting variants — dotted (`5.3.0`), underscored (`5_3_0`), and hyphenated (`5-3-0`) — because version numbers appear in different formats depending on context: dotted in prose and document metadata, underscored in filenames, and hyphenated in kebab-case anchors or URL segments.

When an interactive rebase modifies version numbers across multiple commits, searches for superseded versions must be cumulative at each stop. Each stop must verify not only the version it directly supersedes, but all previously superseded versions as well.

This verification procedure also applies when introducing a new value — such as a version constraint, a compatibility requirement, a tool target version, or a configuration default — that defines or constrains something already stated elsewhere in the repository. Search for existing references to the same concept across all file types to ensure they are consistent with the newly introduced value. For example, when adding `target-version = "py312"` to a tool configuration file, search for plausible existing version references (such as "3.11", "3.10", and "Python 3") to identify any that now contradict the newly authoritative value.

When a commit adds, removes, or renames a file or directory, every manually maintained inventory of files in the repository — such as a directory tree of the project in README.md, a component listing in documentation, or a table of modules in the specification — must be updated in the same commit. A file addition, removal, or rename is not complete until all such inventories reflect the current state of the filesystem.

After any modification to a file that removes, replaces, or restructures existing code, verify that no artefacts in the modified file have become unused as a result of the change. This includes import statements whose imported names no longer appear in the file body, private helper functions that are no longer called, variables that are no longer referenced, and comments or docstrings that described code that no longer exists. Each such orphaned artefact must be removed in the same commit as the modification.

REQUIREMENTS FOR CONSISTENCY BETWEEN CODE IDENTIFIERS AND RUNTIME IDENTIFIERS DERIVED BY FRAMEWORKS

When a framework derives a runtime identifier from a code identifier through convention over configuration — such as a persistence framework deriving the name of a database table from the name of a struct or class, a serialisation library deriving the wire-format name of a field from the name of a struct field or property, a routing framework deriving a URL path from the name of a handler or controller, or a message broker deriving the name of a topic or queue from the name of a type — the derivation creates an implicit coupling between the code identifier and an external system (a database schema, an API contract, a message bus, or a URL structure). A rename of the code identifier silently changes the runtime identifier, potentially breaking the external system without any signal at compile time or lint time.

When reviewing, auditing, or modifying code that uses such a framework, verify the following:

1. Every entity whose runtime identifier is derived from a code identifier shall have an explicit override that pins the runtime identifier independently of the code identifier — for example, a `TableName()` method in GORM, a `Meta.db_table` attribute in Django, a `@Table(name=...)` annotation in JPA, a `json:"field_name"` struct tag in Go, a `@JsonProperty` annotation in Jackson, or the equivalent mechanism in the framework being used. The override makes the coupling explicit and protects against silent breakage during renames.

2. When some entities in the same architectural layer already use explicit overrides and others do not, the inconsistency is a latent defect. If the codebase has established a pattern of pinning runtime identifiers — for example, some structs define `TableName()` methods while other structs in the same package do not — every entity in that layer must follow the established pattern.

3. When some code paths for the same entity specify the runtime identifier explicitly (such as a `.Table("user_cloud_credentials")` clause in a query) while other code paths for the same entity rely on implicit derivation (such as `tx.Create(&row)` without an override for the table), the inconsistency must be flagged. Either all code paths shall use explicit identifiers, or the entity shall have an override method that ensures the implicit derivation produces the correct identifier regardless of future renames. Mixed approaches — where reads are protected by runtime identifiers that are specified explicitly but writes rely on convention, or vice versa — are latent defects that will manifest when the code identifier is renamed.

4. When a runtime identifier is defined by an external artefact — such as a migration that creates a table with a specific name, an API specification that defines a field with a specific wire name, or a message schema that declares a topic with a specific name — the code entity that maps to that artefact must produce a runtime identifier that matches the definition in the external artefact. This match must hold either through the convention of the framework (verified by manually applying the derivation rules of the framework to the current code identifier) or through an explicit override. A mismatch between the name derived by the framework and the name defined in the external artefact is a defect regardless of whether it has manifested at runtime.

REQUIREMENTS FOR CONSISTENCY BETWEEN AN IMPLEMENTATION OF A CONTRACT AND THE ARTEFACT THAT DOCUMENTS THE CONTRACT

When code realises a contract that some other party observes and depends on — a downstream client, an upstream provider, a sibling component of this codebase, a generator of typed bindings, an integration partner, a monitoring tool, a replay script, an audit pipeline, or a future maintainer reading the documentation — the contract forms an implicit coupling between the implementation that realises it and the artefact that documents it. Drift between the two silently breaks every party that depends on the contract while leaving the implementation and the documentation each appearing internally consistent.

The contract may govern any of the following:

- A signal that this codebase emits across an external boundary — a HTTP response header, a HTTP status code, a JSON body field, the name of a query parameter or form parameter, a URL path pattern, a field in a gRPC message, the name of a topic or queue used by a message broker, the identifier of a log event and the names of its fields, the name of a Prometheus metric and the keys of its labels, the name of a column or table in a database schema consumed by an external system, the name of an environment variable and the format of its value, the name of a command-line flag, a Kubernetes annotation or label, the name and structure of a file that other systems consume, the name of a field in a webhook payload, or any other identifier or value that crosses the boundary between this codebase and a downstream system or human-facing surface.
- A signal that this codebase consumes across an external boundary — the assumed name, type, default, presence, or emission condition of any field that the codebase reads from an upstream API, a webhook payload, a message broker, an ingested file format, an environment-variable convention, or any other channel where an external party emits a value the codebase reads.
- An internal contract between components of this codebase — for example, the artefact contracts between phases of an orchestrated pipeline (each phase's `Produces:` and `Consumed by:` clauses in its prompt file, the orchestrator's reads and writes that realise those clauses, and the artefact dependency registry that enumerates the same dependencies), the contract between a public package's function signatures and the docstrings or type stubs that document them, the data format produced by one component of this codebase and consumed by another, or any other implementation/artefact pair where one component realises behaviour that another component or a human reader observes by reading the documentation.
- A behavioural or structural guarantee — idempotency, ordering, exactly-once delivery, retry safety, freedom from side effects, monotonic progression, error-recovery semantics, concurrency safety, or any other property the documentation declares that the implementation must honour at runtime even when no specific field or signal is named.

Artefacts that document the contract include but are not limited to: OpenAPI specifications, Protocol Buffers definitions, JSON Schema files, GraphQL schemas, AsyncAPI specifications, Kubernetes Custom Resource Definitions, type stubs (.pyi) and TypeScript declaration files, README sections describing the contract, runbooks specifying expected behaviour, configuration templates, migration files whose comments document expected outcomes, prompt files declaring artefact contracts for orchestrated pipelines, dependency registries that enumerate required and produced artefacts, and docstrings declaring behavioural guarantees that callers depend on.

When a single branch introduces, modifies, or removes either the implementation of a contract or any artefact that documents the contract, the branch must reconcile every implementation/artefact pair affected by the change before it is merged. Deferring documentation of a self-authored implementation change to a later branch — even a follow-up branch opened immediately after merge — is a violation. The branch that creates, alters, or retires a contract is the branch responsible for completing the reconciliation. Splitting the implementation and the documentation across branches separated by a merge boundary publishes a known, self-authored gap to the trunk and entrenches a follow-up commit that may slip indefinitely as new feature work outweighs the deferred chore.

When reviewing, auditing, or modifying code or documentation that bears on a contract, verify the following:

1. For every contract element that the branch introduces, modifies, or removes in code — whether a signal emitted across an external boundary, a signal consumed across an external boundary, an internal artefact produced or consumed by a sibling component, or a behavioural guarantee asserted on an interface — identify every artefact in the branch that documents that element. Verify that each artefact documents the element accurately, including its name, its type, any default or constraint that bounds its value, the format in which it is rendered, the conditions under which it is emitted or consumed (always, only on a specific status code, only on a specific code path, only when a specific condition holds), and any field or attribute whose value varies. An element whose presence is conditional on a code path must have its conditionality documented; an element whose value is rendered from a template must have its rendered form documented with at least one example. When the change removes an element, every artefact that documented it must remove the entry in the same branch — leaving stale documentation that records a removed element is the same drift class as omitting documentation for an added element.

2. For every documentation entry in the branch that records a contract element, identify the implementation that realises it. Verify that the implementation in the branch matches the documented contract. Documenting an element that the code does not realise — whether a signal that no emission site emits, an upstream field that no consumer reads, an internal artefact that no producer writes, or a behavioural guarantee that the implementation does not honour — is as much a contract violation as realising an element that no documentation records.

3. Where the value of a contract element is rendered by a format string, a template, or any other parameterised construction, define the template once as a named constant in the implementation and reference that single source of truth from both the code that realises the element at runtime and any test that pins the documented example. Add a drift test that asserts the documented example is exactly what the format constant produces when rendered with a known input. The drift test must live in the same branch that introduces, modifies, or removes the element, and it prevents the documented value and the runtime value from silently diverging in future. When the contract is versioned — discriminated by a URL prefix, a header value, a media type, or any other selector — the drift test must cover every active version, because a change that satisfies the newest version while breaking an older version is the same drift class as a change that breaks the newest version.

4. Where multiple sites realise the same contract element under the same conditions, document the element once as a reusable component (an OpenAPI `components/responses` or `components/headers` entry, a shared message type in a Protocol Buffers definition, a shared JSON Schema fragment, a shared section of the README, or a shared registry entry referenced by every site) and reference the reusable component from each site that realises the element. This consolidation makes the documentation maintainable and ensures that a future change to the contract updates every site at once. Sites that realise the element under conditions materially different from the reusable component's preconditions must continue to document the conditional path inline, with explicit prose distinguishing the conditional realisation from the unconditional case.

5. When a contract element is realised only on a specific code path within a response, message, or invocation that may also be produced or consumed by other code paths — for example, a response header that the scope-gate middleware emits on its denial branch but that the ownership check inside the handler does not emit on its denial branch — the documentation must distinguish the branches and state which branches realise the element and which do not. Documenting the element as unconditionally present is a contract lie that is materially worse than under-documentation, because client code generated from the document models a field that the runtime omits.

6. When a contract is documented in more than one artefact — for example, an OpenAPI specification, a README contract section, and an onboarding document, all describing the same endpoint — every artefact that documents the contract must be reconciled with the implementation in the same branch, not only the most authoritative one. Selecting one artefact as canonical and leaving the others to be updated later violates the same-branch reconciliation requirement and propagates the drift onto every reader who consults a non-canonical artefact.

The reconciliation requirement applies regardless of which side of the contract the branch authors first. A branch that adds a new realisation site in code must update every artefact documenting the contract in the same branch; a branch that adds a new documentation entry must verify that the implementation realises the element in the same branch; a branch that removes an implementation must remove every documentation entry that recorded it in the same branch. The git history must record the implementation and the documentation as either a single commit or as adjacent commits within the same branch — never as commits in different branches separated by a merge boundary.

SPECIFICATION COUNT INTEGRITY

When correcting a count in the specification (such as the number of logging events, the number of requirements, or any other enumerated total):

1. Never infer which version introduced an item based on semantic reasoning about its description or its relationship to other items. Always verify against the git history (e.g. `git log -S "<item_name>" -- "*.py"` to find when it was implemented, and `git log -S "<item_name>" -- "*.md"` to find when it was added to the specification).
2. After determining the correct count, perform a repository-wide search across all file types (.py, .yaml, .yml, .env, .env.example, .md, .toml, .cfg, .ini, .json) for every instance of the old count that appears in the context of the thing being counted (e.g. search for `\b44\b` when correcting a logging event count from 44 to 45). Verify each match to determine whether it refers to the count being corrected or to something else (such as a requirement number), and update all stale instances. A specification-wide search is not sufficient — counts such as requirement totals may appear in README files, code comments, comments in continuous integration workflows, or other non-specification documents.

SCOPE OF NORMATIVE KEYWORDS IN SPECIFICATIONS

When a specification section uses a normative keyword (such as 'shall', 'must', or 'should') to govern a collection of items that serve different purposes — for example, a directory tree containing both application source files and operational deployment templates — the normative keyword must be scoped to each category individually rather than applied as a blanket over the entire collection.

SPECIFICATION REQUIREMENTS

The specification is a purely prescriptive document that defines the target state of the system. It must never comment on what is or is not currently implemented. Every requirement, stage, and configuration example shall be written as a normative statement of what the system shall do, not annotated with implementation status.

Every implementation change must be preceded by a corresponding specification change. If a feature, behaviour, or configuration parameter is not yet documented in the specification, the specification must be updated and committed first, and only then may the implementation be written. The specification commit must always appear before the implementation commit in the git history.

When bumping the version of the specification document, the specification file shall be renamed to reflect the new version number, following the established pattern `specification_version_{major}_{minor}_{patch}.md`. The rename shall be included in the same commit that updates the document version and changelog.

When bumping the version of the specification document, every reference to the previous specification version that appears in code comments, docstrings, inline annotations, comments in configuration files, and comments in continuous integration workflows shall be updated to cite the new version number in the same commit that bumps the version. The version reference updates are not a separate follow-up step; they are part of the version bump itself. Never create a separate commit for updating version references — they must be included in the commit that bumps the specification version. References to the specification version inside the specification file's own changelog table are historical records and shall not be updated. This principle extends to all values in changelog entries — including counts, configuration defaults, and any other figures: They are historical records of what was true at the time of that changelog entry and shall not be updated when the current value changes.

SPECIFICATION AUTHORITY AND EXTERNAL ASSESSMENTS

The specification is the authoritative source of truth for what constitutes correct system behaviour, but it is not infallible. When an external document — including audit reports, review feedback, or third-party assessments — characterises a specification-compliant behaviour as a deficiency, defect, or design issue, do not silently accept the finding as actionable and do not silently reject it either. Instead, verify the finding against the specification and present both perspectives to the user:

1. What the specification prescribes and why (quoting the relevant section).
2. What the external assessment recommends and why.
3. Whether the external assessment has identified a genuine limitation in the specification's design — a case where the specification may not be optimal even though the implementation conforms to it.

After presenting both perspectives, make a clear engineering recommendation. If the external assessment identifies a genuine design improvement — one where industry best practice, operational reality, or engineering rigour favours the external recommendation over the specification's current prescription — recommend updating the specification rather than defaulting to specification compliance. The specification exists to serve the system, not the other way around. Treating the specification as immutable when evidence points to a better design is itself a deficiency.

The user decides whether to treat the finding as (a) invalid because the specification's design trade-off is sound, (b) a specification improvement opportunity that warrants updating the specification first and then the implementation, or (c) something to defer. Never unilaterally commit to implementing a change that contradicts the specification, and never unilaterally dismiss an external finding without surfacing it.

README REQUIREMENTS

README.md must contain, at minimum:

- Clear setup steps
- Run instructions
- Environment prerequisites
- Example commands

REQUIREMENTS FOR COMMIT MESSAGES

Commit messages must describe the intent of the changes — why the change was made and what it achieves — not the mechanical edits performed. For example, "Add 'right' to 'before' in docstrings" describes the edit but not the intent; "Tighten the temporal language in docstrings to reflect that CLAUDE.md must be read immediately before each commit" describes the intent. When the intent is clear, the mechanical detail can be inferred from the diff; when only the mechanical detail is stated, the intent cannot be recovered.

A subject line that names the capability introduced, the edit performed, or the mechanism employed — without naming the problem, deficiency, or limitation in the previous state that made the change necessary — is incomplete. A reader cannot reconstruct the motivation from the capability alone. For example, "Introduce optional capability interfaces so that the controller dispatches generically via type assertion" describes the mechanism but not the motivation; "Decouple optional cloud provider operations from the controller so that enabling support for a provider requires only implementing the relevant interface, not modifying controller dispatch logic" names the problem and the improvement it enables. When the subject line uses a "so that" clause, the clause must describe the improvement to the developer's workflow, the system's correctness, or the codebase's maintainability — not the technical mechanism by which the improvement is achieved.

Conversely, the subject line must contain only the intent — the problem being corrected, the deficiency being eliminated, or the improvement being achieved — not the mechanical edit that implements it. A subject line that primarily describes what was done to the codebase (such as 'Add line X to file Y' or 'Remove line X from file Y') rather than what the change achieves defers the motivation to a subordinate position, regardless of whether that motivation appears in a 'so that' clause, a 'because' clause, or any other trailing construction. The diagnostic test: a subject line that answers 'what did you edit?' is mechanical; one that answers 'why is this commit an improvement?' names the intent. When the mechanism adds useful context beyond what the diff alone conveys, relegate it to bullet points in the commit body — do not embed it in the subject line. For example, "Set CGO_ENABLED=1 on the Makefile test target so that go-sqlite3 builds with the real driver" leads with the mechanism; the correct form is a subject line of "Ensure go-sqlite3 builds with the real driver instead of silently falling back to a non-functional stub" with the mechanism in the body.

The "why is this commit an improvement?" test must be applied to the subject line, not the verb in isolation. The answer must be intelligible to a reader unfamiliar with this codebase's conventions: a subject line that describes an outcome that is self-evidently an improvement to such a reader is intent-led; one that describes an edit whose value can only be evaluated with project-specific context is mechanical. The same verb can therefore appear in mechanical and intent-led subject lines, depending on whether what it acts on counts as a deficiency universally, or only under this codebase's conventions. For example, "Eliminate the race condition in the connection-pool resize handler" is intent-led — race conditions are universally a defect, so the outcome (a race-free handler) is self-evidently an improvement. "Eliminate the abbreviation 'auth' from the description of the GET /healthz endpoint in control-plane/README.md" is mechanical — the same verb 'eliminate' acts on the abbreviation, which counts as a deficiency only under this codebase's no-abbreviation convention; without that convention, the message describes only a text edit.

For cases where the deficiency is project-specific, the intent-led form must describe a universally recognisable improvement that the change produces. Universal improvements include consistency between adjacent items, self-explanatory readability, structural unambiguity, removal of redundancy, and other properties whose desirability any reader recognises in isolation. The abbreviation removal above can therefore be expressed as "Ensure the description of the GET /healthz endpoint in control-plane/README.md is consistent with the descriptions of the other endpoints, which use the full word 'authentication'" — intent-led, because consistency between adjacent items is universally desirable.

The subject line's complement — the object, predicate, or clause that the verb governs — must include the deficiency being corrected, the harm being prevented, or the limitation being removed. A complement that describes only the resulting state, the target behaviour, or the mechanism — without naming the deficiency — causes the subject line to answer 'what is true after the change?' rather than 'what was wrong before it?', regardless of the verb choice. The mechanism or resulting state may accompany the deficiency but must not replace it. For example, 'Ensure compound `git commit` is blocked unconditionally and at all levels of shell nesting' has a complement that describes only the target behaviour ('blocked unconditionally', 'at all levels of shell nesting') without naming the deficiency; the correct form includes what was wrong — 'Prevent the hook blocking `git commit` in compound commands from being bypassed outside rebases and inside subshells' — because the complement identifies the concrete bypass paths that the change closes.

A subject line ascends a chain of 'but why?' questions, accumulating facets as it goes — the artefact's scope or function, then the manifestation it prevents or enforces, then the consequence of that manifestation, then the foundational property that makes the consequence bad, then the governing principle that connects that property to the specific decision at hand. The subject line must continue ascending until the purpose — the 'why' — is reached, which is the layer where the next 'but why?' would be answered not by anything specific to this change or project, but by the reader's general knowledge of the domain.

The stopping point is thus marked by a shift in the audience that further explanation would address. Up to the purpose layer, each layer gives the reader information specific to this change or project that they cannot supply themselves. Past the purpose layer, each further layer would give information that the reader's general knowledge of the domain already supplies — and that reader is not the audience of a commit message. The audience is assumed to be a competent practitioner of the domain; continuing past the purpose layer treats them as less than that. Stopping below the purpose layer leaves change-specific or project-specific explanatory work undone; stopping at it discharges that work; stopping above it encroaches on what the reader already brings.

The depth at which the purpose is reached varies by change. Some changes reach it in two or three layers; others in five or more. Subject lines must ascend to the purpose layer regardless of the depth that takes; any stopping point below it leaves a 'but why?' that still requires project-specific reasoning to answer.

The ascent can be illustrated with three worked cases that reach the purpose at different depths.

Consider first a change to a prohibition on referencing external documents, whose purpose is reached at the fifth layer. Starting from a form that begins no ascent — "Close the gap in CLAUDE.md's commit-message directive where references to Claude-related artefacts could slip in", which names a manifestation only — successive intent layers run:

1. "Extend CLAUDE.md's prohibition on referencing external documents to also cover Claude-related artefacts" — adds the prohibition's scope ("on referencing external documents"); the reader asks 'but why extend it?'.
2. "..., preventing them from slipping into commits that do not modify them" — adds the manifestation prevented; the reader asks 'but why is that bad?'.
3. "..., which would be undesirable because the Claude-related artefacts would be acting as external documents in those cases" — adds the consequence; the reader asks 'but why is acting as external documents bad?'.
4. "..., because the Claude-related artefacts, like external documents, serve specifically as auxiliary documentation for ad hoc productivity" — adds the foundational property; the reader asks 'but why shouldn't commits reference auxiliary documentation for ad hoc productivity?' — still project-specific.
5. "..., and the durable record of a project's commits must remain self-contained, not depending on auxiliary, ephemeral documentation that can change or disappear over time" — adds the governing principle. The fifth layer is the purpose: the next 'but why?' (why must durable records be self-contained?) invokes what any competent practitioner of the domain already knows.

Consider next a change to a diagnostic test for intent-led versus mechanical subject lines, whose purpose is reached at the fourth layer. Starting form: "Close the gap in CLAUDE.md's diagnostic test where improvement-naming verbs could still pass it". Successive intent layers:

1. "Tighten CLAUDE.md's diagnostic test for distinguishing intent-led from mechanical subject lines" — adds the test's scope; the reader asks 'but why tighten it?'.
2. "..., so that adopting an improvement-naming verb such as 'ensure' or 'prevent' no longer suffices when the surrounding subject line describes an edit intelligible only under this codebase's conventions" — adds the manifestation prevented; the reader asks 'but why is that bad?'.
3. "..., because such subject lines are intelligible only under this codebase's conventions and leave readers outside the project unable to understand the commit" — adds the consequence; the reader asks 'but why is it bad for readers outside the project not to understand?'.
4. "..., and commit messages must remain intelligible to any competent reader independent of this codebase's conventions" — adds the governing principle. The fourth layer is the purpose: the next 'but why?' (why must commit messages be intelligible independent of conventions?) invokes what any competent practitioner of the domain already knows.

Consider finally a change to a list of approved abbreviations, whose purpose is reached at the third layer. Starting form: "Close the gap in CLAUDE.md's list of approved abbreviations where DTO had no prescribed handling". Successive intent layers:

1. "Extend CLAUDE.md's list of approved abbreviations with DTO" — adds the list's scope ("of approved abbreviations"); the reader asks 'but why add DTO?'.
2. "..., since DTO had no prescribed handling and was therefore subject to inconsistent treatment in code and prose" — adds the manifestation and its consequence together; the reader asks 'but why is inconsistent treatment bad?'.
3. "..., and consistent treatment of terms across code and prose is required for readability and for reliable reference to the same concept" — adds the governing principle. The third layer is the purpose: the next 'but why?' (why are readability and reliable reference required?) invokes what any competent practitioner of the domain already knows.

The three cases reach the purpose at different depths because the chain from artefact to domain-baseline knowledge has different length in each: in the list case the principle is close; in the test case a consequence intercedes; in the prohibition case both a consequence and a foundational property intercede before the principle. The number of layers is incidental — the rule is to keep ascending while the next 'but why?' would require project-specific reasoning to answer.

This principle extends to the rest of the body. When a body is needed, each bullet point should describe a decision and its rationale — not enumerate every function added or file touched. The diff already records what was touched; the commit message records what a reader cannot recover from the diff alone.

Commit messages must describe the changes in terms of the specification and the codebase. They must never reference external documents, such as audit reports, review feedback, or third-party assessments, or anything Claude-related such as CLAUDE.md or .claude (unless the commit modifies Claude-related files). The motivation for a change is the specification requirement it satisfies or the defect it corrects — not the external document that identified it. This prohibition extends to organisational terminology, sequencing labels, and structural vocabulary inherited from external documents — such as phase numbers, finding identifiers, priority tiers, or evaluation categories. When a series of commits implements a multi-step change, describe each step in terms of what it does to the codebase (e.g. "Split application/models.py into application/api/schemas/ subpackage"), not in terms of where it falls in an externally defined plan.

The prohibition on referencing CLAUDE.md also applies to vocabulary coined within CLAUDE.md itself — the names of rules defined in it (e.g. "the connector rule"), the names of lists maintained in it (e.g. "established technical compound terms"), and any term whose meaning a reader can only recover by consulting CLAUDE.md. A commit message that uses such vocabulary references CLAUDE.md as surely as one that names the file. Describe the deficiency being corrected and the improvement being achieved using standard engineering, linguistic, or domain vocabulary that a reader unfamiliar with CLAUDE.md can understand — or name the specific edits performed. For example, write "expand `auth` to `authentication` and `repo` to `repository`" rather than "expand the unapproved abbreviations". The test: if a reader without access to CLAUDE.md would have to guess at the meaning of a term or ask what it refers to, the term is CLAUDE.md-internal vocabulary and must be replaced.

When a commit modifies a specific artefact whose identity is not self-evident from the change description, the commit message must name that artefact explicitly. For example, a message that says "Add directive to recommend specification improvements" is ambiguous — it could refer to a change in the specification, in CLAUDE.md, in a continuous integration workflow, or in application code. The correct form names the file or artefact: "Add directive to CLAUDE.md to recommend specification improvements". This applies to all artefacts — the specification, CLAUDE.md, the Makefile, the Dockerfile, Kubernetes manifests, continuous integration workflows, and any other file where the subject line alone does not make the target unambiguous.

Commit messages must never reference other commits by their hash. A hash is an opaque identifier that conveys no semantic information; a reader encountering a hash must look it up to understand the reference. When a commit message needs to refer to a prior change, it must describe that change by its intent — the deficiency it corrected or the capability it introduced — not by its hash.

When a commit message mentions a rename (not that it has to) — of a file, directory, class, function, variable, or any other identifier — it must include both the old name and the new name. A rename description that states only the new name forces the reader to consult the diff to determine what was renamed from; a description that states only the old name forces the reader to consult the diff to determine what it was renamed to. Both names are necessary for the commit message to be self-contained.

Following an interactive rebase that edits files, each edited commit's message shall be reassessed for accuracy against the updated diff. If any commit message no longer accurately describes the commit's content, a follow-up interactive rebase shall be used to correct it.

When an interactive rebase rewrites commit messages — whether by splitting a commit, editing its content, or rewording its message — each resulting commit message must be verified against the resulting diff for both accuracy and completeness. Detail from the original message that remains accurate against the new diff — concrete examples, precise terminology, specific manifestations of deficiencies, and rationale — must be preserved; detail that is no longer accurate against the new diff must be updated or removed, not carried over blindly. A rebase operation that produces commits whose messages are accurate but less informative than the originals is an information loss; equally, a rebase operation that carries over detail that no longer matches the resulting diff is an accuracy violation. When splitting a commit whose message contained a body, distribute the original body's detail across the resulting commits so that each carries the portion that remains accurate against its changes.

When an interactive rebase stops due to a merge conflict, never use `git commit --amend` to finalise the resolution. During a conflict, HEAD still points to the last successfully applied commit — the conflicted commit has not yet been created. Running `--amend` in this state replaces that previous commit with the merged result, losing the previous commit as a distinct entry in the history. Instead, stage the resolved files with `git add` and run `git rebase --continue`, which creates the conflicted commit as a new entry. This prohibition does not apply to `edit` marker stops without a conflict, where HEAD is the commit being edited and `git commit --amend` is correct.

When a change belongs in an unpushed commit — for example, a formatting correction caused by a bulk string replacement in that commit, or a fixup discovered after committing — amend it into the commit it belongs to. For the most recent commit, use `git commit --amend`. For an earlier unpushed commit, use an interactive rebase to edit or fixup the target commit. Do not create a separate follow-up commit for changes that are logically part of an existing unpushed commit. This directive overrides the Claude Code system prompt's instruction to always create new commits rather than amending.

PLANNING REQUIREMENTS

Every plan must end with a section titled "Unresolved questions", if any exist. An unresolved question is any ambiguity, missing requirement, undetermined design choice, or dependency on information not yet available that could affect the correctness or completeness of the plan's implementation. If no unresolved questions exist, the section shall state "None." explicitly. This section ensures that the user can identify and resolve open issues before approving the plan for implementation.

REQUIREMENTS FOR JUSTIFICATION OF NUMERICAL VALUES

Every numerical value that appears in any output — whether a threshold, a sizing parameter, a timeout, a percentage, a capacity figure, a count, a ratio, a scaling factor, a retention period, a polling interval, a pool size, a fleet count, a partition count, a replication factor, or any other concrete number that influences a design or operational decision — must be accompanied by an explicit justification chain. A number without a justification is an assertion without evidence. No numerical value may be stated as a fact without justification.

The justification chain must trace the number to one or more of the following grounding sources, listed in order of preference:

1. A specification or document reference — a line, section, or table in an authoritative document that prescribes or constrains the value. Cite the specific location (section number, line number, table name). When the referenced specification states a maximum, a default, or a target, name which of these the reference represents — do not conflate a timeout maximum with an expected duration, a default with a recommendation, or a target with a guarantee.
2. A mathematical derivation from documented parameters — a formula whose every input is itself grounded in one of these sources. State the formula, name each input, cite the source of each input, and show the computation. When using Little's Law, queuing theory, or capacity planning formulae, name the law or formula explicitly so the derivation can be audited. A derivation requires two independent validations: Every input must be grounded in one of the listed sources, and the mathematical operation that combines those inputs must be logically valid for the context in which the result will be used. An operation is logically valid when there is a domain-specific reason why that particular mathematical relationship produces a meaningful result in the target context. An operation borrowed from one context does not transfer to a different context merely because the same numerical inputs are involved. For example, multiplying a baseline count by a sensitivity analysis factor does not produce a valid scheduling milestone, because the sensitivity analysis factor exists to stress-test the robustness of assumptions, not to determine when reviews should occur — the arithmetic is correct but the operation has no logical grounding in the target context. When proposing a derivation, state explicitly why the operation — not just the inputs — is valid for the context in which the result will be applied.
3. A published benchmark or empirical measurement — a performance figure from the documentation, benchmarking suite, or published technical report of the specific technology being discussed. Name the technology, the source, and the conditions under which the measurement was taken (workload type, hardware class, deployment topology). Do not cite benchmarks from a different technology or a materially different deployment topology without stating the extrapolation and its uncertainty.
4. An industry standard or established convention — a value that is widely adopted in the relevant engineering domain and can be verified by reference to standard practice. Name the standard or convention and the domain in which it applies (e.g. "Kubernetes default node-status-update-frequency of 10 seconds", "control system hysteresis ratio of 0.4–0.6 for threshold-based switching").
5. First-principles reasoning — a derivation from physical, mathematical, or engineering constraints where no empirical source exists. State the constraint, the reasoning chain, and the assumptions. This is the least preferred source and must be accompanied by a sensitivity analysis: what happens if the assumptions are wrong by 2× in either direction?

When a number is derived from an assumption that is not itself grounded in sources 1–4, the assumption must be stated explicitly, named as an assumption (not presented as a fact), and accompanied by the following:

- A sensitivity analysis showing how the dependent values change if the assumption varies across its plausible range. At minimum, evaluate the assumption at 0.5× and 2× its stated value.
- A statement of whether the downstream design (sizing, threshold, pool configuration, or other dependent decision) is robust across that range or sensitive to the assumed value. If the design is robust (the same sizing works at 0.5× and 2×), state this explicitly — it reduces the risk of the assumption. If the design is sensitive (the sizing must change at 0.5× or 2×), prescribe the adjustment or flag it as a decision point.

When a number falls within a valid range, derive and state the range bounds before selecting a specific value. The derivation of bounds must explain what constraint defines each bound (why values below the lower bound are invalid, why values above the upper bound are invalid). The selection of a specific value within the range must then be justified by a criterion distinct from the bounds themselves — cost efficiency, operational response time, alignment with another system parameter, or empirical calibration.

When a number is a starting calibration point that must be validated empirically (e.g. through load testing, production observation, or benchmarking), state this explicitly and prescribe the calibration protocol: what to measure, what to vary, what threshold in the measurement determines whether the number should be adjusted, and in which direction. A calibration point without a calibration protocol is an unvalidated guess.

For every numerical value, evaluate whether adjacent values would be materially better or worse. Specifically, for any threshold, interval, pool size, fleet count, or similar parameter, state why the value is not half of what is prescribed and why it is not double what is prescribed. If halving or doubling the value produces no material change in the design's behaviour, the value may be less important than it appears — state this. If halving or doubling produces a failure mode, name the failure mode. This "why not half, why not double" evaluation must be performed for every number, with the following exceptions: numbers determined by complete enumeration (where the count is the result of listing all items and no design latitude exists), literal references (such as line numbers, section numbers, or HTTP status codes), and mathematical constants.

When a number participates in a system of related numbers (e.g. a trigger threshold paired with a reversal threshold, a pool size paired with a maximum client connection count, a warning threshold paired with a critical threshold), the relationship between the numbers must be stated and justified. If one number is derived from another (e.g. the reversal threshold is 60% of the trigger threshold), state the ratio, justify the ratio (not just the absolute values), and explain what would go wrong if the ratio were materially different.

When a number is derived from a document source, verify that the source says what the derivation claims it says. Timeout maximums are not expected durations. Default values are not recommendations. Peak capacity is not sustained throughput. Warning thresholds are not operational baselines. If the derivation conflates two distinct concepts, the number is wrong regardless of whether it happens to produce a reasonable result.

This requirement applies to all numerical values in all output contexts: architecture documents, capacity planning, configuration prescriptions, threshold specifications, scaling parameters, monitoring configurations, operational runbooks, and any other context where a number influences a decision. It applies equally to numbers in prose, in tables, in formulae, and in code comments. A number in a table cell requires the same justification as a number in a paragraph — the format does not reduce the obligation.

ESTABLISHED TECHNICAL COMPOUND TERMS

- cloud provider
- data transfer object
- deep learning
- file path
- large language model
- machine learning
- natural language processing
- neural network
- response body

APPROVED ABBREVIATIONS

When the same abbreviation appears in multiple rows — because it is used to shorten more than one distinct term — the correct expansion is determined by context. The abbreviation/expansion rule (always abbreviate or always expand) applies equally to all rows sharing that abbreviation; only the choice of which expansion to use varies by context.

| Abbreviation | Expansion | In code | In prose |
|---|---|---|---|
| All file extensions | (varies by extension) | abbreviated | abbreviated |
| All ISO 4217 currency codes | (varies by currency) | abbreviated | abbreviated |
| adv | adversarial | expanded | expanded |
| AI | artificial intelligence | abbreviated | abbreviated |
| API | Application Programming Interface | abbreviated | abbreviated |
| arch | architecture | expanded | expanded |
| ASGI | Asynchronous Server Gateway Interface | abbreviated | abbreviated |
| BE | backend | expanded | expanded |
| bid | batch identifier | expanded | expanded |
| cat | category | expanded | expanded |
| CI | continuous integration | expanded | expanded |
| CLI | command-line interface | abbreviated | expanded |
| CRUD | create, read, update, delete | abbreviated | abbreviated |
| CLIP | Contrastive Language-Image Pre-training | abbreviated | abbreviated |
| cmd | command | expanded | expanded |
| CORS | Cross-Origin Resource Sharing | abbreviated | abbreviated |
| CPU | central processing unit | abbreviated | abbreviated |
| CUDA | Compute Unified Device Architecture | abbreviated | abbreviated |
| cwd | current working directory | expanded | expanded |
| DDL | data definition language | abbreviated | expanded |
| dep | dependency | expanded | expanded |
| desc | description | expanded | expanded |
| DevOps | development operations | abbreviated | abbreviated |
| diff | difference | abbreviated | abbreviated |
| docs | documentation | expanded | expanded |
| DTO | data transfer object | abbreviated | expanded |
| e.g. | for example | expanded | abbreviated |
| etc. | et cetera | abbreviated | abbreviated |
| ext | extension | expanded | expanded |
| FE | frontend | expanded | expanded |
| FR | functional requirement | abbreviated | abbreviated |
| GB | gigabyte | abbreviated | abbreviated |
| GiB | gibibyte | abbreviated | abbreviated |
| GCC | GNU Compiler Collection | abbreviated | abbreviated |
| GDPR | General Data Protection Regulation | abbreviated | abbreviated |
| GGUF | GGML Unified Format | abbreviated | abbreviated |
| GNU | GNU's Not Unix | abbreviated | abbreviated |
| gomod | Go module | expanded | expanded |
| GPU | graphics processing unit | abbreviated | abbreviated |
| HPA | Horizontal Pod Autoscaler | abbreviated | abbreviated |
| HTTP | Hypertext Transfer Protocol | abbreviated | abbreviated |
| i.e. | that is to say | expanded | abbreviated |
| ID | identifier | abbreviated | abbreviated |
| idx | index | expanded | expanded |
| info | information | expanded | expanded |
| I/O | input/output | abbreviated | abbreviated |
| IP | Internet Protocol | abbreviated | abbreviated |
| JDBC | Java Database Connectivity | abbreviated | expanded |
| JIT | just-in-time | abbreviated | abbreviated |
| JPEG | Joint Photographic Experts Group | abbreviated | abbreviated |
| JPG | Joint Photographic Experts Group (variant) | abbreviated | abbreviated |
| JSON | JavaScript Object Notation | abbreviated | abbreviated |
| JSONB | JSON Binary | abbreviated | abbreviated |
| JTI | JSON Token Identifier | abbreviated | abbreviated |
| JWT | JSON Web Token | abbreviated | abbreviated |
| KB | kilobyte | abbreviated | abbreviated |
| kw | keyword | expanded | expanded |
| lf | lock file | expanded | expanded |
| LLM | large language model | abbreviated | expanded |
| max | maximum | expanded | expanded |
| MB | megabyte | abbreviated | abbreviated |
| min | minimum | expanded | expanded |
| msg | message | expanded | expanded |
| MTBF | mean time between failures | expanded | expanded |
| NFR | non-functional requirement | abbreviated | abbreviated |
| NSFW | not safe for work | abbreviated | abbreviated |
| num | number | expanded | expanded |
| obs | observation | expanded | expanded |
| OLAP | online analytical processing | expanded | expanded |
| op | operation | expanded | expanded |
| pkg | package | expanded | expanded |
| PNG | Portable Network Graphics | abbreviated | abbreviated |
| pyproj | pyproject | expanded | expanded |
| QPS | queries per second | expanded | expanded |
| RAM | random-access memory | abbreviated | abbreviated |
| README | read me | abbreviated | abbreviated |
| rel | relative | expanded | expanded |
| repo | repository | expanded | expanded |
| req | requirement | expanded | expanded |
| REST | Representational State Transfer | abbreviated | abbreviated |
| rid | requirement identifier | expanded | expanded |
| RO | Reference Operation | abbreviated | abbreviated |
| sev | severity | expanded | expanded |
| spec | specification | expanded | expanded |
| SQL | Structured Query Language | abbreviated | abbreviated |
| SSB | Star Schema Benchmark | abbreviated | expanded |
| SSH | Secure Shell | abbreviated | abbreviated |
| sub | subsystem | expanded | expanded |
| TCP | Transmission Control Protocol | abbreviated | abbreviated |
| temp | temporary | expanded | expanded |
| temp | temperature | expanded | expanded |
| TPC-H | Transaction Processing Performance Council Benchmark H | abbreviated | expanded |
| URL | Uniform Resource Locator | abbreviated | abbreviated |
| UUID | Universally Unique Identifier | abbreviated | abbreviated |
| v | version | expanded | expanded |
| VRAM | video random-access memory | abbreviated | abbreviated |
| WSGI | Web Server Gateway Interface | abbreviated | abbreviated |
| WSL | Windows Subsystem for Linux | abbreviated | abbreviated |
| WSL2 | Windows Subsystem for Linux 2 | abbreviated | abbreviated |