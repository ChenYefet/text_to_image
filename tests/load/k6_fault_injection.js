/**
 * k6 Load Test Script for RO8 — Fault Injection Under Concurrent Load
 *
 * This script implements the RO8 reference operation as defined in the
 * Text-to-Image specification (v5.2.1). It verifies that the service
 * handles upstream dependency failures gracefully under concurrent load
 * without crashing, hanging, or producing non-JSON responses, and that
 * it recovers automatically when the dependency is restored.
 *
 * The test runs for 10 minutes across three phases:
 *   - Phase 1 (0-3 minutes):  Normal operation; llama.cpp is running
 *   - Phase 2 (3-7 minutes):  Fault active; llama.cpp is stopped
 *   - Phase 3 (7-10 minutes): Recovery; llama.cpp is restarted
 *
 * IMPORTANT — Manual intervention required:
 *   The operator must manually stop and restart the llama.cpp server
 *   at the phase transition points. The script will output console
 *   reminders at the appropriate times:
 *     - At 3 minutes: Stop the llama.cpp server
 *       (e.g. kill $(pgrep llama-server))
 *     - At 7 minutes: Restart the llama.cpp server
 *
 * Success criteria (from NFR9 — Fault tolerance under concurrent load):
 *
 *   Phase 1 (normal operation):
 *     - At least 95% of all requests return HTTP 200 with a valid
 *       enhanced_prompt field
 *     - The 95th percentile latency is <= 30 seconds
 *
 *   Phase 2 (fault active):
 *     - 100% of all requests return an HTTP response (HTTP 200 or
 *       HTTP 502) with a valid JSON body within 10 seconds
 *     - At least 95% of Phase 2 requests return HTTP 502 with
 *       error.code equal to "upstream_service_unavailable"
 *     - No request produces a non-JSON response body, an unstructured
 *       error page, or an HTTP 500 response
 *
 *   Phase 3 (recovery):
 *     - Within 30 seconds of llama.cpp restart, HTTP 200 responses
 *       resume
 *     - After the initial 30-second recovery window, at least 95% of
 *       requests return HTTP 200 with valid enhanced_prompt fields
 *
 *   Across all phases:
 *     - The service process does not crash, restart, or become
 *       unresponsive at any point during the 10-minute test
 *
 * Usage:
 *   k6 run tests/load/k6_fault_injection.js
 *   k6 run --env BASE_URL=http://localhost:8000 tests/load/k6_fault_injection.js
 */

import http from "k6/http";
import { check } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

// ---------------------------------------------------------------------------
// Custom metrics — Phase 1 (normal operation, minutes 0-3)
// ---------------------------------------------------------------------------

const rate_of_successful_responses_during_phase_1 = new Rate(
  "rate_of_successful_responses_during_phase_1"
);

const duration_of_response_during_phase_1_in_milliseconds = new Trend(
  "duration_of_response_during_phase_1_in_milliseconds"
);

const number_of_requests_during_phase_1 = new Counter(
  "number_of_requests_during_phase_1"
);

// ---------------------------------------------------------------------------
// Custom metrics — Phase 2 (fault active, minutes 3-7)
// ---------------------------------------------------------------------------

const rate_of_structured_fault_responses_during_phase_2 = new Rate(
  "rate_of_structured_fault_responses_during_phase_2"
);

const rate_of_responses_with_valid_json_during_phase_2 = new Rate(
  "rate_of_responses_with_valid_json_during_phase_2"
);

const rate_of_responses_within_timeout_during_phase_2 = new Rate(
  "rate_of_responses_within_timeout_during_phase_2"
);

const rate_of_non_500_responses_during_phase_2 = new Rate(
  "rate_of_non_500_responses_during_phase_2"
);

const duration_of_response_during_phase_2_in_milliseconds = new Trend(
  "duration_of_response_during_phase_2_in_milliseconds"
);

const number_of_requests_during_phase_2 = new Counter(
  "number_of_requests_during_phase_2"
);

// ---------------------------------------------------------------------------
// Custom metrics — Phase 3 (recovery, minutes 7-10)
// ---------------------------------------------------------------------------

const rate_of_successful_responses_during_phase_3 = new Rate(
  "rate_of_successful_responses_during_phase_3"
);

/**
 * Tracks success rate specifically for the portion of Phase 3 after
 * the initial 30-second recovery window (from minute 7:30 onward).
 */
const rate_of_successful_responses_after_recovery_window = new Rate(
  "rate_of_successful_responses_after_recovery_window"
);

