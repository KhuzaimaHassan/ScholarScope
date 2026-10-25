# Provider-neutral structured generation

`scholarscope.llm` uses plain httpx, never vendor SDKs. This keeps wire formats,
timeouts, redaction and tests explicit. No dependency was added. Only mocked
synthetic responses were used; the manual smoke script was **not run**.

## Interface and trust boundary

`StructuredRequest` is a frozen generic dataclass: trusted `system` and `task`,
`untrusted_passages=((passage_id, text), ...)`, a Pydantic model class,
prompt_version, temperature (finite 0–2, default 0), and positive
max_output_tokens (default 2048). Empty tasks/versions, invalid models/parameters
or passage shapes raise ValueError with fixed messages, not input dumps.

`render_user_message(task, passages)` alone renders the task and labeled data
blocks. It preserves passage text exactly, keeps system/task separate, and says
the blocks are untrusted data. These simple delimiters are **not** an injection
defense: hostile text may contain delimiters. Stronger hardening remains #21.
Callers must never interpolate page content into trusted system/task strings.

`LLMClient.generate_structured(request)` returns a frozen
`StructuredResponse[T]`: status, parsed or null, last raw_text or null, attempts,
provider, configured model, prompt_version, usage, cached, sanitized error.
`close()` releases an internally owned HTTP client; injected clients stay owned
by their caller. Responses omit raw_text/parsed from repr to avoid accidental
logging. Valid model garbage and provider failures return statuses, not errors
that expose HTTP bodies, headers, keys or Pydantic input details.

| Status | Meaning |
|---|---|
| ok | Pydantic validated the returned text (also revalidated on every cache hit) |
| invalid_output | Model text still fails JSON/Pydantic validation after bounded attempts; last raw_text retained privately |
| provider_error | HTTP/transport/envelope failure, schema rejection, credential echo, or exhausted fake script; sanitized error only |
| unavailable | Read-only cache miss/invalid entry, missing credential, or unsupported Gemini schema keywords; no provider call |

Presence/support and eligibility are not inferred here. #19 owns extraction,
field grouping, provider-result orchestration, and resetting all verification
to `not_checked`; only the deterministic verifier can promote it (ADR 010/012).
No labels, snapshots, schema.py or existing ADRs are changed by this package.

## Validation, retry, and usage

Pydantic **always** validates returned text, even when a provider promises strict
schema enforcement. Never repair model JSON or strip code fences. Invalid JSON
or schema validation adds a short generic failure note to the next user message;
model input/output and validation details are not repeated. max_attempts defaults
to **3 model-output attempts** (two retries), configurable on the client.

Each output attempt permits at most **3 transport sends** on timeout/connection
errors, HTTP 429 or 5xx. Backoff is 1, then 2 seconds plus uniform [0,1] jitter;
Retry-After seconds or HTTP-date is a lower bound. Sleeper, rng and date clock
are injectable; mocked tests never sleep. No HTTP 400/401/403 retry; in particular
a schema-rejection 400 is terminal provider_error, never an automatic downgrade.
Redirects are not followed, so credentials cannot be forwarded to another host.

`attempts` counts actual sends across both retry layers (at most 9 at defaults);
cache hits/misses in read_only use zero. Usage contains the last completion's
input/output token counts, nullable if absent/malformed, **not aggregate retry
cost or billing**. Gemini candidate counts do not include thinking-token usage.

## Cache and secrets

FileCache defaults to private, git-ignored `.cache/llm/`. Its SHA-256 key covers
canonical JSON of provider, model, system, task, ordered passage IDs/text, full
response schema, temperature, max_output_tokens and prompt_version. No prompt,
headers or key is written; files contain **only raw_text and usage**. Treat these
outputs as private source-derived data, not material to publish. Writes are
atomic. Only locally validated ok responses can enter the cache. Cache failure
does not discard an otherwise valid response (ok with a fixed warning).

- read_write: validated hit avoids provider; missing/corrupt/model-invalid entry
  can be refreshed. Returned cached text is always revalidated.
- read_only: miss/corruption/validation failure returns unavailable without a
  provider call, even with credentials configured; intended for eval replay.
- off: no file reads, writes or directory creation.

Config credentials are SecretStr, excluded from repr/str and model_dump (including
JSON mode). Errors use fixed messages/status codes, never response bodies or
exception strings. Known credential echoes in model output are rejected before
exposure or caching. Package code does not log keys, headers, requests or raw
responses. Do not enable third-party wire logging that dumps headers yourself.

## Environment configuration

