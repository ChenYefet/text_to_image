/**
 * k6 Load Test Script for RO7 — Concurrent Load: Prompt Enhancement
 *
 * This script implements the RO7 reference operation as defined in the
 * Text-to-Image specification (v5.2.1). It measures prompt enhancement
 * performance under sustained concurrent load by having 5 virtual users
 * continuously issue POST /v1/prompts/enhance requests back-to-back for
 * 5 minutes.
 *
 * Success criteria (from NFR1 — Latency of prompt enhancement under
 * concurrent load):
 *   - At least 95% of all requests return HTTP 200 with a syntactically
 *     valid JSON response body containing a valid "enhanced_prompt" field
 *   - The 95th percentile latency across all requests is <= 30 seconds
 *   - The maximum latency across all requests is <= 60 seconds
 *   - No request returns a non-JSON response body
 *
 * Usage:
 *   k6 run tests/load/k6_prompt_enhancement.js
 *   k6 run --env BASE_URL=http://localhost:8000 tests/load/k6_prompt_enhancement.js
 */

import http from "k6/http";
import { check } from "k6";
import { Rate, Trend } from "k6/metrics";

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

/**
 * Tracks the rate of successful requests (HTTP 200 with valid
 * enhanced_prompt field in the JSON response body).
 */
const rate_of_successful_responses = new Rate(
  "rate_of_successful_responses"
);

/**
 * Tracks the rate of responses that contain a valid JSON body,
 * regardless of HTTP status code.
 */
const rate_of_valid_json_responses = new Rate(
  "rate_of_valid_json_responses"
);

/**
 * Records the response duration (in milliseconds) for every request,
 * used to compute aggregate latency statistics in the summary output.
 */