const duration_of_response_during_phase_3_in_milliseconds = new Trend(
  "duration_of_response_during_phase_3_in_milliseconds"
);

const number_of_requests_during_phase_3 = new Counter(
  "number_of_requests_during_phase_3"
);

// ---------------------------------------------------------------------------
// Cross-phase metrics
// ---------------------------------------------------------------------------

const rate_of_valid_json_responses_across_all_phases = new Rate(
  "rate_of_valid_json_responses_across_all_phases"
);

// ---------------------------------------------------------------------------
// Base URL configuration
// ---------------------------------------------------------------------------

/**
 * The base URL of the Text-to-Image API Service. Configurable via the
 * k6 environment variable BASE_URL; defaults to http://localhost:8000.
 */
const base_url_of_service =
  __ENV.BASE_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Pool of unique prompts
// ---------------------------------------------------------------------------

/**
 * The same pool of 20 unique prompts as used in the RO7 script, as
 * specified by the RO8 execution details: "Each virtual user issues
 * requests with prompts from the same pool as RO7."
 */
const pool_of_unique_prompts = [
  // Short prompts (approximately 10-50 characters)
  "a red fox in snow",
  "sunset over calm ocean waves",
  "a lone tree on a hilltop at dawn",
  "ancient stone bridge crossing a river",

  // Medium prompts (approximately 50-150 characters)
  "a steampunk clockwork city with brass towers and copper pipes, illuminated by gas lanterns at twilight",
  "two astronauts playing chess on the surface of Mars with Earth visible in the background sky",
  "a Japanese garden in autumn with a curved wooden bridge over a koi pond surrounded by maple trees",
  "a cosy library interior with floor-to-ceiling bookshelves, a crackling fireplace, and a sleeping cat",

  // Longer prompts (approximately 150-300 characters)
  "an underwater coral reef teeming with tropical fish and sea turtles, sunlight filtering through the crystal clear water above, with an ancient shipwreck partially visible in the background covered in barnacles and coral growth",
  "a medieval blacksmith working at an anvil in a dimly lit forge, sparks flying from the hammer, with various swords and shields hanging on the stone walls and a roaring furnace casting orange light across the scene",
  "a futuristic cyberpunk street market at night with neon signs in multiple languages, vendors selling exotic food from hovering carts, rain-slicked pavement reflecting colourful lights, and a massive holographic advertisement floating overhead",
  "a peaceful mountain monastery perched on a cliff edge above the clouds, with prayer flags fluttering in the wind, stone steps carved into the mountainside, and a monk meditating in the courtyard as the sun rises",

  // Longer prompts (approximately 300-500 characters)
  "a vast desert landscape at golden hour with towering sand dunes casting long shadows across the rippled terrain, a caravan of camels silhouetted against the setting sun moving slowly along the ridge of the tallest dune, with a distant oasis visible as a small patch of green surrounded by palm trees, and the sky painted in gradients of orange, purple, and deep blue as the first stars begin to appear",
  "an enchanted forest clearing where bioluminescent mushrooms and flowers create a soft ethereal glow in shades of blue and violet, a crystal clear stream winds through the moss-covered ground reflecting the magical light, ancient twisted oak trees form a natural cathedral arch overhead with their branches intertwined, fireflies drift lazily through the warm summer air, and a family of deer drinks peacefully from the stream",
  "a grand Victorian greenhouse conservatory filled with exotic tropical plants and orchids of every colour imaginable, wrought iron framework supporting panels of glass that catch and refract the afternoon sunlight into rainbow patterns on the tiled floor, a central fountain with water lilies and goldfish, winding pathways between raised garden beds, hanging ferns creating green curtains, and a small reading nook with a cushioned bench tucked beneath an ancient wisteria vine",
  "a dramatic scene of a lighthouse standing firm against a violent storm at sea, enormous waves crashing against the rocky cliff base sending spray high into the air, lightning illuminating the dark churning clouds above, the lighthouse beam cutting through sheets of rain and mist to guide ships to safety, seabirds sheltering in the crevices of the weathered stone tower, and far in the distance a cargo ship struggling against the towering swells",

  // Additional prompts for variety
  "a whimsical treehouse village connected by rope bridges and wooden walkways high in the canopy of a redwood forest",
  "a vintage 1950s American diner interior with chrome stools, a jukebox, and milkshakes on the counter",
  "a Northern Lights display over a frozen lake in Finland with a small wooden cabin and snow-covered pine trees",
  "a bustling Renaissance-era Italian marketplace with merchants, artists painting portraits, and a marble fountain",
];