`LLMConfig.from_env()` reads an explicit environment allowlist and validates it
with Pydantic; no pydantic-settings/dotenv dependency or automatic `.env` loading.
`build_client(config)` selects the provider without changing callers. Optional
constructor/builder arguments inject HTTP clients, cache directories and retry
settings for tests. Keep credentials in your shell/secret manager, never code.
`.env.example` has empty credential placeholders; `.env` and `.cache/` are ignored.

| Variable | Default / meaning |
|---|---|
| LLM_PROVIDER | fake; gemini, groq, ollama or fake |
| LLM_MODEL | fake-v1; explicitly set a compatible provider model when changing provider |
| GEMINI_API_KEY / GROQ_API_KEY | unset; required for live calls, not cache replay |
| OLLAMA_BASE_URL | http://localhost:11434; HTTP(S), no embedded auth/query/fragment |
| LLM_TIMEOUT_SECONDS | 30, positive and finite |
| LLM_CACHE_MODE | read_write; read_only or off also supported |

FakeClient consumes scripted raw strings per model-output attempt and records
each high-level request. It shares validation/retry/cache behavior without HTTP,
sleeping or randomness. Exhaustion returns a sanitized provider_error; it does
not fabricate a generic response for an unknown response model.

## Official wire formats checked 2026-10-25

- **Gemini:** [Generating content / GenerationConfig](https://ai.google.dev/api/generate-content)
  and [Generate Content structured outputs](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).
  POST v1beta/models/{model}:generateContent, x-goog-api-key header,
  systemInstruction/contents, responseJsonSchema + responseMimeType application/json,
  temperature/maxOutputTokens; candidates[].content.parts[].text and
  usageMetadata.promptTokenCount/candidatesTokenCount. Never responseSchema.
- **Groq:** [Structured Outputs](https://console.groq.com/docs/structured-outputs)
  and [Chat API reference](https://console.groq.com/docs/api-reference).
  POST openai/v1/chat/completions, Bearer header, messages, max_completion_tokens,
  temperature, response_format; choices[].message.content and
  usage.prompt_tokens/completion_tokens. Strict json_schema is **model-limited**:
  the documented model sets are isolated in groq.py and need maintenance. On a
  supported model, use strict only when every object forbids additional properties
  and requires all properties; otherwise use best-effort json_schema unchanged.
  Other models select json_object **before sending**, with explicit JSON/schema
  instructions in the user message and the same local validation/retries. A 400
  never causes fallback. This is not a promise of support for arbitrary models.
- **Ollama:** [Chat endpoint](https://docs.ollama.com/api/chat),
  [Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs),
  [Modelfile parameters](https://docs.ollama.com/modelfile).
  Local POST /api/chat with messages, schema-valued format, stream=false,
  options.temperature/num_predict; message.content, prompt_eval_count/eval_count.
  The cited structured-output docs exclude Ollama Cloud; this adapter targets
  local Ollama, not its cloud service.

### Schema limits: explicit refusal, never silent stripping

Gemini's API reference lists a supported keyword subset. The adapter checks
schema objects (not property names or enum values) against that list. Unknown
keywords return unavailable before HTTP; the original schema is never mutated.
Tests assert outgoing schemas contain only supported keywords and that local
refusal prevents sending minLength/maxLength/pattern/default/const/discriminator
and exclusiveMinimum, rather than quietly discarding them.

The current **RequirementRecord.model_json_schema()** contains `$defs`/`$ref`, many
enums and deep nested shapes. It currently also contains `const`, `default`,
`discriminator`, `maxLength`, `minLength` and `pattern`, which trigger this Gemini
guard. Even keyword-compatible models may exceed a provider's schema-complexity
limits; recursive references have provider-specific restrictions. **Issue #19
may need smaller, explicitly designed field-group response models**, followed
by validation against the unchanged RequirementRecord. Do not silently weaken
the canonical schema or treat a provider's constrained decoding as evidence
verification. HTTP 400 schema rejection remains a sanitized terminal error.

## Adding a provider and manual smoke

Subclass BaseClient and isolate endpoint, headers, payload, extraction and
capability checks in the adapter. Verify current official docs, add synthetic
MockTransport request/response and failure cases, then add the config factory
selection. The common engine owns validation, retries and caching. LLM tests
block real socket/DNS connections and use only dummy credential markers.

The owner may export configuration and run `python scripts/llm_smoke.py` manually.
It sends one tiny structured request (subject to the same bounded retries), then
prints provider, model, status, usage and latency only. It never prints request
headers, credentials or model text. **It was not run during this task.**
