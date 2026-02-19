# Technical Specification: Text-to-Image Generation Service with Prompt Enhancement

**Document Version:** 3.2.0
**Status:** Final — Panel Review Ready
**Target Audience:** Senior Engineering Panel, Implementation Teams
**Specification Authority:** Principal Technical Specification Authority
**Date:** 19 February 2026

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Glossary and Terminology](#glossary-and-terminology)
3. [System Overview](#system-overview)
4. [Architectural Principles](#architectural-principles)
5. [Reference Operations](#reference-operations)
6. [Requirements](#requirements)
   a. [Non-Functional Requirements](#non-functional-requirements)
      i. [Performance and Latency](#performance-and-latency)
      ii. [Scalability](#scalability)
      iii. [Reliability and Fault Tolerance](#reliability-and-fault-tolerance)
      iv. [Observability](#observability)
      v. [Security](#security)
      vi. [API Contract and Stability](#api-contract-and-stability)
   b. [Functional Requirements](#functional-requirements)
      i. [Prompt Enhancement](#prompt-enhancement)
      ii. [Image Generation](#image-generation)
      iii. [Request Validation and Error Handling](#request-validation-and-error-handling)
      iv. [Correlation and Tracing](#correlation-and-tracing)
      v. [Health and Readiness](#health-and-readiness)
      vi. [Configuration-Driven Behaviour](#configuration-driven-behaviour)
7. [Requirements Traceability Matrix](#requirements-traceability-matrix)
8. [New Requirement Categorisation Guide](#new-requirement-categorisation-guide)
9. [New Requirement Section Creation Guide](#new-requirement-section-creation-guide)
10. [Data Model and Schema Definition](#data-model-and-schema-definition)
11. [API Contract Definition](#api-contract-definition)
12. [Technology Stack and Justification](#technology-stack-and-justification)
13. [Component Architecture and Responsibilities](#component-architecture-and-responsibilities)
14. [Model Integration Specifications](#model-integration-specifications)
15. [Error Handling and Recovery](#error-handling-and-recovery)
16. [Configuration Requirements](#configuration-requirements)
17. [Logging and Observability](#logging-and-observability)
18. [Security Considerations](#security-considerations)
19. [Scalability and Future Extension Considerations](#scalability-and-future-extension-considerations)
20. [Infrastructure Definition](#infrastructure-definition)
21. [CI/CD Pipeline Requirements](#cicd-pipeline-requirements)
22. [Testing Requirements](#testing-requirements)
23. [Specification Governance and Evolution](#specification-governance-and-evolution)
24. [README (Implementation and Execution Guide)](#readme-implementation-and-execution-guide)
25. [Appendices](#appendices)

---

## Executive Summary

This document constitutes a complete, implementation-ready technical specification for a Text-to-Image Generation Service with integrated Prompt Enhancement capabilities. The system integrates two distinct machine learning inference engines — llama.cpp for natural language prompt enhancement and Stable Diffusion for image synthesis — exposed through a unified, RESTful HTTP API contract.

The service architecture prioritises horizontal scalability, operational observability, deterministic error handling, and extensibility to support future multi-model orchestration scenarios. All architectural decisions have been explicitly justified for production deployment at enterprise scale.

This specification is designed for evaluation by a hiring panel assessing a candidate's ability to design, document, implement, deploy, and operate distributed systems with machine learning inference components. Every requirement includes an explicit intent, a detailed test procedure with step-by-step instructions executable by an independent reviewer without deep domain knowledge, and measurable success criteria.

### Key Architectural Characteristics

- **Service pattern:** Synchronous REST API with blocking inference execution
- **Model integration:** Process-based isolation for llama.cpp; library-based integration for Stable Diffusion
- **Error handling:** Deterministic HTTP status code mapping with structured error responses
- **Scalability model:** Horizontal scaling with stateless service instances
- **Observability:** Structured JSON logging with correlation identifiers and inference telemetry
- **Deployment model:** Containerised deployment with Kubernetes orchestration support
- **Infrastructure:** Infrastructure-as-code using Kubernetes manifests

### Document Structure

This specification follows a layered structure designed to serve multiple audiences:

- **Sections 1–4:** Executive overview, glossary, and architectural foundations (for technical leadership)
- **Sections 5–9:** Reference operations, testable requirements with verification procedures, and traceability (for implementation teams and evaluators)
- **Sections 10–18:** Detailed technical specifications (for developers and DevOps teams)
- **Sections 19–22:** Infrastructure, CI/CD, and testing (for platform teams)
- **Sections 23–25:** Governance, README, and appendices (for all audiences)

---

## Glossary and Terminology

This section defines all key terms used throughout this specification to ensure unambiguous interpretation by all readers, including reviewers without deep domain expertise. Terms are listed in alphabetical order and shall be interpreted as defined here whenever they appear in this document.

| Term | Definition |
|------|-----------|
| **Base64-encoded image payload** | A PNG image that has been encoded using the base64 encoding scheme and embedded as a string field (`b64_json`) inside a JSON response document. |
| **Correlation identifier** | A UUID v4 value generated by the Text-to-Image API Service for each incoming HTTP request and propagated via the `X-Correlation-ID` response header, error response payloads, and structured log entries, enabling end-to-end request tracing. |
| **Enhanced prompt** | The output of the prompt enhancement process: a natural language description enriched with artistic style, lighting, composition, and quality modifiers, optimised for Stable Diffusion inference. |
| **Functional requirement (FR)** | A numbered requirement (FR1, FR2, …) describing observable behaviour of the service from the perspective of an external client or operator. |
| **Horizontal scaling** | Increasing overall system capacity by deploying additional stateless service instances behind a load balancer without modifying application code or requiring coordination between instances. |
| **Inference** | The process by which a machine learning model produces an output (text completion or image) from a given input (prompt). |
| **llama.cpp server** | An external process running the llama.cpp binary, compiled for CPU-only execution, exposing an OpenAI-compatible HTTP API for natural language prompt enhancement. |
| **Local environment** | A development or evaluation setup in which both the Text-to-Image API Service and its dependencies run on `localhost` or within a single machine, without exposure to untrusted networks. |
| **Non-functional requirement (NFR)** | A numbered requirement (NFR1, NFR2, …) describing a quality attribute such as performance, scalability, observability, reliability, or security. |
| **Prompt** | A natural language text description provided by a client as input to the service, describing the desired image content or the text to be enhanced. |
| **Reference operation (RO)** | A self-contained, numbered, executable test scenario (RO1, RO2, …) defined in the Reference Operations section, each with explicit preconditions, step-by-step test instructions, and success criteria. Reference operations serve as the primary verification mechanism for requirements. |
| **Stable Diffusion inference engine** | The in-process image generation component, implemented using the Hugging Face Diffusers library, that converts text prompts into PNG images. |
| **Stateless service instance** | A running copy of the Text-to-Image API Service that does not retain user-specific or request-specific state between HTTP requests. |
| **Structured log entry** | A log record emitted in JSON format containing machine-readable fields including, at minimum, a timestamp, log level, event name, correlation identifier, and service name. |
| **Text-to-Image API Service** | The HTTP service specified in this document that exposes the `/v1/prompts/enhance` and `/v1/images/generations` endpoints and orchestrates llama.cpp and Stable Diffusion. Also referred to as "the service" throughout this specification. |
| **Transient fault** | A temporary failure condition — such as a network timeout, connection reset, or brief service unavailability — that is expected to resolve without manual intervention and does not indicate a persistent system defect. |
| **Upstream service** | Any dependency that the Text-to-Image API Service calls during request processing, specifically the llama.cpp server and the Stable Diffusion inference engine. |

---

## System Overview

### Purpose and Scope

The Text-to-Image Generation Service provides programmatic access to AI-powered image synthesis capabilities with optional intelligent prompt enhancement. The service accepts natural language descriptions of desired images, optionally enhances these descriptions using a large language model, and generates corresponding visual outputs using a diffusion-based image generation model.

#### Primary Use Cases

1. Direct image generation from user-provided natural language prompts
2. Enhanced image generation where prompts are refined for optimal visual output quality
3. Batch generation of multiple images from a single enhanced or unenhanced prompt

#### Out of Scope

- Image-to-image transformation
- Inpainting or outpainting operations
- Real-time streaming of generation progress
- User authentication or authorisation (assumed to be handled by an upstream API gateway)
- Persistent storage of generated images beyond response delivery
- Rate limiting or quota enforcement (assumed to be handled by an upstream API gateway)

### System Context and Architecture

The service operates as a containerised HTTP API server. It orchestrates two separate machine learning inference engines:

1. **llama.cpp HTTP server:** Executed as an external process (or separate Kubernetes pod) exposing an OpenAI-compatible chat completion endpoint for prompt enhancement. CPU-only execution is mandated.
2. **Stable Diffusion inference engine:** Integrated as an in-process library within the service for image generation.

#### High-Level Architecture (Textual Description)

The system comprises three principal runtime components arranged in a request-flow topology:

1. **Ingress layer:** An external client (for example, `curl`) sends HTTP requests to the Text-to-Image API Service on its configured port (default: 8000).

2. **Text-to-Image API Service:** Receives HTTP requests, validates input against JSON schemas, orchestrates model inference, and returns JSON responses. This service contains three internal layers:
   - *HTTP API layer:* Request parsing, validation, response serialisation, correlation identifier injection, and global exception handling.
   - *Application service layer:* Business logic orchestration, workflow coordination (enhancement followed by generation when `use_enhancer` is `true`), and error recovery.
   - *Model integration layer:* HTTP client for llama.cpp communication and Diffusers pipeline wrapper for Stable Diffusion inference.

3. **llama.cpp HTTP server:** A separate process listening on its own port (default: 8080), loaded with an instruction-tuned language model in GGUF format. The Text-to-Image API Service communicates with this server over HTTP using the OpenAI-compatible `/v1/chat/completions` endpoint.

Data flows unidirectionally from the ingress layer through the Text-to-Image API Service to the upstream inference engines. No persistent state is shared between requests. No inter-instance coordination is required.

### System Boundaries

**Internal responsibilities:**
- HTTP request validation and deserialisation
- Orchestration of prompt enhancement workflow
- Orchestration of image generation workflow
- Error classification and HTTP status code mapping
- Response serialisation to JSON
- Structured logging of operations and inference telemetry

**External dependencies:**
- llama.cpp HTTP server process (deployed as a separate process or Kubernetes pod)
- Stable Diffusion model files (must be pre-downloaded and accessible via local filesystem or persistent volume)
- Python runtime environment with required dependencies

**Explicit non-responsibilities:**
- Model file acquisition or version management (handled by deployment process)
- Process supervision of llama.cpp server (handled by the operating system, container runtime, or Kubernetes)
- Image persistence beyond HTTP response delivery
- Client authentication or authorisation (handled by upstream API gateway)
- TLS termination (handled by ingress controller or reverse proxy)

---

## Architectural Principles

The service architecture adheres to the following foundational principles. Each principle includes explicit justification, implementation implications, and verification criteria.

### Principle 1: Statelessness and Horizontal Scalability

**Statement:** The service shall maintain no session state, user context, or request history between invocations. Each HTTP request shall be processed independently with no reliance on prior interactions.

**Justification:** Statelessness enables horizontal scaling through load balancer distribution. Multiple service instances can operate concurrently without coordination, shared storage, or distributed consensus mechanisms. This architectural property is essential for handling variable request rates and provides linear scalability characteristics.

**Implementation implications:**
- Service instances are fungible and interchangeable
- No session affinity requirements for load balancing
- Graceful degradation under partial instance failure
- Simplified deployment and rollback procedures
- Easy auto-scaling based on resource utilisation

**Verification:** Verified via NFR3 (Horizontal Scaling Support).

### Principle 2: Service Boundary Clarity

**Statement:** Despite deployment as a monolithic application, the service shall maintain clear internal boundaries between the HTTP API layer, application orchestration layer, and model integration layer.

**Justification:** Explicit service boundaries facilitate future decomposition into microservices without requiring fundamental architectural redesign. Clear separation of concerns enables independent testing, modification, and potential extraction of components as organisational scaling demands evolve.

**Implementation implications:**
- Each layer communicates through defined interfaces
- Dependencies flow unidirectionally (API → Application → Integration)
- Model integration clients are replaceable without API contract modification
- Future service extraction requires interface formalisation, not code restructuring
- Testing can be performed at each layer independently

### Principle 3: Deterministic Error Semantics

**Statement:** All error conditions shall map to specific, well-defined HTTP status codes with structured error response bodies containing machine-readable error identifiers and human-readable descriptions.

**Justification:** Deterministic error handling enables reliable client-side retry logic, monitoring alerting rules, and operational troubleshooting. Ambiguity in error semantics creates operational blind spots and degrades system observability.

**Error classification taxonomy:**

| HTTP Status | Category | Retry Behaviour | Client Action |
|-------------|----------|-----------------|---------------|
| 400 | Client error | Never retry | Fix request and resubmit |
| 502 | Upstream failure | Retry with exponential backoff | Wait and retry |
| 500 | Internal error | Retry with exponential backoff | Wait and retry; escalate if persistent |

**Verification:** Verified via FR5, FR6, FR7, FR8, and FR14.

### Principle 4: Observability by Default

**Statement:** All significant operations — HTTP requests, model inference invocations, errors, and performance metrics — shall be logged in structured JSON format suitable for aggregation and analysis.

**Justification:** Production systems cannot be effectively operated without comprehensive observability. Structured logging enables rapid incident diagnosis, performance regression detection, and capacity planning based on empirical metrics.

**Verification:** Verified via NFR5 (Structured Logging) and NFR7 (Performance Metrics Collection).

### Principle 5: Fail-Fast Validation

**Statement:** Request validation shall occur at the earliest possible point in the request processing pipeline, immediately rejecting malformed or semantically invalid requests before consuming inference resources.

**Justification:** Early validation reduces computational waste, improves error response latency, and prevents invalid data from propagating through the system. Fast failure provides superior client experience through reduced wait times for malformed requests.

**Verification:** Verified via FR5 and FR4.

### Principle 6: External Process Isolation

**Statement:** llama.cpp shall execute as an independent HTTP server process, isolated from the primary service process space.

**Justification:** Process isolation prevents model inference crashes from terminating the HTTP API service. Memory leaks, segmentation faults, or resource exhaustion in the inference engine do not compromise API availability. This separation also enables independent scaling, versioning, and resource allocation for the language model inference workload.

**Verification:** Verified via FR6 and FR14.

---

## Reference Operations

Reference operations (ROs) are precise, repeatable operations that the system must support, defined to ensure that all requirements in this specification can be verified objectively and reproduced by independent reviewers. Each RO specifies the type of request or operation, the expected input and output, and the conditions under which it is executed.

All non-functional and functional requirements that specify what the system does, how much load it handles, when and how it executes, or how success is measured, shall reference one or more of these operations.

### RO1 — Prompt Enhancement

#### Description

RO1 is a request where a client submits a short natural language prompt to the prompt enhancement endpoint and receives an enhanced, visually descriptive prompt in return.

#### Purpose

To measure baseline prompt enhancement performance and verify correct integration with the llama.cpp server.

#### Execution Details

- **Endpoint:** `POST /v1/prompts/enhance`
- **Request body:** `{"prompt": "a cat sitting on a windowsill"}`
- **Expected response status:** HTTP 200
- **Expected response body field:** `enhanced_prompt` (string, length ≥ 50 characters)
- **Response format:** JSON
- **Required response headers:** `Content-Type: application/json`, `X-Correlation-ID: {uuid-v4}`

#### Step-by-Step Execution Procedure

1. Open a terminal with `curl` installed.
2. Execute the following command:

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}\n" \
  -X POST http://localhost:8000/v1/prompts/enhance \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a cat sitting on a windowsill"}'
```

3. Record the HTTP status code printed after `HTTP_STATUS:`.
4. Copy the JSON response body (all text before the `HTTP_STATUS:` line).
5. Verify the JSON response body is parseable using any JSON parser (for example, pipe the output through `jq .`).
6. Extract the value of the `enhanced_prompt` field from the parsed JSON.
7. Measure the character length of the `enhanced_prompt` value.

### RO2 — Image Generation Without Enhancement

#### Description

RO2 is a request where a client submits a detailed prompt directly to the image generation endpoint with `use_enhancer` set to `false`, requesting a single 512×512 image.

#### Purpose

To measure baseline image generation performance and verify correct Stable Diffusion integration without the prompt enhancement step.

#### Execution Details

- **Endpoint:** `POST /v1/images/generations`
- **Request body:**
```json
{
  "prompt": "a serene mountain landscape at sunset, vibrant colours, photorealistic",
  "use_enhancer": false,
  "n": 1,
  "size": "512x512"
}
```
- **Expected response status:** HTTP 200
- **Expected response body fields:** `created` (integer, Unix timestamp), `data` (array of exactly 1 element, each containing `b64_json`)
- **Response format:** JSON
- **Required response headers:** `Content-Type: application/json`, `X-Correlation-ID: {uuid-v4}`

#### Step-by-Step Execution Procedure

1. Open a terminal with `curl`, `jq`, and `base64` installed.
2. Execute the following command:

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}\n" \
  -X POST http://localhost:8000/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "a serene mountain landscape at sunset, vibrant colours, photorealistic",
    "use_enhancer": false,
    "n": 1,
    "size": "512x512"
  }' -o response_ro2.json
```

3. Record the HTTP status code.
4. Parse the response file: `cat response_ro2.json | jq .`
5. Verify the `created` field is an integer.
6. Verify the `data` array contains exactly 1 element.
7. Decode the first image: `cat response_ro2.json | jq -r '.data[0].b64_json' | base64 -d > image_ro2.png`
8. Verify the file is a valid PNG: `file image_ro2.png` (expected output contains "PNG image data").
9. Verify image dimensions: `identify image_ro2.png` or equivalent tool (expected: 512×512 pixels).
10. Verify file size: `ls -l image_ro2.png` (expected: file size > 1024 bytes).

### RO3 — Image Generation With Enhancement

#### Description

RO3 is a request where a client submits a brief prompt to the image generation endpoint with `use_enhancer` set to `true`, requesting two 512×512 images. The service must first enhance the prompt via llama.cpp, then generate images using the enhanced prompt.

#### Purpose

To verify the end-to-end workflow combining prompt enhancement and image generation, and to measure combined latency.

#### Execution Details

- **Endpoint:** `POST /v1/images/generations`
- **Request body:**
```json
{
  "prompt": "a futuristic cityscape",
  "use_enhancer": true,
  "n": 2,
  "size": "512x512"
}
```
- **Expected response status:** HTTP 200
- **Expected response body fields:** `created` (integer), `data` (array of exactly 2 elements)
- **Response format:** JSON
- **Required response headers:** `Content-Type: application/json`, `X-Correlation-ID: {uuid-v4}`

#### Step-by-Step Execution Procedure

1. Open a terminal with `curl`, `jq`, and `base64` installed.
2. Execute the following command:

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}\nTOTAL_TIME:%{time_total}\n" \
  -X POST http://localhost:8000/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "a futuristic cityscape",
    "use_enhancer": true,
    "n": 2,
    "size": "512x512"
  }' -o response_ro3.json
```

3. Record the HTTP status code and total request time.
4. Parse the response: `cat response_ro3.json | jq .`
5. Verify the `data` array contains exactly 2 elements.
6. Decode both images:

```bash
cat response_ro3.json | jq -r '.data[0].b64_json' | base64 -d > image_ro3_1.png
cat response_ro3.json | jq -r '.data[1].b64_json' | base64 -d > image_ro3_2.png
```

7. Verify both files are valid PNGs with dimensions of exactly 512×512 pixels.
8. Verify both file sizes are > 1024 bytes.
9. Examine the service logs (for example, `docker logs {container_name}` or `kubectl logs {pod_name}`) and verify that the logs contain, in chronological order:
   a. A `prompt_enhancement_initiated` (or equivalent) event.
   b. A `prompt_enhancement_completed` (or equivalent) event showing an enhanced prompt that differs from the original input.
   c. An `image_generation_initiated` (or equivalent) event.
   d. An `image_generation_completed` (or equivalent) event.

### RO4 — Error Handling: Invalid JSON

#### Description

RO4 is a request where a client sends a syntactically malformed JSON body to the prompt enhancement endpoint.

#### Purpose

To verify that the service detects and rejects malformed JSON immediately, returning a structured 400 error response without invoking any model inference.

#### Execution Details

- **Endpoint:** `POST /v1/prompts/enhance`
- **Request body (malformed):** `{"prompt": "test"`  (missing closing brace)
- **Expected response status:** HTTP 400
- **Expected error code:** `invalid_request_json`

#### Step-by-Step Execution Procedure

1. Execute the following command:

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}\nTOTAL_TIME:%{time_total}\n" \
  -X POST http://localhost:8000/v1/prompts/enhance \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test"'
```

2. Record the HTTP status code (expected: 400).
3. Record the total request time (expected: < 1 second).
4. Parse the response body using a JSON parser.
5. Verify the response body contains an `error` object.
6. Verify the `error` object contains the fields: `code`, `message`, `correlation_id`.
7. Verify `error.code` equals `"invalid_request_json"`.
8. Verify `error.correlation_id` is a valid UUID v4 string (format: 8-4-4-4-12 hexadecimal digits separated by hyphens).

### RO5 — Error Handling: llama.cpp Unavailable

#### Description

RO5 is a request where a client sends a valid prompt enhancement request while the llama.cpp server is intentionally stopped.

#### Purpose

To verify that the service returns a 502 response with a structured error when the llama.cpp upstream server is unreachable.

#### Execution Details

- **Endpoint:** `POST /v1/prompts/enhance`
- **Request body:** `{"prompt": "test prompt"}`
- **Precondition:** llama.cpp server is not running
- **Expected response status:** HTTP 502
- **Expected error code:** `upstream_service_unavailable`

#### Step-by-Step Execution Procedure

1. Stop the llama.cpp server process (for example, `kill $(pgrep llama-server)` or `kubectl scale deployment llama-cpp-server --replicas=0`).
2. Verify the llama.cpp server is not responding: `curl http://localhost:8080/health` should fail with "Connection refused" or equivalent.
3. Execute the following command:

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}\nTOTAL_TIME:%{time_total}\n" \
  -X POST http://localhost:8000/v1/prompts/enhance \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test prompt"}'
```

4. Record the HTTP status code (expected: 502).
5. Record the total request time (expected: < 5 seconds; connection-refused errors are detected immediately by the operating system's TCP stack and do not wait for the upstream request timeout to elapse).
6. Parse the response body using a JSON parser.
7. Verify the `error.code` field equals `"upstream_service_unavailable"`.
8. Verify the `error.correlation_id` field is a valid UUID v4.
9. Examine the service logs and verify an ERROR-level entry exists for this request, containing the correlation identifier.

### RO6 — Error Handling: Transient Network Fault (Timeout)

#### Description

RO6 is a request where the service is configured to point to a non-routable llama.cpp endpoint, simulating a network timeout.

#### Purpose

To verify that the service responds within a bounded time when the upstream llama.cpp server is unreachable due to network conditions, rather than hanging indefinitely.

#### Execution Details

- **Endpoint:** `POST /v1/prompts/enhance`
- **Request body:** `{"prompt": "test prompt for timeout behaviour"}`
- **Precondition:** The environment variable `TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL` is set to `http://10.255.255.1:8080` (a non-routable address)
- **Expected response status:** HTTP 502
- **Expected error code:** `upstream_service_unavailable`

#### Step-by-Step Execution Procedure

1. Set the environment variable `TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL` to `http://10.255.255.1:8080`.
2. Restart the Text-to-Image API Service to apply the new configuration.
3. Execute the following command:

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}\nTOTAL_TIME:%{time_total}\n" \
  -X POST http://localhost:8000/v1/prompts/enhance \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test prompt for timeout behaviour"}'
```

4. Record the HTTP status code (expected: 502).
5. Record the total request time in seconds.
6. Verify the total request time is ≤ 125 seconds (the configured upstream timeout of 120 seconds plus up to 5 seconds of processing overhead).
7. Parse the response body and verify `error.code` equals `"upstream_service_unavailable"`.
8. Verify the service remains responsive to other requests by executing: `curl http://localhost:8000/health` (expected: HTTP 200).
9. Examine the service logs and verify an ERROR-level entry exists indicating a timeout or network failure, including the correlation identifier.
10. Restore `TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL` to the correct value and restart the service.

---

## Requirements

### Non-Functional Requirements

The non-functional requirements are specified before functional requirements because they establish the performance, scalability, reliability, observability, security, and stability constraints — defined and measured using the reference operations — that govern the system's functional behaviour.

#### Performance and Latency

**Scope:** Requirements that define how quickly the system responds to requests, including latency bounds for prompt enhancement, image generation, and error responses.

##### Prompt enhancement latency

1. The service shall complete prompt enhancement requests within bounded latency for prompts of up to 2000 characters on CPU-only hardware.

**Intent:** To ensure prompt enhancement provides acceptable response times for interactive use cases whilst acknowledging the computational cost of large language model inference on CPU hardware. Bounding latency enables clients to implement predictable timeout and retry strategies.

**Preconditions:**

- The Text-to-Image API Service is running and accessible at its configured port (recommended verification: `curl http://localhost:8000/health` returns HTTP 200)
- The llama.cpp HTTP server is running and accessible at its configured port (recommended verification: `curl http://localhost:8080/health`)
- The llama.cpp server is loaded with an instruction-tuned language model

**Verification:**

- Test procedure:

    1. Prepare a set of 20 unique natural language prompts with lengths uniformly distributed between 10 and 2000 characters (recommended tool: any text editor)
    2. For each prompt, execute [RO1](#ro1--prompt-enhancement) using the prepared prompt as the `prompt` field value, recording the total request latency using `curl -w "%{time_total}"` (recommended tool: terminal with `curl`)
    3. Collect all 20 latency measurements into a list
    4. Sort the latency measurements in ascending order
    5. Identify the 95th percentile value (the 19th value in the sorted list of 20)

- Success criteria:

    - The 95th percentile latency across all 20 executions is ≤ 30 seconds
    - The maximum latency across all 20 executions is ≤ 60 seconds
    - All 20 requests return HTTP 200 with a valid `enhanced_prompt` field

##### Image generation latency (single image, 512×512)

2. The service shall complete single-image generation requests at 512×512 resolution within bounded latency on CPU hardware with a minimum of 8 GB RAM.

**Intent:** To establish baseline performance expectations for Stable Diffusion inference on CPU, acknowledging that CPU-based image generation is significantly slower than GPU-accelerated alternatives. Bounded latency enables capacity planning and client-side timeout configuration.

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- The Stable Diffusion model has been fully loaded (verify via service startup logs showing successful model initialisation)
- The host system has at least 8 GB of available RAM and at least 4 CPU cores

**Verification:**

- Test procedure:

    1. Prepare a set of 10 unique natural language prompts, each between 20 and 200 characters in length (recommended tool: any text editor)
    2. For each prompt, execute [RO2](#ro2--image-generation-without-enhancement) using the prepared prompt, recording the total request latency using `curl -w "%{time_total}"` (recommended tool: terminal with `curl`)
    3. Collect all 10 latency measurements into a list
    4. Sort the latency measurements in ascending order
    5. Identify the 95th percentile value (the 10th value in the sorted list of 10)

- Success criteria:

    - The 95th percentile latency across all 10 executions is ≤ 60 seconds
    - The maximum latency across all 10 executions is ≤ 90 seconds
    - All 10 requests return HTTP 200 with a valid `data` array containing exactly 1 valid base64-encoded PNG image

##### Validation response latency

3. The service shall respond to requests that fail JSON syntax or schema validation within 1 second.

**Intent:** To ensure that clients submitting malformed or invalid requests receive immediate feedback without waiting for model inference timeouts. Fast validation failure reduces operational noise and client-side timeout confusion.

**Preconditions:**

- The Text-to-Image API Service is running and accessible

**Verification:**

- Test procedure:

    1. Execute [RO4](#ro4--error-handling-invalid-json) and record the total request time using `curl -w "%{time_total}"` (recommended tool: terminal with `curl`)
    2. Execute a request to `POST /v1/images/generations` with a valid JSON body containing an invalid `size` value (for example, `"size": "999x999"`) and record the total request time

- Success criteria:

    - The total request time for each of the two requests is < 1 second
    - Both requests return the expected HTTP 400 response with a structured error body

---

#### Scalability

**Scope:** Requirements that define how the system scales to accommodate increased request volume, including horizontal scaling behaviour and statelessness guarantees.

##### Horizontal scaling support

4. The service shall support horizontal scaling to N concurrent instances without requiring shared state, session affinity, or coordination between instances.

**Intent:** To enable linear capacity scaling by adding service instances behind a load balancer, supporting variable request rates without architectural modifications. Verifying statelessness ensures that any instance can handle any request, which is a prerequisite for effective horizontal scaling.

**Preconditions:**

- At least 2 instances of the Text-to-Image API Service are deployed behind a load balancer or reverse proxy configured for round-robin distribution with no session affinity (recommended tool: Kubernetes with a LoadBalancer Service, or `nginx` with round-robin upstream configuration)
- Each instance is configured identically (same environment variables, same model files)
- The llama.cpp HTTP server is running and accessible to all instances

**Verification:**

- Test procedure:

    1. Deploy 2 instances of the Text-to-Image API Service behind a load balancer configured for round-robin distribution (recommended tool: Kubernetes Deployment with `replicas: 2` and a Service of type LoadBalancer, or `docker-compose` with `nginx` as a reverse proxy)
    2. Execute [RO1](#ro1--prompt-enhancement) 10 times in sequence through the load balancer (recommended tool: terminal with `curl` in a loop)
    3. For each request, record the `X-Correlation-ID` response header value
    4. Examine the logs of each service instance and, for each recorded correlation identifier, determine which instance processed the request (recommended tool: `docker logs {container}` or `kubectl logs {pod}`)
    5. Count the number of requests processed by each instance

- Success criteria:

    - All 10 requests return HTTP 200 with valid `enhanced_prompt` values
    - Both instances process at least 3 requests each (demonstrating load distribution, within expected statistical variation for 10 requests across 2 instances)
    - No request fails due to instance-specific state requirements
    - All responses are structurally identical in format (same JSON schema) regardless of which instance processed the request

##### Stateless request processing

5. The service shall process each HTTP request independently, with no dependence on the outcome, state, or data produced by any prior request.

**Intent:** To guarantee that the service maintains no hidden state that could cause inconsistent behaviour across instances or across successive requests to the same instance. Statelessness is a prerequisite for horizontal scaling (requirement 4) and idempotent request handling (requirement 16).

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- The llama.cpp HTTP server is running and accessible

**Verification:**

- Test procedure:

    1. Execute [RO1](#ro1--prompt-enhancement) with the prompt `"a mountain landscape"` and record the HTTP status code and response structure (recommended tool: terminal with `curl`)
    2. Execute [RO4](#ro4--error-handling-invalid-json) and record the HTTP status code (recommended tool: terminal with `curl`)
    3. Immediately execute [RO1](#ro1--prompt-enhancement) again with the same prompt `"a mountain landscape"` and record the HTTP status code and response structure (recommended tool: terminal with `curl`)

- Success criteria:

    - The first execution of RO1 returns HTTP 200 with a valid `enhanced_prompt` field
    - The execution of RO4 returns HTTP 400 (demonstrating an error condition between the two successful requests)
    - The second execution of RO1 returns HTTP 200 with a valid `enhanced_prompt` field
    - The response structure of the second RO1 execution is identical in schema to the first (same fields, same types), confirming that the intervening error request did not corrupt service state

---

#### Reliability and Fault Tolerance

**Scope:** Requirements that define how the system handles failures, transient errors, and degraded dependencies, including fail-fast behaviour and partial availability guarantees.

##### Upstream timeout enforcement

6. The service shall enforce a bounded timeout when communicating with the llama.cpp server and shall return an HTTP 502 response within the configured timeout period if the llama.cpp server does not respond.

**Intent:** To prevent the service from hanging indefinitely when the llama.cpp server is slow or unresponsive. Bounded timeouts ensure that system resources are not consumed by requests that cannot be completed and that clients receive timely failure signals.

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- The environment variable `TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL` can be modified for test purposes

**Verification:**

- Test procedure:

    1. Execute [RO6](#ro6--error-handling-transient-network-fault-timeout) in its entirety
    2. Record the total request time and HTTP status code

- Success criteria:

    - All RO6 success criteria are met
    - The total request time is ≤ 125 seconds (the configured upstream timeout of 120 seconds plus up to 5 seconds of processing overhead)
    - The service remains responsive to `GET /health` requests during and after the timed-out request

##### Partial availability under component failure

7. The service shall remain available for image generation requests with `use_enhancer` set to `false` when the llama.cpp server is unavailable.

**Intent:** To ensure that a failure in the prompt enhancement dependency does not disable the entire service. Clients who do not require prompt enhancement should be able to generate images even when llama.cpp is unreachable.

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- The Stable Diffusion model is loaded and operational
- The llama.cpp server is intentionally stopped

**Verification:**

- Test procedure:

    1. Stop the llama.cpp server process (for example, `kill $(pgrep llama-server)` or equivalent)
    2. Verify the llama.cpp server is not responding: execute `curl http://localhost:8080/health` and confirm the request fails with "Connection refused" or equivalent (recommended tool: terminal with `curl`)
    3. Execute [RO2](#ro2--image-generation-without-enhancement) (which uses `use_enhancer: false`) and record the HTTP status code and response body (recommended tool: terminal with `curl`)
    4. Execute [RO5](#ro5--error-handling-llama-cpp-unavailable) (prompt enhancement with llama.cpp down) and record the HTTP status code (recommended tool: terminal with `curl`)

- Success criteria:

    - The execution of RO2 returns HTTP 200 with a valid image response, demonstrating that image generation without enhancement is unaffected by llama.cpp unavailability
    - The execution of RO5 returns HTTP 502 with `error.code` equal to `"upstream_service_unavailable"`, demonstrating that enhancement-dependent requests fail gracefully
    - The service does not crash, restart, or become unresponsive during or after these tests

##### Service process stability under upstream failure

8. The service process shall not terminate, crash, or enter an unrecoverable state when an upstream dependency (llama.cpp or Stable Diffusion) fails or becomes unavailable.

**Intent:** To ensure that upstream failures are isolated to individual request failures and do not compromise the overall service process. Process stability is a prerequisite for reliable horizontal scaling and automated orchestration (for example, Kubernetes liveness probes).

**Preconditions:**

- The Text-to-Image API Service is running and accessible

**Verification:**

- Test procedure:

    1. Record the service process identifier (PID) or Kubernetes pod name (recommended tool: `pgrep uvicorn` or `kubectl get pods`)
    2. Execute [RO5](#ro5--error-handling-llama-cpp-unavailable) to trigger an llama.cpp connection failure
    3. Execute [RO4](#ro4--error-handling-invalid-json) to trigger a JSON validation error
    4. Execute [RO6](#ro6--error-handling-transient-network-fault-timeout) to trigger a network timeout
    5. After all three error-inducing operations, verify the service process is still running by checking the process identifier (recommended tool: `ps -p {PID}` or `kubectl get pods`)
    6. Execute `curl http://localhost:8000/health` to verify the service health endpoint returns HTTP 200

- Success criteria:

    - The service process identifier is unchanged after all three error-inducing operations (the process did not restart)
    - The health endpoint returns HTTP 200 after all error-inducing operations
    - No unhandled exception stack traces appear in the service logs (all exceptions are caught and translated to structured error responses)

---

#### Observability

**Scope:** Requirements that ensure system behaviour can be monitored, diagnosed, and analysed through structured logs, telemetry, and metrics, enabling operational visibility, troubleshooting, and objective verification of other requirements.

##### Structured logging

9. The service shall emit all log entries in structured JSON format with mandatory fields: `timestamp` (ISO 8601 UTC), `level`, `event`, `correlation_id`, and `service_name`.

**Intent:** To ensure that the operational behaviour of the service can be reconstructed, queried, and analysed deterministically. Structured logs enable objective verification of other requirements and support efficient troubleshooting through machine-queryable log data.

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- Service log output is accessible (for example, via `docker logs`, `kubectl logs`, or stdout redirection)

**Verification:**

- Test procedure:

    1. Execute [RO1](#ro1--prompt-enhancement) and record the `X-Correlation-ID` response header value (recommended tool: terminal with `curl -i`)
    2. Execute [RO4](#ro4--error-handling-invalid-json) and record the `X-Correlation-ID` response header value
    3. Retrieve the service log output (recommended tool: `docker logs {container}` or `kubectl logs {pod}`)
    4. Locate all log entries whose `correlation_id` field matches the correlation identifier recorded in step 1
    5. Locate all log entries whose `correlation_id` field matches the correlation identifier recorded in step 2
    6. For each located log entry, inspect the following fields: `timestamp`, `level`, `event`, `correlation_id`, `service_name`

- Success criteria:

    - Every inspected log entry is valid JSON (parseable by a standard JSON parser)
    - Every inspected log entry contains all five mandatory fields: `timestamp`, `level`, `event`, `correlation_id`, `service_name`
    - The `timestamp` field is in ISO 8601 format with UTC timezone (for example, `2026-02-16T14:32:10.123456Z`)
    - The `level` field is one of: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
    - The `event` field is a snake_case string identifying the event type (for example, `http_request_received`, `prompt_enhancement_completed`)
    - The `correlation_id` field matches the `X-Correlation-ID` response header for the corresponding request
    - The `service_name` field is a consistent, non-empty string across all log entries
    - At least one log entry exists for the successful RO1 request with `level` equal to `INFO`
    - At least one log entry exists for the failed RO4 request with `level` equal to `WARNING` or `ERROR`

##### Error observability

10. The service shall emit structured log entries at ERROR level for all upstream failures, including the correlation identifier, the nature of the failure, and the upstream service that failed.

**Intent:** To ensure that operational teams can identify, diagnose, and correlate upstream failures using structured logs without requiring application-level debugging. Error log entries must be sufficient to reconstruct the failure scenario and to correlate with client-reported errors.

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- Service log output is accessible

**Verification:**

- Test procedure:

    1. Execute [RO5](#ro5--error-handling-llama-cpp-unavailable) and record the `X-Correlation-ID` from the HTTP response header (recommended tool: terminal with `curl -i`)
    2. Retrieve the service log output (recommended tool: `docker logs {container}` or `kubectl logs {pod}`)
    3. Locate all log entries whose `correlation_id` field matches the recorded correlation identifier
    4. Identify the log entry (or entries) with `level` equal to `ERROR`

- Success criteria:

    - At least one ERROR-level log entry exists with a `correlation_id` matching the recorded value
    - The ERROR-level log entry contains a field (for example, `error` or `exception_message`) describing the nature of the failure (for example, "Connection refused" or "timeout")
    - The ERROR-level log entry does not contain internal stack traces, file paths, or credentials in fields that would be exposed to log aggregation systems shared with non-privileged users

##### Performance metrics collection

11. The service shall collect and expose request latency and request count metrics in a machine-readable format suitable for monitoring.

**Intent:** To provide operational visibility into service performance, enabling capacity planning, anomaly detection, and SLA monitoring. Metrics must be collectible by standard monitoring tools.

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- The `GET /metrics` endpoint is exposed by the service

**Verification:**

- Test procedure:

    1. Execute [RO1](#ro1--prompt-enhancement) and [RO2](#ro2--image-generation-without-enhancement) at least once each (recommended tool: terminal with `curl`)
    2. Query the service metrics endpoint: `curl http://localhost:8000/metrics` (recommended tool: terminal with `curl`)
    3. Inspect the returned JSON for `request_counts` and `request_latencies` fields

- Success criteria:

    - Request count metrics exist and reflect the number of requests executed in steps 1
    - Latency metrics exist and contain non-zero values consistent with the observed response times
    - Metrics are formatted in a standard, machine-parseable format (for example, Prometheus text exposition format or structured JSON)

---

#### Security

**Scope:** Requirements that define input validation, error message sanitisation, and protection against information disclosure, within the context of a local or trusted network deployment.

##### Input validation

12. The service shall validate all user-provided input against the defined JSON schemas before processing and shall reject invalid input with an HTTP 400 response containing a structured error body.

**Intent:** To prevent injection attacks, resource exhaustion, and unintended behaviour from malformed or malicious input. Early input validation enforces the API contract at the service boundary and prevents invalid data from reaching inference engines.

**Verification:** Verified via FR4 (Request Validation: Schema Compliance) and FR5 (Error Handling: Invalid JSON Syntax) test procedures.

##### Error message sanitisation

13. The service shall not expose internal implementation details, stack traces, file paths, internal IP addresses, or configuration values in error responses returned to clients.

**Intent:** To prevent information disclosure that could aid attackers in reconnaissance or exploitation of vulnerabilities, even in a local deployment context. Error responses shall contain only user-friendly, non-revealing messages.

**Preconditions:**

- The Text-to-Image API Service is running and accessible

**Verification:**

- Test procedure:

    1. Execute [RO4](#ro4--error-handling-invalid-json) and capture the full HTTP response body (recommended tool: terminal with `curl`)
    2. Execute [RO5](#ro5--error-handling-llama-cpp-unavailable) and capture the full HTTP response body
    3. For each response body, search for the following patterns:
        - Python exception type names (for example, `ValueError`, `ConnectionError`, `TypeError`)
        - File system paths (for example, strings containing `/home/`, `/app/`, `/usr/`)
        - Internal IP addresses or hostnames (for example, `10.x.x.x`, `172.x.x.x`, `192.168.x.x`, or internal DNS names)
        - Stack trace indicators (for example, `Traceback`, `File "`, `line `)
        - Configuration values (for example, environment variable values, model file paths)

- Success criteria:

    - No error response body contains any of the patterns listed above
    - All error response bodies contain only the fields defined in the error response schema (`code`, `message`, `details`, `correlation_id`)
    - Detailed technical error information (stack traces, internal addresses) appears only in server-side logs, never in HTTP responses

---

#### API Contract and Stability

**Scope:** Requirements that define API behaviour guarantees, including response format consistency, versioning, and backward compatibility.

##### API versioning

14. The service shall expose explicitly versioned endpoints using a URL path prefix.

**Intent:** To ensure that API consumers can rely on stable, predictable behaviour over time while allowing the API to evolve in a controlled manner. Explicit versioning prevents incompatible changes from affecting existing clients unexpectedly.

**Preconditions:**

- The Text-to-Image API Service is running and accessible

**Verification:**

- Test procedure:

    1. Execute [RO1](#ro1--prompt-enhancement) using the endpoint URL `http://localhost:8000/v1/prompts/enhance` and record the HTTP status code (recommended tool: terminal with `curl`)
    2. Execute [RO2](#ro2--image-generation-without-enhancement) using the endpoint URL `http://localhost:8000/v1/images/generations` and record the HTTP status code (recommended tool: terminal with `curl`)
    3. Execute a request to `POST http://localhost:8000/prompts/enhance` (without the `/v1` prefix) with the same request body as RO1, and record the HTTP status code

- Success criteria:

    - The versioned endpoints (steps 1 and 2) return HTTP 200 with valid response bodies
    - The unversioned endpoint (step 3) returns either HTTP 404 (endpoint not found) or a redirect to the versioned endpoint, but does not return a successful response, confirming that versioned access is enforced

##### Response format consistency

15. The service shall return all HTTP responses as valid JSON documents with a `Content-Type: application/json` header, including both successful and error responses.

**Intent:** To ensure API clients can reliably parse all responses using standard JSON libraries without conditional content-type handling. Consistent response formatting is a prerequisite for automated testing and monitoring.

**Verification:** Verified via FR9 (Response Format Consistency) test procedures.

---

### Functional Requirements

The functional requirements define the observable behaviour of the system: the operations it performs, the data it accepts, processes, and returns, and the rules that govern those behaviours.

#### Prompt Enhancement

**Scope:** Requirements that define the prompt enhancement endpoint, including what input is accepted, how the llama.cpp server is invoked, and what output is returned.

##### Prompt enhancement capability

16. The service shall accept a natural language prompt via the `POST /v1/prompts/enhance` endpoint and return an enhanced version of the prompt optimised for text-to-image generation.

**Intent:** To enable users to improve the quality of generated images by transforming simple prompts into detailed, visually descriptive prompts that include artistic style, lighting, composition, and quality modifiers.

**Preconditions:**

- The Text-to-Image API Service is running and accessible at its configured port (recommended verification: `curl http://localhost:8000/health` returns HTTP 200)
- The llama.cpp HTTP server is running and accessible at its configured port (recommended verification: `curl http://localhost:8080/health`)
- The llama.cpp server is loaded with an instruction-tuned language model

**Verification:**

- Test procedure:

    1. Execute [RO1](#ro1--prompt-enhancement) exactly as documented in the Reference Operations section (recommended tool: terminal with `curl`)
    2. Record the HTTP status code, response body, and `X-Correlation-ID` response header
    3. Parse the JSON response body and extract the `enhanced_prompt` field value
    4. Measure the character length of the `enhanced_prompt` value
    5. Visually inspect the `enhanced_prompt` value for the presence of descriptive modifiers (for example, artistic style, lighting conditions, composition details, or quality indicators such as "photorealistic" or "high detail")
    6. Repeat steps 1–5 with two additional prompts of different lengths: one prompt of approximately 10 characters (for example, `"red car"`) and one prompt of approximately 500 characters

- Success criteria:

    - All three requests return HTTP 200
    - All three response bodies contain a valid `enhanced_prompt` field of type string
    - All three `enhanced_prompt` values have a character length ≥ 50
    - All three `enhanced_prompt` values contain descriptive modifiers not present in the original prompt (assessed by visual inspection: the enhanced prompt includes at least one of the following categories: artistic style, lighting, composition, or quality modifiers)
    - No `enhanced_prompt` value contains meta-commentary, explanations, or text that is not part of the enhanced prompt itself (for example, no "Here is the enhanced prompt:" preamble)
    - All three responses include an `X-Correlation-ID` header with a valid UUID v4 value

---

#### Image Generation

**Scope:** Requirements that define the image generation endpoint, including input parameters, the optional enhancement workflow, supported image sizes, batch generation, and output format.

##### Image generation without enhancement

17. The service shall generate one or more images from a user-provided prompt without invoking prompt enhancement when `use_enhancer` is set to `false`.

**Intent:** To provide direct image generation capability for users who have already crafted detailed prompts or who wish to bypass the enhancement step for performance or control reasons.

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- The Stable Diffusion model has been fully loaded (verify via service startup logs)

**Verification:**

- Test procedure:

    1. Execute [RO2](#ro2--image-generation-without-enhancement) exactly as documented in the Reference Operations section (recommended tool: terminal with `curl`)
    2. Verify all RO2 success criteria are met
    3. Examine the service logs for the request identified by its `X-Correlation-ID` value (recommended tool: `docker logs {container}` or `kubectl logs {pod}`)
    4. Search the logs for any event indicating an llama.cpp invocation (for example, `llama_cpp_request_sent`, `prompt_enhancement_initiated`, or any HTTP request to the llama.cpp base URL)

- Success criteria:

    - All RO2 success criteria are met
    - The service logs contain no events indicating that llama.cpp was invoked for this request, confirming that enhancement was bypassed when `use_enhancer` was `false`

##### Image generation with enhancement

18. The service shall enhance the user-provided prompt using llama.cpp before generating images when `use_enhancer` is set to `true`, and shall use the enhanced prompt (not the original prompt) for Stable Diffusion inference.

**Intent:** To provide an integrated workflow that automatically improves prompt quality before image generation, maximising output quality without requiring users to manually craft detailed prompts.

**Preconditions:**

- The Text-to-Image API Service and llama.cpp server are both running and accessible
- The Stable Diffusion model has been fully loaded
- Requirements 16 (Prompt Enhancement Capability) and 17 (Image Generation Without Enhancement) have been verified independently

**Verification:**

- Test procedure:

    1. Execute [RO3](#ro3--image-generation-with-enhancement) exactly as documented in the Reference Operations section (recommended tool: terminal with `curl`)
    2. Verify all RO3 success criteria are met
    3. Examine the service logs for the request identified by its `X-Correlation-ID` value (recommended tool: `docker logs {container}` or `kubectl logs {pod}`)
    4. Locate the log entries in chronological order and verify the following sequence:
        a. A log entry indicating prompt enhancement was initiated (for example, `prompt_enhancement_initiated`)
        b. A log entry indicating prompt enhancement completed (for example, `prompt_enhancement_completed`), containing or referencing the enhanced prompt text
        c. A log entry indicating image generation was initiated (for example, `image_generation_initiated`)
        d. A log entry indicating image generation completed (for example, `image_generation_completed`)
    5. Verify the enhanced prompt text (from step 4b) differs from the original input prompt `"a futuristic cityscape"`

- Success criteria:

    - All RO3 success criteria are met
    - The service logs confirm the sequential execution order: enhancement first, then generation
    - The enhanced prompt text logged in step 4b is demonstrably different from the original input prompt
    - Enhancement failure (if llama.cpp were unavailable) causes the entire request to fail with HTTP 502; the service does not silently fall back to the unenhanced prompt

##### Batch image generation

19. The service shall generate between 1 and 4 images per request when the `n` parameter is specified, returning exactly `n` base64-encoded PNG images in the `data` array.

**Intent:** To enable batch generation workflows where multiple image variations are desired from a single prompt, reducing total request overhead compared to sequential single-image requests.

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- The Stable Diffusion model has been fully loaded

**Verification:**

- Test procedure:

    1. Execute a `POST /v1/images/generations` request with `n=1`, `use_enhancer: false`, `size: "512x512"`, and a prompt of your choice. Record the number of elements in the response `data` array (recommended tool: terminal with `curl` and `jq`)
    2. Execute a `POST /v1/images/generations` request with `n=2`, `use_enhancer: false`, `size: "512x512"`, and a prompt of your choice. Record the number of elements in the response `data` array
    3. Execute a `POST /v1/images/generations` request with `n=4`, `use_enhancer: false`, `size: "512x512"`, and a prompt of your choice. Record the number of elements in the response `data` array
    4. For each response, decode all base64 images and verify each is a valid PNG with dimensions 512×512 pixels (recommended tool: `jq`, `base64`, `file`, and `identify` or equivalent)
    5. Execute a `POST /v1/images/generations` request with `n=5` (exceeding the maximum) and record the HTTP status code

- Success criteria:

    - The `n=1` response contains a `data` array with exactly 1 element
    - The `n=2` response contains a `data` array with exactly 2 elements
    - The `n=4` response contains a `data` array with exactly 4 elements
    - All decoded images are valid PNGs with dimensions 512×512 pixels
    - The `n=5` request returns HTTP 400 with `error.code` equal to `"request_validation_failed"`

##### Image size parameter handling

20. The service shall generate images with dimensions matching the requested `size` parameter, supporting `512x512`, `768x768`, and `1024x1024` pixel dimensions.

**Intent:** To provide clients with control over output resolution, enabling trade-offs between generation speed (smaller images are faster) and output quality (larger images contain more detail).

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- The Stable Diffusion model has been fully loaded

**Verification:**

- Test procedure:

    1. Execute a `POST /v1/images/generations` request with `size: "512x512"`, `n: 1`, `use_enhancer: false`, and a prompt of your choice. Decode the resulting base64 image to a PNG file (recommended tool: terminal with `curl`, `jq`, `base64`)
    2. Verify the decoded image dimensions using an image inspection tool (recommended tool: `identify image.png` from ImageMagick, or `file image.png`)
    3. Repeat steps 1–2 with `size: "768x768"`
    4. Repeat steps 1–2 with `size: "1024x1024"`
    5. Execute a request with `size: "256x256"` (unsupported) and record the HTTP status code

- Success criteria:

    - The `512x512` request produces an image with exact dimensions 512×512 pixels
    - The `768x768` request produces an image with exact dimensions 768×768 pixels
    - The `1024x1024` request produces an image with exact dimensions 1024×1024 pixels
    - The `256x256` request returns HTTP 400 with `error.code` equal to `"request_validation_failed"` and an error message indicating the invalid enum value

---

#### Request Validation and Error Handling

**Scope:** Requirements that define how the service validates incoming requests, handles malformed input, and maps error conditions to appropriate HTTP status codes with structured error responses.

##### Request validation: schema compliance

21. The service shall validate all incoming HTTP request bodies against the defined JSON schema for each endpoint and shall reject requests that fail validation with HTTP 400 and a structured error response identifying the specific validation failure.

**Intent:** To enforce API contract compliance, prevent malformed requests from consuming inference resources, and provide clear, actionable error messages to API clients.

**Preconditions:**

- The Text-to-Image API Service is running and accessible

**Verification:**

- Test procedure:

    Execute the following validation tests against the `POST /v1/images/generations` endpoint using `curl` (recommended tool: terminal with `curl`):

    1. **Missing required field:** Send `{"use_enhancer": false, "n": 1, "size": "512x512"}` (no `prompt` field). Record the HTTP status code and response body.
    2. **Field type violation:** Send `{"prompt": 12345}` (prompt is an integer, not a string). Record the HTTP status code and response body.
    3. **Length constraint violation:** Send `{"prompt": "` followed by 2001 characters of text followed by `"}`. Record the HTTP status code and response body.
    4. **Enum violation:** Send `{"prompt": "test", "size": "999x999"}`. Record the HTTP status code and response body.
    5. **Range violation (above maximum):** Send `{"prompt": "test", "n": 5}`. Record the HTTP status code and response body.
    6. **Range violation (below minimum):** Send `{"prompt": "test", "n": 0}`. Record the HTTP status code and response body.
    7. **Whitespace-only prompt:** Send `{"prompt": "   "}`. Record the HTTP status code and response body.
    8. Parse each response body as JSON and inspect the `error` object.

- Success criteria:

    - All seven requests return HTTP 400
    - All seven response bodies contain an `error` object with `code`, `message`, and `correlation_id` fields
    - The `error.code` field is `"request_validation_failed"` for all seven responses
    - The `error.details` field (or `error.message`) identifies which field failed validation and why (for example, "prompt is required", "n must be between 1 and 4")
    - No response returns HTTP 200 or any status code other than 400

##### Error handling: invalid JSON syntax

22. The service shall detect malformed JSON syntax in request bodies and return HTTP 400 with a structured error response.

**Intent:** To provide immediate, actionable feedback when clients send syntactically invalid JSON, enabling rapid debugging without consuming inference resources.

**Preconditions:**

- The Text-to-Image API Service is running and accessible

**Verification:**

- Test procedure:

    1. Execute [RO4](#ro4--error-handling-invalid-json) exactly as documented in the Reference Operations section (recommended tool: terminal with `curl`)
    2. Verify all RO4 success criteria are met
    3. Execute additional malformed JSON tests against `POST /v1/prompts/enhance`:
        a. Missing comma: `{"prompt": "test" "extra": "field"}`
        b. Trailing comma: `{"prompt": "test",}`
    4. For each additional test, record the HTTP status code and parse the response body

- Success criteria:

    - All RO4 success criteria are met
    - All additional malformed JSON requests return HTTP 400
    - All error responses contain `error.code` equal to `"invalid_request_json"`
    - All error responses contain a valid `error.correlation_id` field

##### Error handling: llama.cpp unavailability

23. The service shall detect llama.cpp server connection failures and return HTTP 502 with a structured error response indicating the upstream service is unavailable.

**Intent:** To provide clear error signals when the prompt enhancement dependency is unreachable, enabling operators to diagnose infrastructure issues and clients to implement appropriate retry logic.

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- The llama.cpp server is intentionally stopped

**Verification:**

- Test procedure:

    1. Execute [RO5](#ro5--error-handling-llama-cpp-unavailable) exactly as documented in the Reference Operations section (recommended tool: terminal with `curl`)
    2. Verify all RO5 success criteria are met

- Success criteria:

    - All RO5 success criteria are met

##### Error handling: Stable Diffusion failures

24. The service shall detect Stable Diffusion model loading or inference failures and return HTTP 502 with a structured error response indicating the image generation model is unavailable.

**Intent:** To isolate Stable Diffusion failures from service availability, ensuring that model issues are clearly identified and do not cause service crashes.

**Preconditions:**

- The Text-to-Image API Service is deployed
- The Stable Diffusion model files are missing, corrupted, or insufficient memory is available (for failure testing)

**Verification:**

- Test procedure:

    1. Deploy the Text-to-Image API Service in an environment where the Stable Diffusion model cannot be loaded (for example, set the environment variable `TEXT_TO_IMAGE_STABLE_DIFFUSION_MODEL_ID` to a non-existent model identifier such as `"nonexistent/model-does-not-exist"`, or restrict available memory to below 4 GB)
    2. Start the service and observe the startup behaviour (recommended tool: `docker logs {container}` or terminal output)
    3. If the service starts despite the model failure, execute a `POST /v1/images/generations` request with `{"prompt": "test", "use_enhancer": false, "n": 1, "size": "512x512"}` and record the HTTP status code and response body

- Success criteria:

    - Either (a) the service refuses to start and emits a clear, human-readable error log indicating the model loading failure, or (b) the service starts but returns HTTP 502 with `error.code` equal to `"model_unavailable"` for image generation requests
    - In either case, no unhandled exception stack trace appears in client-facing HTTP responses
    - If the service remains running, the prompt enhancement endpoint (`POST /v1/prompts/enhance`) still functions correctly (it does not depend on Stable Diffusion)

##### Error handling: unexpected internal errors

25. The service shall catch all unhandled exceptions during request processing and return HTTP 500 with a structured error response that does not expose internal details.

**Intent:** To provide a deterministic, safe fallback for any error condition not explicitly handled by specific error handlers. This ensures that clients always receive a parseable JSON response and that no internal implementation details leak through unexpected error paths.

**Preconditions:**

- The Text-to-Image API Service is running and accessible

**Verification:**

- Test procedure:

    1. Execute [RO1](#ro1--prompt-enhancement), [RO2](#ro2--image-generation-without-enhancement), [RO4](#ro4--error-handling-invalid-json), and [RO5](#ro5--error-handling-llama-cpp-unavailable)
    2. For every HTTP response received (both successful and error), verify the response body is valid JSON by parsing it with a standard JSON parser (recommended tool: `jq .`)

- Success criteria:

    - Every HTTP response received across all reference operations has a `Content-Type: application/json` header
    - Every HTTP response body is valid JSON
    - No response body contains raw exception messages, stack traces, or HTML error pages
    - Error responses (HTTP 4xx and 5xx) all conform to the error response schema defined in the Data Model and Schema Definition section

---

#### Correlation and Tracing

**Scope:** Requirements that define how request correlation identifiers are generated, propagated, and included in responses and logs.

##### Correlation identifier injection

26. The service shall generate a unique UUID v4 correlation identifier for each incoming HTTP request and include this identifier in the `X-Correlation-ID` response header, all structured log entries for that request, and all error response bodies.

**Intent:** To enable end-to-end request tracing across log aggregation systems, supporting rapid incident diagnosis and request lifecycle reconstruction.

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- Service log output is accessible

**Verification:**

- Test procedure:

    1. Execute [RO1](#ro1--prompt-enhancement) and record the `X-Correlation-ID` response header value (recommended tool: `curl -i`)
    2. Execute [RO4](#ro4--error-handling-invalid-json) and record the `X-Correlation-ID` response header value and the `error.correlation_id` field from the response body
    3. Retrieve the service log output and locate all log entries containing the correlation identifier from step 1
    4. Retrieve the service log output and locate all log entries containing the correlation identifier from step 2

- Success criteria:

    - Both responses include an `X-Correlation-ID` header
    - Both correlation identifiers are valid UUID v4 values (8-4-4-4-12 hexadecimal digit pattern)
    - The two correlation identifiers are different (unique per request)
    - For the error response (step 2), the `error.correlation_id` field matches the `X-Correlation-ID` header
    - At least one log entry exists for each correlation identifier in the service logs
    - All log entries for a given correlation identifier share the same `correlation_id` value

---

#### Health and Readiness

**Scope:** Requirements that define health check endpoints used by load balancers, orchestrators, and monitoring systems.

##### Health check endpoint

27. The service shall expose a `GET /health` endpoint returning HTTP 200 with `{"status": "healthy"}` when the service is operational.

**Intent:** To enable load balancers, container orchestrators (for example, Kubernetes), and monitoring systems to determine service health and route traffic appropriately.

**Preconditions:**

- The Text-to-Image API Service is running and accessible

**Verification:**

- Test procedure:

    1. Execute: `curl -s -w "\nHTTP_STATUS:%{http_code}\n" http://localhost:8000/health` (recommended tool: terminal with `curl`)
    2. Record the HTTP status code and response body

- Success criteria:

    - The HTTP status code is 200
    - The response body is valid JSON
    - The response body contains `"status": "healthy"` (or an equivalent status field)
    - The response time is < 500 milliseconds

##### Readiness check endpoint

30. The service shall expose a `GET /health/ready` endpoint that reports the initialisation status of backend services (language model client, image generation pipeline). The endpoint shall return HTTP 200 with `{"status": "ready"}` when all backends are initialised, and HTTP 503 with `{"status": "not_ready"}` when any backend is unavailable.

**Intent:** To enable orchestrators (for example, Kubernetes readiness probes) to distinguish between a service that is alive but still loading models and one that is fully ready to accept traffic. This prevents load balancers from routing requests to instances that have not yet completed model loading.

**Preconditions:**

- The Text-to-Image API Service is running and accessible

**Verification:**

- Test procedure:

    1. Execute: `curl -s -w "\nHTTP_STATUS:%{http_code}\n" http://localhost:8000/health/ready` (recommended tool: terminal with `curl`)
    2. Record the HTTP status code and response body

- Success criteria:

    - The HTTP status code is 200 when all backend services are initialised
    - The response body is valid JSON containing `"status": "ready"` and a `"checks"` object with `"image_generation"` and `"language_model"` fields
    - Each check field is `"ok"` when the corresponding service is initialised

---

#### Configuration-Driven Behaviour

**Scope:** Requirements that define how the service loads configuration from environment variables and validates required configuration on startup.

##### Configuration externalisation

28. The service shall load all configuration from environment variables, supporting deployment-time configuration without code changes or container image rebuilds.

**Intent:** To enable environment-specific configuration (development, staging, production) using a single container image, following twelve-factor application principles.

**Preconditions:**

- The Text-to-Image API Service can be started with custom environment variables

**Verification:**

- Test procedure:

    1. Start the service with default configuration (no custom environment variables beyond required ones). Verify it starts successfully and responds on its default port (recommended tool: terminal with `curl http://localhost:8000/health`)
    2. Stop the service
    3. Set the environment variable `TEXT_TO_IMAGE_APPLICATION_PORT` to `9000` and restart the service
    4. Execute `curl http://localhost:9000/health` and record the HTTP status code
    5. Stop the service and restore `TEXT_TO_IMAGE_APPLICATION_PORT` to its default value

- Success criteria:

    - The service responds on port 8000 with default configuration
    - The service responds on port 9000 after setting `TEXT_TO_IMAGE_APPLICATION_PORT=9000`, without any code changes or image rebuilds
    - Missing required configuration (for example, unsetting `TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL` if it is required) causes a clear startup failure with a human-readable error message in the logs

##### Graceful shutdown

29. The service shall complete in-flight requests before terminating when receiving a `SIGTERM` signal, with a maximum graceful shutdown timeout of 60 seconds.

**Intent:** To prevent request failures during rolling deployments or scaling events, ensuring that clients do not receive abruptly terminated connections.

**Preconditions:**

- The Text-to-Image API Service is running and accessible
- The service process can receive SIGTERM signals

**Verification:**

- Test procedure:

    1. Start a long-running request by executing [RO2](#ro2--image-generation-without-enhancement) in the background (recommended tool: `curl ... &` in a terminal)
    2. While the request is in flight, send SIGTERM to the service process: `kill -TERM $(pgrep uvicorn)` or equivalent
    3. Wait for the background request to complete and record the HTTP status code and response body

- Success criteria:

    - The in-flight request completes successfully (HTTP 200 with a valid image response) before the service terminates
    - The service terminates within 60 seconds of receiving SIGTERM
    - The service logs contain an INFO-level entry indicating graceful shutdown initiation

---

## Requirements Traceability Matrix

This matrix links functional requirements, reference operations, and non-functional requirements, demonstrating how each functional requirement validates specific quality attributes. A functional requirement supports a non-functional requirement if implementing the functional requirement correctly requires the non-functional requirement to be upheld.

| Functional Requirement | Reference Operations Used for Verification | Key Non-Functional Requirements Supported |
|------------------------|---------------------------------------------|------------------------------------------|
| 16 (Prompt enhancement capability) | RO1 | 1 (Prompt enhancement latency), 4 (Horizontal scaling), 5 (Statelessness), 9 (Structured logging), 11 (Performance metrics), 12 (Input validation), 14 (API versioning), 15 (Response format consistency) |
| 17 (Image generation without enhancement) | RO2 | 2 (Image generation latency), 4 (Horizontal scaling), 5 (Statelessness), 7 (Partial availability), 9 (Structured logging), 11 (Performance metrics), 12 (Input validation), 14 (API versioning), 15 (Response format consistency) |
| 18 (Image generation with enhancement) | RO3 | 1 (Prompt enhancement latency), 2 (Image generation latency), 6 (Upstream timeout enforcement), 9 (Structured logging), 11 (Performance metrics), 14 (API versioning), 15 (Response format consistency) |
| 19 (Batch image generation) | RO2, RO3 | 2 (Image generation latency), 12 (Input validation) |
| 20 (Image size parameter handling) | RO2, RO3 | 12 (Input validation) |
| 21 (Request validation: schema compliance) | RO1–RO4 | 3 (Validation response latency), 12 (Input validation), 13 (Error message sanitisation) |
| 22 (Error handling: invalid JSON syntax) | RO4 | 3 (Validation response latency), 12 (Input validation), 13 (Error message sanitisation) |
| 23 (Error handling: llama.cpp unavailability) | RO5 | 6 (Upstream timeout enforcement), 7 (Partial availability), 8 (Service process stability), 10 (Error observability), 13 (Error message sanitisation) |
| 24 (Error handling: Stable Diffusion failures) | — | 8 (Service process stability), 10 (Error observability), 13 (Error message sanitisation) |
| 25 (Error handling: unexpected internal errors) | RO1–RO5 | 8 (Service process stability), 13 (Error message sanitisation), 15 (Response format consistency) |
| 26 (Correlation identifier injection) | RO1, RO4 | 9 (Structured logging), 10 (Error observability) |
| 27 (Health check endpoint) | — | 4 (Horizontal scaling) |
| 28 (Configuration externalisation) | — | 4 (Horizontal scaling), 5 (Statelessness) |
| 29 (Graceful shutdown) | RO2 | 4 (Horizontal scaling) |
| 30 (Readiness check endpoint) | — | 4 (Horizontal scaling), 7 (Partial availability) |

---

## New Requirement Categorisation Guide

When adding a new requirement to this specification, first determine whether it is functional or non-functional, then use the appropriate decision tree below.

### Step 1: Functional versus non-functional

Does this requirement define what the system does (an operation, transformation, or data it processes), or does it define how well the system does it (a quality attribute, constraint, or behavioural guarantee)?

- **Functional** → Defines operations, data processing, transformations, or workflow rules. E.g., "The service shall accept a prompt and return an enhanced prompt."
- **Non-functional** → Defines quality attributes, performance constraints, stability guarantees, or operational properties. E.g., "The service shall respond within 30 seconds."

### Step 2A: Categorising functional requirements

1. Does it define how the service enhances prompts via llama.cpp?
   → **Prompt Enhancement**
2. Does it define how the service generates images via Stable Diffusion?
   → **Image Generation**
3. Does it define how the service validates requests, handles malformed input, or rejects invalid requests?
   → **Request Validation and Error Handling**
4. Does it define how correlation identifiers are generated, propagated, or included in responses?
   → **Correlation and Tracing**
5. Does it define health check or readiness endpoints?
   → **Health and Readiness**
6. Does it define system behaviour that can be modified through configuration without code changes?
   → **Configuration-Driven Behaviour**

### Step 2B: Categorising non-functional requirements

1. Does it define response time, throughput, or latency constraints?
   → **Performance and Latency**
2. Does it define how the system scales horizontally or maintains statelessness?
   → **Scalability**
3. Does it define how the system handles failures, transient errors, or degraded dependencies?
   → **Reliability and Fault Tolerance**
4. Does it define logging, metrics, tracing, or diagnostic visibility?
   → **Observability**
5. Does it define input validation, error sanitisation, or information disclosure prevention?
   → **Security**
6. Does it define API versioning, response format consistency, or backward compatibility?
   → **API Contract and Stability**

---

## New Requirement Section Creation Guide

If you are considering creating a new section within Functional Requirements or Non-Functional Requirements:

- Create a new section when you have a requirement that represents a distinct quality attribute or functional capability not covered by existing sections.
- Ensure the new section has a clear, focused purpose that can be expressed in a scope statement.
- A new section can contain a single requirement if it represents a coherent, standalone concern that is likely to have additional requirements added in the future.
- Prefer creating a focused new section over forcing a requirement into an ill-fitting existing section.

**Rationale:** This specification prioritises long-term scalability and conceptual clarity. A single-requirement section that clearly delineates a distinct concern is preferable to diluting an existing section's focus or creating ambiguity about requirement categorisation.

---

## Data Model and Schema Definition

This section defines the API request and response schemas and validation rules. The Text-to-Image API Service is stateless and does not maintain persistent storage; however, it enforces strict schemas for all API contracts.

### API Request Schemas

#### Prompt Enhancement Request Schema

**Endpoint:** `POST /v1/prompts/enhance`
**Content-Type:** `application/json`

**JSON Schema:**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["prompt"],
  "properties": {
    "prompt": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2000,
      "description": "Natural language prompt to enhance for text-to-image generation.",
      "pattern": ".*\\S.*"
    }
  },
  "additionalProperties": false
}
```

**Field Validation Rules:**

| Field | Type | Required | Default | Constraints | Error Code on Violation |
|-------|------|----------|---------|-------------|------------------------|
| `prompt` | string | Yes | — | 1 ≤ length ≤ 2000 characters; must contain at least one non-whitespace character | `request_validation_failed` |

#### Image Generation Request Schema

**Endpoint:** `POST /v1/images/generations`
**Content-Type:** `application/json`

**JSON Schema:**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["prompt"],
  "properties": {
    "prompt": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2000,
      "description": "Natural language prompt describing the desired image.",
      "pattern": ".*\\S.*"
    },
    "use_enhancer": {
      "type": "boolean",
      "default": false,
      "description": "When true, the prompt is enhanced via llama.cpp before image generation."
    },
    "n": {
      "type": "integer",
      "minimum": 1,
      "maximum": 4,
      "default": 1,
      "description": "Number of images to generate."
    },
    "size": {
      "type": "string",
      "enum": ["512x512", "768x768", "1024x1024"],
      "default": "512x512",
      "description": "Pixel dimensions of the generated image(s)."
    }
  },
  "additionalProperties": false
}
```

**Field Validation Rules:**

| Field | Type | Required | Default | Constraints | Error Code on Violation |
|-------|------|----------|---------|-------------|------------------------|
| `prompt` | string | Yes | — | 1 ≤ length ≤ 2000 characters; must contain at least one non-whitespace character | `request_validation_failed` |
| `use_enhancer` | boolean | No | `false` | Must be a JSON boolean (`true` or `false`) | `request_validation_failed` |
| `n` | integer | No | `1` | 1 ≤ n ≤ 4; must be an integer (not a float) | `request_validation_failed` |
| `size` | string | No | `"512x512"` | Must be one of: `"512x512"`, `"768x768"`, `"1024x1024"` | `request_validation_failed` |

### API Response Schemas

#### Prompt Enhancement Response Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["enhanced_prompt"],
  "properties": {
    "enhanced_prompt": {
      "type": "string",
      "minLength": 1,
      "description": "Enhanced version of the input prompt, optimised for text-to-image generation."
    }
  },
  "additionalProperties": false
}
```

#### Image Generation Response Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["created", "data"],
  "properties": {
    "created": {
      "type": "integer",
      "description": "Unix timestamp (seconds since epoch) indicating when generation completed."
    },
    "data": {
      "type": "array",
      "minItems": 1,
      "maxItems": 4,
      "items": {
        "type": "object",
        "required": ["b64_json"],
        "properties": {
          "b64_json": {
            "type": "string",
            "contentEncoding": "base64",
            "description": "Base64-encoded PNG image data."
          }
        },
        "additionalProperties": false
      },
      "description": "Array of generated images; array length equals the request 'n' parameter."
    }
  },
  "additionalProperties": false
}
```

#### Error Response Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["error"],
  "properties": {
    "error": {
      "type": "object",
      "required": ["code", "message", "correlation_id"],
      "properties": {
        "code": {
          "type": "string",
          "description": "Machine-readable error identifier in snake_case format."
        },
        "message": {
          "type": "string",
          "description": "Human-readable error description safe for display to end users."
        },
        "details": {
          "description": "Additional context about the error, when available.",
          "type": ["string", "null"]
        },
        "correlation_id": {
          "type": "string",
          "format": "uuid",
          "description": "UUID v4 correlation identifier matching the X-Correlation-ID response header."
        }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

### Error Code Registry

**Client errors (HTTP 400):**

| Code | Trigger Condition | `details` Format |
|------|-------------------|------------------|
| `invalid_request_json` | JSON syntax error in request body | String describing the parse error |
| `request_validation_failed` | Schema validation failure (missing field, type mismatch, constraint violation) | Array of objects identifying failing fields |

**Upstream errors (HTTP 502):**

| Code | Trigger Condition | `details` Format |
|------|-------------------|------------------|
| `upstream_service_unavailable` | llama.cpp connection failure, timeout, or HTTP error | String describing the failure (sanitised) |
| `model_unavailable` | Stable Diffusion model loading or inference failure | String describing the failure (sanitised) |

**Internal errors (HTTP 500):**

| Code | Trigger Condition | `details` Format |
|------|-------------------|------------------|
| `internal_server_error` | Unexpected, unhandled exception | Omitted (no internal details exposed) |

---

## API Contract Definition

### Base URL and Versioning

**Base URL:** `http://{host}:{port}/v1`

The `/v1` prefix enables future API evolution. Version increments shall occur only for breaking changes to request or response schemas or endpoint semantics.

### Common Request Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Content-Type` | Yes | Must be `application/json` for all POST endpoints |
| `Accept` | No | Recommended: `application/json` |

### Common Response Headers

All responses include:

| Header | Description |
|--------|-------------|
| `Content-Type` | Always `application/json` |
| `X-Correlation-ID` | UUID v4 correlation identifier for request tracing |

### Endpoint: POST /v1/prompts/enhance

**Purpose:** Accept a natural language prompt and return an enhanced version optimised for text-to-image generation.

**HTTP Status Code Mapping:**

| Status | Condition | Retry Recommendation |
|--------|-----------|---------------------|
| 200 | Prompt enhanced successfully | N/A |
| 400 | Invalid request (malformed JSON or schema violation) | Do not retry — fix request |
| 502 | llama.cpp unavailable or returned an error | Retry with exponential backoff |
| 500 | Unexpected internal error | Retry with exponential backoff; escalate if persistent |

### Endpoint: POST /v1/images/generations

**Purpose:** Generate one or more images based on a natural language prompt, with optional prompt enhancement.

**HTTP Status Code Mapping:**

| Status | Condition | Retry Recommendation |
|--------|-----------|---------------------|
| 200 | Image(s) generated successfully | N/A |
| 400 | Invalid request (malformed JSON or schema violation) | Do not retry — fix request |
| 502 | Upstream unavailable (llama.cpp or Stable Diffusion) | Retry with exponential backoff |
| 500 | Unexpected internal error | Retry with exponential backoff; escalate if persistent |

### Endpoint: GET /health

**Purpose:** Report service operational status for load balancers and orchestrators.

**HTTP Status Code Mapping:**

| Status | Condition |
|--------|-----------|
| 200 | Service is operational |

**Response Body:** `{"status": "healthy"}`

### Endpoint: GET /health/ready

**Purpose:** Report readiness status including backend service initialisation checks. Used by Kubernetes readiness probes and load balancers to determine whether an instance can accept traffic.

**HTTP Status Code Mapping:**

| Status | Condition |
|--------|-----------|
| 200 | All backend services are initialised and ready |
| 503 | One or more backend services are unavailable or still loading |

**Response Body (200):** `{"status": "ready", "checks": {"image_generation": "ok", "language_model": "ok"}}`

**Response Body (503):** `{"status": "not_ready", "checks": {"image_generation": "unavailable", "language_model": "ok"}}`

### Endpoint: GET /metrics

**Purpose:** Expose request count and latency metrics in structured JSON format for operational monitoring (requirement 11).

**HTTP Status Code Mapping:**

| Status | Condition |
|--------|-----------|
| 200 | Metrics returned successfully |

**Response Body:**

```json
{
  "request_counts": {
    "POST /v1/prompts/enhance 200": 5,
    "POST /v1/images/generations 200": 3,
    "POST /v1/prompts/enhance 400": 1
  },
  "request_latencies": {
    "POST /v1/prompts/enhance": {
      "count": 6,
      "min_ms": 1.2,
      "max_ms": 450.3,
      "avg_ms": 120.5,
      "p95_ms": 430.1
    }
  }
}
```

---

## Technology Stack and Justification

The following technology stack is mandated for implementation. Each selection is explicitly justified for scalability, operational characteristics, and ecosystem maturity.

### Backend Language: Python 3.11+

**Justification:** Native ecosystem support for machine learning libraries (PyTorch, Diffusers, Transformers); excellent HTTP framework options with production-grade maturity (FastAPI); strong typing support via type hints; widespread industry adoption.

**Scalability considerations:** GIL limitations are mitigated by the I/O-bound nature of HTTP serving and model inference delegation. Multi-process deployment via uvicorn workers provides horizontal scalability within a single host.

### HTTP Server Framework: FastAPI 0.100+

**Justification:** Native async/await support for efficient I/O multiplexing; automatic request validation using Pydantic models; dependency injection system facilitating testability; standards-compliant HTTP implementation.

### Request Validation: Pydantic 2.0+

**Justification:** Type-safe request and response schema definition; automatic validation with detailed error messages; performance-optimised validation using Rust internals.

### HTTP Client for llama.cpp: httpx 0.24+

**Justification:** Async and sync API support; connection pooling for reduced TCP overhead; configurable timeouts for reliable failure detection.

### Stable Diffusion Integration: Diffusers 0.25+ (Hugging Face)

**Justification:** Official library for Stable Diffusion pipelines; optimised inference implementations; support for multiple model versions; active maintenance.

### Image Encoding: Pillow 10.0+

**Justification:** Industry-standard Python imaging library; efficient in-memory image manipulation; base64 encoding for JSON-embedded transport.

### Logging Framework: structlog 23.1+

**Justification:** Structured JSON logging with context binding for request correlation; processor chains for consistent log formatting; integration with standard library logging.

### Process Management for llama.cpp: Operating system process or Kubernetes Deployment

**Justification:** llama.cpp is deployed as a separate process managed by the operating system or by Kubernetes, providing process isolation, independent scaling, and automatic restart on failure.

---

## Component Architecture and Responsibilities

The service is structured as a three-layer architecture with unidirectional dependency flow.

### Layer 1: HTTP API Layer

**Responsibilities:** Accept and parse incoming HTTP requests; validate request structure via Pydantic models; route requests to appropriate application service handlers; serialise responses to JSON; map exceptions to HTTP status codes; inject correlation identifiers via middleware; log request and response metadata.

**Non-responsibilities:** Business logic execution; model invocation; error recovery strategies beyond HTTP-level error representation.

### Layer 2: Application Service Layer

**Responsibilities:** Implement business logic and workflow orchestration; coordinate interactions between integration layer components (invoke llama.cpp first, then Stable Diffusion when `use_enhancer` is `true`); apply business rules and constraints; emit structured logs for operational visibility.

**Non-responsibilities:** HTTP protocol concerns; direct model invocation; request or response serialisation.

### Layer 3: Model Integration Layer

**Responsibilities:** Manage HTTP connections to the llama.cpp server via httpx; load and cache the Stable Diffusion model pipeline; execute model inference; handle integration-specific errors and timeouts; translate between service abstractions and model-specific protocols.

**Non-responsibilities:** Business logic or workflow orchestration; HTTP request validation; deciding when to use enhancement.

### Dependency Flow

```
HTTP API Layer → Application Service Layer → Model Integration Layer
```

Dependencies flow strictly from left to right. No layer depends on a layer above it.

---

## Model Integration Specifications

### llama.cpp Integration

#### Deployment Configuration

llama.cpp is deployed as a separate process exposing an OpenAI-compatible HTTP API. CPU-only execution is mandated.

**Recommended invocation:**

```bash
./llama-server \
  --host 0.0.0.0 \
  --port 8080 \
  --model /models/llama-2-7b-chat.Q4_K_M.gguf \
  --ctx-size 2048 \
  --threads 4
```

**Configuration parameters:**

| Parameter | Purpose | Recommended Value |
|-----------|---------|-------------------|
| `--model` | Path to GGUF model file | Instruction-tuned model (e.g., Llama-2-7b-chat) |
| `--host` | Bind address | `0.0.0.0` |
| `--port` | HTTP port | `8080` |
| `--ctx-size` | Context window size | `2048` (sufficient for prompt enhancement) |
| `--threads` | CPU threads for inference | `4` (adjust based on available cores) |

#### API Endpoint Contract

**Endpoint:** `POST http://{llama_cpp_host}:{llama_cpp_port}/v1/chat/completions`

**Request format (OpenAI-compatible):**

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are an expert at enhancing text-to-image prompts. Transform the user's simple prompt into a detailed, visually descriptive prompt. Add artistic style, lighting, composition, and quality modifiers. Return only the enhanced prompt, nothing else."
    },
    {
      "role": "user",
      "content": "{user_prompt}"
    }
  ],
  "temperature": 0.7,
  "max_tokens": 512
}
```

**Expected response format:**

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "{enhanced_prompt_text}"
      }
    }
  ]
}
```

The service shall extract `choices[0].message.content` and strip leading and trailing whitespace.

#### Error Handling

| Failure Mode | Detection Method | Service Response |
|--------------|------------------|------------------|
| Server not running | Connection refused | HTTP 502, `upstream_service_unavailable` |
| Request timeout | No response within configured timeout (120 s) | HTTP 502, `upstream_service_unavailable` |
| Invalid response format | JSON parse failure or missing `choices` field | HTTP 502, `upstream_service_unavailable` |
| HTTP error from llama.cpp | 4xx or 5xx status code | HTTP 502, `upstream_service_unavailable` |

### Stable Diffusion Integration

#### Model Selection

**Recommended model:** `stable-diffusion-v1-5/stable-diffusion-v1-5`

**Justification:** Widely adopted reference model with extensive community testing and well-documented behaviour; moderate memory requirements; suitable for both CPU and GPU inference; compatible with the broadest range of deployment environments.

#### Pipeline Configuration

| Parameter | Value | Justification |
|-----------|-------|---------------|
| `torch_dtype` | `torch.float16` (CUDA) / `torch.float32` (CPU) | Half-precision on GPU reduces memory consumption and improves throughput; full precision is required on CPU where float16 is not hardware-accelerated |
| `safety_checker` | Configurable (default: enabled) | Controlled via `TEXT_TO_IMAGE_STABLE_DIFFUSION_SAFETY_CHECKER`; enabled by default for safe operation, can be disabled for performance in controlled environments where content moderation is handled externally |
| `attention_slicing` | Enabled | Reduces peak memory usage during inference on both CPU and GPU |
| `num_inference_steps` | `20` | Optimised for acceptable output quality with significantly reduced latency, particularly on CPU hardware |
| `guidance_scale` | `7.0` | Balanced prompt adherence without over-constraining the diffusion process |

---

## Error Handling and Recovery

### Error Classification

| HTTP Status | Category | Meaning | Retry Strategy |
|-------------|----------|---------|----------------|
| 400 | Client error | Invalid request syntax or schema violation | Never retry — fix request |
| 502 | Upstream failure | llama.cpp or Stable Diffusion unavailable | Retry with exponential backoff (base delay 1s, maximum 3 retries) |
| 500 | Internal error | Unexpected service failure | Retry with exponential backoff; escalate if persistent |

### Error Propagation Rules

1. JSON syntax errors are detected at the HTTP framework level and mapped to HTTP 400 with `invalid_request_json`.
2. Schema validation errors are detected by Pydantic and mapped to HTTP 400 with `request_validation_failed`.
3. llama.cpp connection failures (connection refused, timeout, HTTP error) are caught at the integration layer and mapped to HTTP 502 with `upstream_service_unavailable`.
4. Stable Diffusion failures (model loading, inference, out-of-memory) are caught at the integration layer and mapped to HTTP 502 with `model_unavailable`.
5. All other exceptions are caught by the global exception handler middleware and mapped to HTTP 500 with `internal_server_error`.

No exception shall propagate to the HTTP framework's default error handler, which would produce non-JSON responses.

---

## Configuration Requirements

All configuration shall be expressed exclusively as environment variables with fully descriptive names. Abbreviations in configuration names are not permitted. All environment variables use the prefix `TEXT_TO_IMAGE_` to prevent namespace collisions with other services or system-level variables in shared deployment environments. The implementation uses a Pydantic Settings model with `env_prefix="TEXT_TO_IMAGE_"`, which maps each field name to the corresponding prefixed environment variable automatically. A `.env` file is also supported for local development convenience.

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `TEXT_TO_IMAGE_APPLICATION_HOST` | HTTP bind address for the service | `127.0.0.1` | No |
| `TEXT_TO_IMAGE_APPLICATION_PORT` | HTTP bind port for the service | `8000` | No |
| `TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL` | Base URL of the llama.cpp server (OpenAI-compatible endpoint) | `http://localhost:8080` | No |
| `TEXT_TO_IMAGE_LANGUAGE_MODEL_REQUEST_TIMEOUT_SECONDS` | Maximum time in seconds to wait for a response from the llama.cpp server before treating the request as failed | `120` | No |
| `TEXT_TO_IMAGE_LANGUAGE_MODEL_TEMPERATURE` | Sampling temperature for prompt enhancement; higher values produce more creative output | `0.7` | No |
| `TEXT_TO_IMAGE_LANGUAGE_MODEL_MAX_TOKENS` | Maximum number of tokens the language model may generate for an enhanced prompt | `512` | No |
| `TEXT_TO_IMAGE_STABLE_DIFFUSION_MODEL_ID` | Hugging Face model identifier or local filesystem path for the Stable Diffusion pipeline | `stable-diffusion-v1-5/stable-diffusion-v1-5` | No |
| `TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE` | Inference device selection; `auto` selects CUDA when a compatible GPU is available, otherwise falls back to CPU; explicit values `cpu` and `cuda` are also supported | `auto` | No |
| `TEXT_TO_IMAGE_STABLE_DIFFUSION_INFERENCE_STEPS` | Number of diffusion inference steps per image; lower values reduce latency at the cost of output quality | `20` | No |
| `TEXT_TO_IMAGE_STABLE_DIFFUSION_GUIDANCE_SCALE` | Classifier-free guidance scale; higher values follow the prompt more closely | `7.0` | No |
| `TEXT_TO_IMAGE_STABLE_DIFFUSION_SAFETY_CHECKER` | Enable the NSFW safety checker (`true`/`false`); disabling removes content filtering from generated images | `true` | No |
| `TEXT_TO_IMAGE_STABLE_DIFFUSION_INFERENCE_TIMEOUT_PER_UNIT_SECONDS` | Base timeout (seconds) for generating one 512×512 image. The service scales automatically: `base × n_images × (w × h) / (512 × 512)`, with a 30× multiplier applied on CPU. GPU operators can usually leave the default; CPU operators on slow hardware should increase it. | `60` | No |
| `TEXT_TO_IMAGE_CORS_ALLOWED_ORIGINS` | Allowed CORS origins (JSON list); empty list disables CORS | `[]` | No |
| `TEXT_TO_IMAGE_LOG_LEVEL` | Minimum log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` | No |

**Startup validation:** Required configuration values shall be validated during service initialisation. Missing or invalid values shall cause startup failure with a clear, human-readable error message written to stderr and to structured logs.

**Runtime mutability:** Changes to configuration values take effect only on process restart. Hot-reload of configuration is not required.

---

## Logging and Observability

This section consolidates logging, metrics, and tracing expectations.

- **Structured logging:** All log output shall be JSON-formatted with the mandatory fields defined in requirement 9 (Structured Logging). Log entries shall be suitable for direct ingestion by log aggregation systems such as Elasticsearch, Splunk, or CloudWatch Logs.
- **Correlation and tracing:** Every HTTP request shall be associated with a unique correlation identifier as specified in requirement 26 (Correlation Identifier Injection).
- **Error logging:** Upstream failures shall produce ERROR-level log entries as specified in requirement 10 (Error Observability).
- **Metrics:** The service shall expose performance metrics as specified in requirement 11 (Performance Metrics Collection).

**Logging event taxonomy (normative):**

| Event Name | Level | Description |
|------------|-------|-------------|
| `http_request_received` | INFO | An HTTP request has been received |
| `http_request_completed` | INFO | An HTTP request has been processed and a response sent |
| `http_validation_failed` | WARNING | Request failed JSON syntax or schema validation |
| `prompt_enhancement_initiated` | INFO | llama.cpp invocation started |
| `prompt_enhancement_completed` | INFO | llama.cpp invocation completed successfully |
| `image_generation_initiated` | INFO | Stable Diffusion inference started |
| `image_generation_completed` | INFO | Stable Diffusion inference completed successfully |
| `stable_diffusion_pipeline_loading` | INFO | Stable Diffusion model download/load started |
| `stable_diffusion_pipeline_loaded` | INFO | Stable Diffusion model loaded and ready |
| `stable_diffusion_pipeline_released` | INFO | Stable Diffusion pipeline released on shutdown |
| `services_initialised` | INFO | All services initialised and ready to serve traffic |
| `services_shutdown_complete` | INFO | All services shut down gracefully |
| `llama_cpp_connection_failed` | ERROR | Failed to connect to llama.cpp server |
| `llama_cpp_http_error` | ERROR | llama.cpp returned a non-success HTTP status code |
| `llama_cpp_response_parsing_failed` | ERROR | llama.cpp response body could not be parsed |
| `llama_cpp_timeout` | ERROR | llama.cpp request timed out |
| `stable_diffusion_inference_failed` | ERROR | Stable Diffusion inference failed with a runtime error |
| `stable_diffusion_inference_timeout` | ERROR | Stable Diffusion inference exceeded the computed timeout |
| `upstream_service_error` | ERROR | An upstream service error was mapped to an HTTP error response |
| `unexpected_exception` | ERROR | An unhandled exception was caught by global handler |

---

## Security Considerations

This specification assumes a primarily local or controlled network deployment. Upstream concerns such as authentication, authorisation, rate limiting, and TLS are explicitly delegated to an upstream API gateway or reverse proxy.

- **Trust boundary:** Requests are assumed to originate from trusted clients or from an upstream gateway that has already performed authentication. The service focuses on strict input validation and error sanitisation.
- **Transport security:** TLS termination is handled by the ingress or gateway layer. Internal HTTP communication (between the API Service and llama.cpp) may occur over plain HTTP within a trusted network segment.
- **Input validation:** All user-provided input is validated against JSON schemas before processing (requirement 12).
- **Error sanitisation:** No internal implementation details are exposed in HTTP error responses (requirement 13).
- **Local execution:** llama.cpp and Stable Diffusion run on localhost or within a trusted cluster, reducing external attack surface.

---

## Scalability and Future Extension Considerations

### Horizontal Scaling Model

The service is designed for horizontal scaling via stateless instance replication behind a load balancer. Key design decisions supporting this model:

1. **No shared state:** Each request is self-contained; no session data, caches, or shared storage are required between instances.
2. **No session affinity:** Load balancers can distribute requests using round-robin or least-connections strategies without sticky sessions.
3. **Independent scaling of components:** The Text-to-Image API Service and the llama.cpp server can be scaled independently based on their respective resource utilisation patterns.

### Failure Isolation Strategies

1. **Process isolation:** llama.cpp runs as a separate process. A crash or memory leak in llama.cpp does not terminate the API service.
2. **Timeout enforcement:** All upstream HTTP calls have bounded timeouts preventing resource exhaustion.
3. **Graceful degradation:** Image generation without enhancement continues to function when llama.cpp is unavailable.

### Future Extensibility Pathways

1. **GPU acceleration:** The service architecture supports automatic GPU detection via the `TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE` configuration variable. The default value `auto` automatically selects CUDA when a compatible GPU is available, otherwise falling back to CPU. Explicit values `cpu` and `cuda` are also supported for deterministic device selection. When CUDA is active, the pipeline automatically uses `torch.float16` for reduced memory consumption and improved inference throughput. No code changes are required for this transition.
2. **Additional image models:** The model integration layer can be extended to support alternative image generation models (for example, SDXL, DALL-E) by implementing the same integration interface.
3. **Additional prompt enhancement models:** The llama.cpp client can be pointed at any OpenAI-compatible completion server, enabling model upgrades or replacements without service code changes.
4. **Asynchronous generation:** For high-latency operations, a future version could introduce an asynchronous job-based API pattern returning a job identifier and a polling endpoint.
5. **Persistent image storage:** Generated images could be stored in object storage (for example, S3 or MinIO) with URL references returned instead of base64 payloads, reducing response sizes for multi-image requests.

---

## Infrastructure Definition

### Local Deployment (Evaluation Environment)

For hiring panel evaluation, the service runs on a single machine with the following process topology:

1. **llama.cpp server process:** Listening on port 8080
2. **Text-to-Image API Service process:** Listening on port 8000, communicating with llama.cpp on localhost:8080

No containerisation or Kubernetes is required for local evaluation. The service can be run directly using `uvicorn`.

### Kubernetes Deployment (Production Reference)

For production or scaled deployment, the following Kubernetes resources are defined:

- **Namespace:** `text-to-image-service`
- **Deployment: `text-to-image-api`** — 3 replicas minimum, 10 replicas maximum, with HorizontalPodAutoscaler
- **Deployment: `llama-cpp-server`** — 2 replicas minimum
- **Service: `text-to-image-api-service`** — type LoadBalancer, port 80 → targetPort 8000
- **Service: `llama-cpp-service`** — type ClusterIP, port 8080 → targetPort 8080
- **HorizontalPodAutoscaler:** Target CPU utilisation 70%, memory utilisation 80%
- **PersistentVolumeClaims:** For model file storage (Stable Diffusion cache and llama.cpp model files)

---

## CI/CD Pipeline Requirements

This section defines the continuous integration and continuous deployment pipeline expectations for the Text-to-Image API Service. These requirements ensure that code changes are validated automatically before deployment.

### Continuous Integration

**Trigger:** Every commit pushed to the main branch or to an open pull request branch shall trigger the CI pipeline.

**Pipeline stages:**

1. **Dependency installation:** Install all Python dependencies from `requirements.txt` into an isolated virtual environment.
2. **Linting and static analysis:** Run code quality checks (for example, `ruff` or `flake8`) to enforce style consistency and detect common errors.
3. **Unit and integration tests:** Execute the full `pytest` test suite with coverage measurement. The pipeline shall fail if any test fails or if code coverage falls below the target defined in the Testing Requirements section.
4. **Schema validation:** Verify that all API request and response models are consistent with the JSON schemas defined in the Data Model and Schema Definition section.

### Continuous Deployment

**Trigger:** Successful completion of the CI pipeline on the main branch.

**Pipeline stages:**

1. **Container image build:** Build a container image containing the service, its dependencies, and the Python runtime.
2. **Image tagging:** Tag the container image with the Git commit SHA and, for tagged releases, the semantic version number.
3. **Registry push:** Push the tagged image to the designated container registry.
4. **Deployment:** Apply the updated image reference to the Kubernetes Deployment manifest and trigger a rolling update.

### Pipeline Non-Functional Expectations

- The CI pipeline (stages 1–4) shall complete within 10 minutes on standard CI runner hardware.
- Pipeline failures shall produce clear, human-readable error messages identifying the failing stage and the specific error.
- Pipeline configuration shall be version-controlled alongside the application source code.

---

## Testing Requirements

### Unit Testing

**Framework:** pytest
**Coverage target:** ≥ 80%
**Scope:** Application service layer logic, request schema validation, error handling, response serialisation.

### Integration Testing

**Scope:** Verify service interactions with llama.cpp (HTTP client behaviour, timeout handling, error mapping) and Stable Diffusion (pipeline loading, inference execution, image encoding).

### Contract Testing

**Scope:** Validate that API endpoints conform to the JSON schemas defined in the Data Model and Schema Definition section. Verify all error codes, response structures, and HTTP status codes match this specification.

### End-to-End Testing

**Scope:** Execute all reference operations (RO1–RO6) against a fully deployed service and verify all success criteria are met.

---

## Specification Governance and Evolution

### Versioning Policy

All normative changes to requirements, reference operations, or API contracts shall result in a minor or major version increment. Purely editorial clarifications that do not alter behaviour may be released as patch versions.

### Compatibility Rules

Any change that modifies request or response schemas, error codes, or non-functional targets in a way that could break existing clients shall be considered backwards-incompatible and must trigger a major version increment. Additive, backwards-compatible changes (for example, new optional fields) require a minor version increment with updated JSON schema definitions and test procedures.

### Change Control

Proposed changes shall be captured as tracked issues referencing specific FR, NFR, and RO identifiers. Each change proposal shall include updated requirement statements, modified test procedures, and revised success criteria.

### Approval Workflow

Changes become effective only after review and approval by a designated Specification Authority or equivalent senior engineering panel.

### Traceability Maintenance

When new FRs, NFRs, or ROs are introduced, the Requirements Traceability Matrix must be updated in the same change set so that no requirement or reference operation remains unlinked.

### Deprecation Process

Deprecated behaviours or endpoints shall be clearly marked within the relevant requirement sections, with a defined deprecation period and a specified replacement. Removing deprecated behaviour requires a major version increment.

---

## README (Implementation and Execution Guide)

### Environment Prerequisites

- **Operating system:** Linux, macOS, or Windows with WSL2
- **Python:** Version 3.11 or later, available on the `PATH`
- **Tools:** `git`, `curl`, `jq`, and `base64` installed
- **System resources:** Minimum 8 GB RAM, minimum 4 CPU cores
- **Network access:** Required to download Python packages and model weights on first run

### Setup Steps

1. **Clone the repository** or unpack the candidate's submission directory.

2. **Create and activate a Python virtual environment:**

```bash
python -m venv .venv
source .venv/bin/activate
```

3. **Install Python dependencies:**

```bash
pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt
```

4. **Prepare model files:**
   - The Stable Diffusion model (for example, `stable-diffusion-v1-5/stable-diffusion-v1-5`) will be downloaded automatically by the Diffusers library on first use.
   - A llama.cpp model file (for example, `llama-2-7b-chat.Q4_K_M.gguf`) must be downloaded separately and placed in a known directory.

### Running llama.cpp as an OpenAI-Compatible HTTP Server

```bash
./llama-server \
  --host 0.0.0.0 \
  --port 8080 \
  --model /path/to/llama-2-7b-chat.Q4_K_M.gguf \
  --ctx-size 2048 \
  --threads 4
```

Verify the server is running:

```bash
curl http://localhost:8080/health
```

### Running the Text-to-Image API Service

```bash
export TEXT_TO_IMAGE_APPLICATION_PORT=8000
export TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL=http://localhost:8080
export TEXT_TO_IMAGE_STABLE_DIFFUSION_MODEL_ID=stable-diffusion-v1-5/stable-diffusion-v1-5
export TEXT_TO_IMAGE_LOG_LEVEL=INFO

uvicorn main:fastapi_application --host 0.0.0.0 --port 8000
```

Verify the service is running:

```bash
curl http://localhost:8000/health
```

Expected response: `{"status": "healthy"}`

### Example curl Commands

**1. Prompt Enhancement:**

```bash
curl -X POST http://localhost:8000/v1/prompts/enhance \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a cat sitting on a windowsill"}'
```

**2. Image Generation without Enhancement:**

```bash
curl -X POST http://localhost:8000/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "a serene mountain landscape at sunset, vibrant colours, photorealistic",
    "use_enhancer": false,
    "n": 1,
    "size": "512x512"
  }' -o response.json
```

To decode the generated image:

```bash
cat response.json | jq -r '.data[0].b64_json' | base64 -d > generated_image.png
```

**3. Image Generation with Enhancement:**

```bash
curl -X POST http://localhost:8000/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "a futuristic cityscape",
    "use_enhancer": true,
    "n": 2,
    "size": "512x512"
  }' -o response_enhanced.json
```

---

## Appendices

### Appendix A: Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `TEXT_TO_IMAGE_APPLICATION_HOST` | HTTP bind address for the service | `127.0.0.1` | No |
| `TEXT_TO_IMAGE_APPLICATION_PORT` | HTTP bind port for the service | `8000` | No |
| `TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL` | Base URL of the llama.cpp server | `http://localhost:8080` | No |
| `TEXT_TO_IMAGE_LANGUAGE_MODEL_PATH` | Path to GGUF model file (reference only, not used at runtime) | *(empty)* | No |
| `TEXT_TO_IMAGE_LANGUAGE_MODEL_REQUEST_TIMEOUT_SECONDS` | Maximum time in seconds to wait for a llama.cpp response | `120` | No |
| `TEXT_TO_IMAGE_LANGUAGE_MODEL_TEMPERATURE` | Sampling temperature for prompt enhancement | `0.7` | No |
| `TEXT_TO_IMAGE_LANGUAGE_MODEL_MAX_TOKENS` | Maximum tokens the language model may generate | `512` | No |
| `TEXT_TO_IMAGE_STABLE_DIFFUSION_MODEL_ID` | Hugging Face model identifier or local path | `stable-diffusion-v1-5/stable-diffusion-v1-5` | No |
| `TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE` | Inference device (`auto`, `cpu`, or `cuda`) | `auto` | No |
| `TEXT_TO_IMAGE_STABLE_DIFFUSION_INFERENCE_STEPS` | Number of diffusion inference steps | `20` | No |
| `TEXT_TO_IMAGE_STABLE_DIFFUSION_GUIDANCE_SCALE` | Classifier-free guidance scale | `7.0` | No |
| `TEXT_TO_IMAGE_STABLE_DIFFUSION_SAFETY_CHECKER` | Enable NSFW safety checker (`true`/`false`) | `true` | No |
| `TEXT_TO_IMAGE_CORS_ALLOWED_ORIGINS` | Allowed CORS origins (JSON list) | `[]` | No |
| `TEXT_TO_IMAGE_LOG_LEVEL` | Minimum log level | `INFO` | No |

### Appendix B: Document Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 16 Feb 2026 | Initial specification |
| 2.0.0 | 16 Feb 2026 | Restructure with testable requirements |
| 2.1.0 | 16 Feb 2026 | Added architectural principles, implementation guidance, and code examples; enhanced error handling |
| 3.0.0 | 16 Feb 2026 | Enterprise-grade rewrite: added glossary; formalised all requirements with intent, step-by-step test procedures, and measurable success criteria; added complete requirements traceability matrix; added requirement categorisation and section creation guides; replaced informal JSON examples with JSON Schema definitions with field-level validation rules; added transient fault handling (RO6); standardised linguistic consistency (British English, consistent verb usage); added specification governance and evolution framework; aligned with Weather Data App reference specification rigour |
| 3.1.0 | 18 Feb 2026 | Aligned specification with implementation where the implementation was demonstrably superior: adopted `TEXT_TO_IMAGE_` environment variable prefix for namespace isolation; introduced automatic device detection (`auto` default for `TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE` with dynamic `torch.float16`/`torch.float32` selection); increased upstream request timeout default from 30 to 120 seconds to accommodate CPU-based large language model inference; updated default Stable Diffusion model to `stable-diffusion-v1-5/stable-diffusion-v1-5`; reduced default inference steps from 50 to 20 and guidance scale from 7.5 to 7.0 for improved CPU latency; increased `max_tokens` from 200 to 512 for richer prompt enhancement output; corrected Uvicorn application reference to `main:fastapi_application`; all environment variable names now use fully descriptive, unabbreviated identifiers consistent with the implementation's Pydantic Settings model; added CI/CD Pipeline Requirements section (previously referenced in Table of Contents but absent from document body) |
| 3.2.0 | 19 Feb 2026 | Observability alignment: adopted structlog as the structured logging library (NFR9); added normative logging event taxonomy with 11 mandatory events; added `GET /metrics` endpoint for in-memory performance metrics (NFR11); added `GET /health/ready` readiness endpoint (FR30); expanded configuration tables with 6 additional environment variables (`LANGUAGE_MODEL_PATH`, `LANGUAGE_MODEL_TEMPERATURE`, `LANGUAGE_MODEL_MAX_TOKENS`, `STABLE_DIFFUSION_GUIDANCE_SCALE`, `STABLE_DIFFUSION_SAFETY_CHECKER`, `CORS_ALLOWED_ORIGINS`); corrected `APPLICATION_HOST` default from `0.0.0.0` to `127.0.0.1`; added readiness and metrics endpoint definitions to API Contract section; updated requirements traceability matrix with FR30 |

---

## END OF SPECIFICATION

This specification is approved for implementation and hiring panel evaluation.