// ---------------------------------------------------------------------------
// Phase boundary timestamps (in milliseconds since the test started)
// ---------------------------------------------------------------------------

/**
 * Phase 1 runs from 0 to 3 minutes (0 to 180,000 milliseconds).
 * Phase 2 runs from 3 to 7 minutes (180,000 to 420,000 milliseconds).
 * Phase 3 runs from 7 to 10 minutes (420,000 to 600,000 milliseconds).
 *
 * The recovery window within Phase 3 lasts for 30 seconds after the
 * phase boundary (420,000 to 450,000 milliseconds).
 */
const boundary_between_phase_1_and_phase_2_in_milliseconds = 3 * 60 * 1000;
const boundary_between_phase_2_and_phase_3_in_milliseconds = 7 * 60 * 1000;
const end_of_recovery_window_in_phase_3_in_milliseconds =
  boundary_between_phase_2_and_phase_3_in_milliseconds + 30 * 1000;

// ---------------------------------------------------------------------------
// State tracking for console reminders
// ---------------------------------------------------------------------------

/**
 * Tracks whether the phase transition reminders have already been
 * printed, so that each reminder is displayed only once across all
 * virtual users. Note: In k6, __VU and __ITER are per-VU, but
 * module-level variables are shared within a single VU context.
 * We use a simple flag approach that tolerates duplicate prints
 * from multiple virtual users (a minor cosmetic issue).
 */
let reminder_to_stop_llama_cpp_has_been_printed = false;
let reminder_to_restart_llama_cpp_has_been_printed = false;

// ---------------------------------------------------------------------------
// k6 test configuration
// ---------------------------------------------------------------------------

export const options = {
  /**
   * 5 concurrent virtual users for 10 minutes, using k6 stages to
   * maintain a constant load throughout the three phases. The stages
   * configuration keeps 5 virtual users active for the full duration
   * without ramping.
   */
  stages: [
    // Phase 1: Normal operation (0-3 minutes)
    { duration: "3m", target: 5 },
    // Phase 2: Fault active (3-7 minutes)
    { duration: "4m", target: 5 },
    // Phase 3: Recovery (7-10 minutes)
    { duration: "3m", target: 5 },
  ],

  /**
   * Automated pass/fail thresholds derived from the NFR9 success
   * criteria:
   *
   *   Phase 1: >= 95% success rate, p95 latency <= 30 seconds
   *   Phase 2: 100% valid JSON, 100% non-500 responses,
   *            100% responses within 10 seconds,
   *            >= 95% structured fault responses (HTTP 502 with
   *            error.code = "upstream_service_unavailable")
   *   Phase 3: >= 95% success rate after the 30-second recovery window
   *   All phases: 100% valid JSON responses
   */
  thresholds: {
    rate_of_successful_responses_during_phase_1: ["rate>=0.95"],
    "duration_of_response_during_phase_1_in_milliseconds": ["p(95)<30000"],
    rate_of_responses_with_valid_json_during_phase_2: ["rate>=1.0"],
    rate_of_non_500_responses_during_phase_2: ["rate>=1.0"],
    rate_of_responses_within_timeout_during_phase_2: ["rate>=1.0"],
    rate_of_structured_fault_responses_during_phase_2: ["rate>=0.95"],
    rate_of_successful_responses_after_recovery_window: ["rate>=0.95"],
    rate_of_valid_json_responses_across_all_phases: ["rate>=1.0"],
  },
};

// ---------------------------------------------------------------------------
// HTTP request headers
// ---------------------------------------------------------------------------

const headers_for_request = {
  "Content-Type": "application/json",
};

// ---------------------------------------------------------------------------
// Timestamp of test start
// ---------------------------------------------------------------------------

/**
 * Records the wall-clock time when the test started. This is set on
 * the first iteration of the first virtual user and used to determine
 * which phase each request falls into.
 */
let timestamp_of_test_start_in_milliseconds = 0;

// ---------------------------------------------------------------------------
// Virtual user iteration (default function)
// ---------------------------------------------------------------------------

/**
 * Each virtual user executes this function repeatedly for the full
 * 10-minute duration. On each iteration, the function determines the
 * current phase based on elapsed time, issues a POST request to the
 * prompt enhancement endpoint, and records phase-specific metrics.
 *
 * At phase transition boundaries, the function prints console
 * reminders instructing the operator to stop or restart the llama.cpp
 * server.
 */