const duration_of_response_in_milliseconds = new Trend(
  "duration_of_response_in_milliseconds"
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
 * A pool of 20 unique natural language prompts with lengths uniformly
 * distributed between 10 and 500 characters, as required by the RO7
 * specification. Each virtual user randomly selects a prompt from this
 * pool for every request.
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
// k6 test configuration
// ---------------------------------------------------------------------------

export const options = {
  /**
   * 5 concurrent virtual users for a sustained duration of 5 minutes,
   * as specified by RO7. Each virtual user issues requests back-to-back
   * with no think time between requests.
   */
  vus: 5,
  duration: "5m",

  /**
   * Automated pass/fail thresholds derived from the NFR1 success
   * criteria in the specification:
   *
   *   - rate_of_successful_responses >= 95%
   *   - 95th percentile of response duration <= 30 seconds (30000 ms)
   *   - Maximum response duration <= 60 seconds (60000 ms)
   *   - rate_of_valid_json_responses == 100% (no non-JSON responses)
   */
  thresholds: {
    rate_of_successful_responses: ["rate>=0.95"],
    "duration_of_response_in_milliseconds": [
      "p(95)<30000",
      "max<60000",
    ],
    rate_of_valid_json_responses: ["rate>=1.0"],
  },
};

// ---------------------------------------------------------------------------
// HTTP request headers
// ---------------------------------------------------------------------------

const headers_for_request = {
  "Content-Type": "application/json",
};

// ---------------------------------------------------------------------------
// Virtual user iteration (default function)
// ---------------------------------------------------------------------------

/**
 * Each virtual user executes this function repeatedly for the full
 * duration of the test. On each iteration, the virtual user selects a
 * random prompt from the pool and issues a POST request to the prompt
 * enhancement endpoint. There is no sleep or think time between
 * iterations, so requests are issued back-to-back as required by RO7.
 */
export default function () {
  // Select a random prompt from the pool for this request
  const index_of_selected_prompt = Math.floor(
    Math.random() * pool_of_unique_prompts.length
  );
  const selected_prompt = pool_of_unique_prompts[index_of_selected_prompt];

  // Construct the request body per the prompt enhancement request schema:
  // { "prompt": "<string>" }
  const body_of_request = JSON.stringify({
    prompt: selected_prompt,
  });

  // Issue the POST request to the prompt enhancement endpoint
  const response = http.post(
    `${base_url_of_service}/v1/prompts/enhance`,
    body_of_request,
    { headers: headers_for_request }
  );

  // Record the response duration in the custom trend metric
  duration_of_response_in_milliseconds.add(response.timings.duration);

  // Attempt to parse the response body as JSON
  let parsed_response_body = null;
  let response_body_is_valid_json = false;
  try {
    parsed_response_body = response.json();
    response_body_is_valid_json = true;
  } catch (parse_error) {
    response_body_is_valid_json = false;
  }

  // Track whether the response body is valid JSON
  rate_of_valid_json_responses.add(response_body_is_valid_json);

  // Determine whether this is a fully successful response:
  // HTTP 200 with a JSON body containing a non-empty "enhanced_prompt" field
  const response_is_successful =
    response.status === 200 &&
    response_body_is_valid_json &&
    parsed_response_body !== null &&
    typeof parsed_response_body.enhanced_prompt === "string" &&
    parsed_response_body.enhanced_prompt.length > 0;

  rate_of_successful_responses.add(response_is_successful);

  // Run k6 checks for per-request assertion reporting
  check(response, {
    "HTTP status is 200": (response_object) =>
      response_object.status === 200,
    "response body is valid JSON": () => response_body_is_valid_json,
    "response contains enhanced_prompt field": () =>
      parsed_response_body !== null &&
      typeof parsed_response_body.enhanced_prompt === "string" &&
      parsed_response_body.enhanced_prompt.length > 0,
    "response contains original_prompt field": () =>
      parsed_response_body !== null &&
      typeof parsed_response_body.original_prompt === "string",
    "response contains created field": () =>
      parsed_response_body !== null &&
      typeof parsed_response_body.created === "number" &&
      Number.isInteger(parsed_response_body.created),
  });
}

// ---------------------------------------------------------------------------
// Summary output
// ---------------------------------------------------------------------------

/**
 * Generates a human-readable summary of the load test results,
 * including aggregate statistics as required by the RO7 step-by-step
 * execution procedure (step 6): total requests completed, HTTP 200
 * count, error count, median latency, 95th percentile latency, and
 * maximum latency.
 */
export function handleSummary(data) {
  const total_number_of_requests =
    data.metrics.http_reqs ? data.metrics.http_reqs.values.count : 0;

  const number_of_successful_responses =
    data.metrics.rate_of_successful_responses
      ? Math.round(
          data.metrics.rate_of_successful_responses.values.rate *
            total_number_of_requests
        )
      : 0;

  const number_of_failed_responses =
    total_number_of_requests - number_of_successful_responses;

  const duration_metrics =
    data.metrics.duration_of_response_in_milliseconds
      ? data.metrics.duration_of_response_in_milliseconds.values
      : {};

  const summary_text = `
================================================================================
  RO7 — Concurrent Load: Prompt Enhancement — Test Summary
================================================================================

  Total number of requests completed:  ${total_number_of_requests}
  Number of successful responses:      ${number_of_successful_responses}
  Number of failed responses:          ${number_of_failed_responses}
  Rate of successful responses:        ${
    data.metrics.rate_of_successful_responses
      ? (data.metrics.rate_of_successful_responses.values.rate * 100).toFixed(2)
      : "N/A"
  }%

  Latency Statistics (milliseconds):
    Median (p50):                      ${
      duration_metrics["p(50)"]
        ? duration_metrics["p(50)"].toFixed(2)
        : "N/A"
    }
    90th percentile (p90):             ${
      duration_metrics["p(90)"]
        ? duration_metrics["p(90)"].toFixed(2)
        : "N/A"
    }
    95th percentile (p95):             ${
      duration_metrics["p(95)"]
        ? duration_metrics["p(95)"].toFixed(2)
        : "N/A"
    }
    Maximum:                           ${
      duration_metrics.max
        ? duration_metrics.max.toFixed(2)
        : "N/A"
    }

  Threshold Results:
    p95 latency <= 30 seconds:         ${
      duration_metrics["p(95)"] && duration_metrics["p(95)"] < 30000
        ? "PASS"
        : "FAIL"
    }
    Maximum latency <= 60 seconds:     ${
      duration_metrics.max && duration_metrics.max < 60000
        ? "PASS"
        : "FAIL"
    }
    Success rate >= 95%:               ${
      data.metrics.rate_of_successful_responses &&
      data.metrics.rate_of_successful_responses.values.rate >= 0.95
        ? "PASS"
        : "FAIL"
    }
    All responses are valid JSON:      ${
      data.metrics.rate_of_valid_json_responses &&
      data.metrics.rate_of_valid_json_responses.values.rate >= 1.0
        ? "PASS"
        : "FAIL"
    }

================================================================================
`;

  return {
    stdout: summary_text,
    "tests/load/summary_of_prompt_enhancement_load_test.json": JSON.stringify(
      data,
      null,
      2
    ),
  };
}