export default function () {
  // Initialise the test start timestamp on the first iteration
  if (timestamp_of_test_start_in_milliseconds === 0) {
    timestamp_of_test_start_in_milliseconds = Date.now();
  }

  // Calculate elapsed time since test start
  const elapsed_time_in_milliseconds =
    Date.now() - timestamp_of_test_start_in_milliseconds;

  // Determine the current phase based on elapsed time
  let current_phase_number;
  if (
    elapsed_time_in_milliseconds <
    boundary_between_phase_1_and_phase_2_in_milliseconds
  ) {
    current_phase_number = 1;
  } else if (
    elapsed_time_in_milliseconds <
    boundary_between_phase_2_and_phase_3_in_milliseconds
  ) {
    current_phase_number = 2;
  } else {
    current_phase_number = 3;
  }

  // Print phase transition reminders (once per virtual user, which is
  // acceptable — a small number of duplicate prints is harmless)
  if (
    current_phase_number === 2 &&
    !reminder_to_stop_llama_cpp_has_been_printed
  ) {
    reminder_to_stop_llama_cpp_has_been_printed = true;
    console.log(
      "============================================================"
    );
    console.log(
      "  PHASE 2 STARTED — STOP THE LLAMA.CPP SERVER NOW"
    );
    console.log(
      "  Example command: kill $(pgrep llama-server)"
    );
    console.log(
      "============================================================"
    );
  }

  if (
    current_phase_number === 3 &&
    !reminder_to_restart_llama_cpp_has_been_printed
  ) {
    reminder_to_restart_llama_cpp_has_been_printed = true;
    console.log(
      "============================================================"
    );
    console.log(
      "  PHASE 3 STARTED — RESTART THE LLAMA.CPP SERVER NOW"
    );
    console.log(
      "  The service should recover within 30 seconds of restart."
    );
    console.log(
      "============================================================"
    );
  }

  // Select a random prompt from the pool for this request
  const index_of_selected_prompt = Math.floor(
    Math.random() * pool_of_unique_prompts.length
  );
  const selected_prompt = pool_of_unique_prompts[index_of_selected_prompt];

  // Construct the request body per the prompt enhancement request schema
  const body_of_request = JSON.stringify({
    prompt: selected_prompt,
  });

  // Issue the POST request to the prompt enhancement endpoint
  const response = http.post(
    `${base_url_of_service}/v1/prompts/enhance`,
    body_of_request,
    { headers: headers_for_request }
  );

  // Attempt to parse the response body as JSON
  let parsed_response_body = null;
  let response_body_is_valid_json = false;
  try {
    parsed_response_body = response.json();
    response_body_is_valid_json = true;
  } catch (parse_error) {
    response_body_is_valid_json = false;
  }

  // Track cross-phase JSON validity
  rate_of_valid_json_responses_across_all_phases.add(
    response_body_is_valid_json
  );

  // Determine whether this is a fully successful response
  const response_is_successful =
    response.status === 200 &&
    response_body_is_valid_json &&
    parsed_response_body !== null &&
    typeof parsed_response_body.enhanced_prompt === "string" &&
    parsed_response_body.enhanced_prompt.length > 0;

  // Determine whether this is a structured fault response (HTTP 502
  // with error.code equal to "upstream_service_unavailable")
  const response_is_structured_fault =
    response.status === 502 &&
    response_body_is_valid_json &&
    parsed_response_body !== null &&
    parsed_response_body.error !== undefined &&
    parsed_response_body.error !== null &&
    parsed_response_body.error.code === "upstream_service_unavailable";

  // Record phase-specific metrics and run phase-specific checks
  if (current_phase_number === 1) {
    number_of_requests_during_phase_1.add(1);
    rate_of_successful_responses_during_phase_1.add(response_is_successful);
    duration_of_response_during_phase_1_in_milliseconds.add(
      response.timings.duration
    );

    check(response, {
      "[Phase 1] HTTP status is 200": (response_object) =>
        response_object.status === 200,
      "[Phase 1] response body is valid JSON": () =>
        response_body_is_valid_json,
      "[Phase 1] response contains enhanced_prompt field": () =>
        response_is_successful,
    });
  } else if (current_phase_number === 2) {
    number_of_requests_during_phase_2.add(1);
    rate_of_responses_with_valid_json_during_phase_2.add(
      response_body_is_valid_json
    );
    rate_of_responses_within_timeout_during_phase_2.add(
      response.timings.duration <= 10000
    );
    rate_of_non_500_responses_during_phase_2.add(
      response.status !== 500
    );
    rate_of_structured_fault_responses_during_phase_2.add(
      response_is_structured_fault
    );
    duration_of_response_during_phase_2_in_milliseconds.add(
      response.timings.duration
    );

    check(response, {
      "[Phase 2] HTTP status is 200 or 502": (response_object) =>
        response_object.status === 200 || response_object.status === 502,
      "[Phase 2] HTTP status is not 500": (response_object) =>
        response_object.status !== 500,
      "[Phase 2] response body is valid JSON": () =>
        response_body_is_valid_json,
      "[Phase 2] response received within 10 seconds": () =>
        response.timings.duration <= 10000,
      "[Phase 2] structured fault response (502 with upstream_service_unavailable)": () =>
        response_is_structured_fault,
    });
  } else if (current_phase_number === 3) {
    number_of_requests_during_phase_3.add(1);
    rate_of_successful_responses_during_phase_3.add(response_is_successful);
    duration_of_response_during_phase_3_in_milliseconds.add(
      response.timings.duration
    );

    // Track success rate specifically for requests after the 30-second
    // recovery window (from minute 7:30 onward)
    const request_is_after_recovery_window =
      elapsed_time_in_milliseconds >=
      end_of_recovery_window_in_phase_3_in_milliseconds;

    if (request_is_after_recovery_window) {
      rate_of_successful_responses_after_recovery_window.add(
        response_is_successful
      );
    }

    check(response, {
      "[Phase 3] response body is valid JSON": () =>
        response_body_is_valid_json,
      "[Phase 3] HTTP status is 200 (after recovery)": (response_object) =>
        response_object.status === 200,
      "[Phase 3] response contains enhanced_prompt field": () =>
        response_is_successful,
    });
  }
}

// ---------------------------------------------------------------------------
// Summary output
// ---------------------------------------------------------------------------

/**
 * Generates a human-readable summary of the load test results,
 * partitioned by phase as required by the RO8 step-by-step execution
 * procedure (steps 8-9): For each phase, compute total requests,
 * HTTP 200 count, HTTP 502 count, other error counts, and 95th
 * percentile latency.
 */
export function handleSummary(data) {
  const number_of_requests_in_phase_1 =
    data.metrics.number_of_requests_during_phase_1
      ? data.metrics.number_of_requests_during_phase_1.values.count
      : 0;

  const number_of_requests_in_phase_2 =
    data.metrics.number_of_requests_during_phase_2
      ? data.metrics.number_of_requests_during_phase_2.values.count
      : 0;

  const number_of_requests_in_phase_3 =
    data.metrics.number_of_requests_during_phase_3
      ? data.metrics.number_of_requests_during_phase_3.values.count
      : 0;

  const total_number_of_requests =
    number_of_requests_in_phase_1 +
    number_of_requests_in_phase_2 +
    number_of_requests_in_phase_3;

  // Phase 1 metrics
  const phase_1_success_rate =
    data.metrics.rate_of_successful_responses_during_phase_1
      ? data.metrics.rate_of_successful_responses_during_phase_1.values.rate
      : 0;

  const phase_1_duration_metrics =
    data.metrics.duration_of_response_during_phase_1_in_milliseconds
      ? data.metrics.duration_of_response_during_phase_1_in_milliseconds.values
      : {};

  // Phase 2 metrics
  const phase_2_structured_fault_rate =
    data.metrics.rate_of_structured_fault_responses_during_phase_2
      ? data.metrics.rate_of_structured_fault_responses_during_phase_2.values.rate
      : 0;

  const phase_2_json_validity_rate =
    data.metrics.rate_of_responses_with_valid_json_during_phase_2
      ? data.metrics.rate_of_responses_with_valid_json_during_phase_2.values.rate
      : 0;

  const phase_2_within_timeout_rate =
    data.metrics.rate_of_responses_within_timeout_during_phase_2
      ? data.metrics.rate_of_responses_within_timeout_during_phase_2.values.rate
      : 0;

  const phase_2_non_500_rate =
    data.metrics.rate_of_non_500_responses_during_phase_2
      ? data.metrics.rate_of_non_500_responses_during_phase_2.values.rate
      : 0;

  const phase_2_duration_metrics =
    data.metrics.duration_of_response_during_phase_2_in_milliseconds
      ? data.metrics.duration_of_response_during_phase_2_in_milliseconds.values
      : {};

  // Phase 3 metrics
  const phase_3_success_rate =
    data.metrics.rate_of_successful_responses_during_phase_3
      ? data.metrics.rate_of_successful_responses_during_phase_3.values.rate
      : 0;

  const phase_3_post_recovery_success_rate =
    data.metrics.rate_of_successful_responses_after_recovery_window
      ? data.metrics.rate_of_successful_responses_after_recovery_window.values.rate
      : 0;

  const phase_3_duration_metrics =
    data.metrics.duration_of_response_during_phase_3_in_milliseconds
      ? data.metrics.duration_of_response_during_phase_3_in_milliseconds.values
      : {};

  const format_milliseconds = function (value) {
    return value !== undefined && value !== null
      ? value.toFixed(2)
      : "N/A";
  };

  const summary_text = `
================================================================================
  RO8 — Fault Injection Under Concurrent Load — Test Summary
================================================================================

  Total number of requests across all phases:  ${total_number_of_requests}

  --------------------------------------------------------------------------
  Phase 1 — Normal Operation (minutes 0-3)
  --------------------------------------------------------------------------
  Number of requests:                          ${number_of_requests_in_phase_1}
  Rate of successful responses:                ${(phase_1_success_rate * 100).toFixed(2)}%
  95th percentile latency (ms):                ${format_milliseconds(phase_1_duration_metrics["p(95)"])}
  Maximum latency (ms):                        ${format_milliseconds(phase_1_duration_metrics.max)}

  Threshold Results:
    Success rate >= 95%:                       ${phase_1_success_rate >= 0.95 ? "PASS" : "FAIL"}
    p95 latency <= 30 seconds:                 ${phase_1_duration_metrics["p(95)"] && phase_1_duration_metrics["p(95)"] < 30000 ? "PASS" : "FAIL"}

  --------------------------------------------------------------------------
  Phase 2 — Fault Active (minutes 3-7)
  --------------------------------------------------------------------------
  Number of requests:                          ${number_of_requests_in_phase_2}
  Rate of structured fault responses (502):    ${(phase_2_structured_fault_rate * 100).toFixed(2)}%
  Rate of valid JSON responses:                ${(phase_2_json_validity_rate * 100).toFixed(2)}%
  Rate of responses within 10 seconds:         ${(phase_2_within_timeout_rate * 100).toFixed(2)}%
  Rate of non-500 responses:                   ${(phase_2_non_500_rate * 100).toFixed(2)}%
  95th percentile latency (ms):                ${format_milliseconds(phase_2_duration_metrics["p(95)"])}
  Maximum latency (ms):                        ${format_milliseconds(phase_2_duration_metrics.max)}

  Threshold Results:
    Structured fault rate >= 95%:              ${phase_2_structured_fault_rate >= 0.95 ? "PASS" : "FAIL"}
    All responses are valid JSON:              ${phase_2_json_validity_rate >= 1.0 ? "PASS" : "FAIL"}
    All responses within 10 seconds:           ${phase_2_within_timeout_rate >= 1.0 ? "PASS" : "FAIL"}
    No HTTP 500 responses:                     ${phase_2_non_500_rate >= 1.0 ? "PASS" : "FAIL"}

  --------------------------------------------------------------------------
  Phase 3 — Recovery (minutes 7-10)
  --------------------------------------------------------------------------
  Number of requests:                          ${number_of_requests_in_phase_3}
  Rate of successful responses (all):          ${(phase_3_success_rate * 100).toFixed(2)}%
  Rate of successful responses (after
    30-second recovery window):                ${(phase_3_post_recovery_success_rate * 100).toFixed(2)}%
  95th percentile latency (ms):                ${format_milliseconds(phase_3_duration_metrics["p(95)"])}
  Maximum latency (ms):                        ${format_milliseconds(phase_3_duration_metrics.max)}

  Threshold Results:
    Post-recovery success rate >= 95%:         ${phase_3_post_recovery_success_rate >= 0.95 ? "PASS" : "FAIL"}

  --------------------------------------------------------------------------
  Cross-Phase Results
  --------------------------------------------------------------------------
  All responses across all phases are
    valid JSON:                                ${data.metrics.rate_of_valid_json_responses_across_all_phases && data.metrics.rate_of_valid_json_responses_across_all_phases.values.rate >= 1.0 ? "PASS" : "FAIL"}

================================================================================
`;

  return {
    stdout: summary_text,
    "tests/load/summary_of_fault_injection_load_test.json": JSON.stringify(
      data,
      null,
      2
    ),
  };
}
