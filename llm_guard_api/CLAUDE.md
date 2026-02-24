# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Structure

This is the **API deployment layer** (`llm_guard_api/`) within a monorepo. The core scanner library lives at `../llm_guard/`. Tests live at `../tests/`. Documentation: https://protectai.github.io/llm-guard/

## Common Commands

### Run the API locally
```bash
# From llm_guard_api/
make run-uvicorn
# Or directly:
uvicorn app.app:create_app --host=0.0.0.0 --port=8000 --workers=1
# With gunicorn (multi-worker, shared model memory):
gunicorn --workers 1 --preload --worker-class uvicorn.workers.UvicornWorker
```

### Install dependencies
```bash
# API with CPU optimizations (from llm_guard_api/)
make install  # equivalent to: pip install ".[cpu]"
# GPU: pip install ".[gpu]"

# Core library dev dependencies (from repo root)
pip install ".[dev]"
```

### Run tests (from repo root, not llm_guard_api/)
```bash
python -m pytest --exitfirst --verbose --failed-first --cov=. --color=yes
# Single test file:
python -m pytest tests/input_scanners/test_anonymize.py -v
```

### Lint and format (from repo root)
```bash
ruff check --fix .
ruff format .
pyright
```

Pre-commit hooks: `ruff check`, `ruff format`, `pyright`, `gitleaks`, `markdownlint`.

### Docker
```bash
make run-docker       # CPU
make run-docker-cuda  # GPU with CUDA
# Official image: docker pull laiyer/llm-guard-api:latest
```

## Architecture

### App module (`app/`)

- **`app.py`** — FastAPI app factory (`create_app()`). Loads config, initializes scanners, registers all routes. Two execution modes:
  - `/analyze/*` — Sequential scanner execution with sanitization (uses core `scan_prompt`/`scan_output`)
  - `/scan/*` — Parallel async execution returning risk scores only (no sanitization)
- **`scanner.py`** — Scanner loading and async execution. Maps scanner names to model configurations, enables ONNX by default. `_configure_model()` handles custom model paths/batch sizes. `InputIsInvalid` exception signals scan failures.
- **`config.py`** — Pydantic config models + YAML loader with `${ENV_VAR:default}` interpolation. Config loaded from `CONFIG_FILE` env var (default: `./config/scanners.yml`).
- **`schemas.py`** — Pydantic request/response models for all endpoints.
- **`otel.py`** — OpenTelemetry tracing and metrics setup (OTEL HTTP, Prometheus, AWS X-Ray, console).
- **`util.py`** — Structured logging config and resource utilization monitoring (psutil).

### Scanner system

Scanners are the core abstraction. They are dynamically loaded by name from `config/scanners.yml`:

- **Input scanners**: `scan(prompt) -> (sanitized_prompt, is_valid, risk_score)`
- **Output scanners**: `scan(prompt, output) -> (sanitized_output, is_valid, risk_score)`

Scanner implementations live in the core library (`../llm_guard/input_scanners/` and `../llm_guard/output_scanners/`). The API layer (`app/scanner.py`) wraps them with model configuration, ONNX enablement, and async execution.

The `Vault` object connects Anonymize (input) and Deanonymize (output) scanners — it stores anonymization mappings so placeholders like `[REDACTED_PERSON_1]` can be reversed in output.

### Adding a custom scanner

1. Create class in `llm_guard/input_scanners/` (or `output_scanners/`) inheriting from `base.Scanner`
2. Implement `scan()` returning `(str, bool, float)`
3. Add tests in `tests/input_scanners/` (or `tests/output_scanners/`)
4. Register in `__init__.py` `__all__` enum
5. Add scanner name mapping in `app/scanner.py` (`_get_input_scanner` / `_get_output_scanner`)

### Configuration

`config/scanners.yml` controls everything: app settings, auth, rate limiting, tracing/metrics, and which scanners to load with what parameters. See `config/scanners.yml.old` for a comprehensive example with all scanner types. Scanners execute in the order listed.

Key env vars: `LOG_LEVEL`, `SCAN_FAIL_FAST`, `SCAN_PROMPT_TIMEOUT` (default 10s), `SCAN_OUTPUT_TIMEOUT` (default 30s), `LAZY_LOAD`, `AUTH_TOKEN`, `APP_PORT` (default 8000).

### API endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/analyze/prompt` | POST | Sequential scan + sanitize prompt |
| `/analyze/output` | POST | Sequential scan + sanitize output |
| `/scan/prompt` | POST | Parallel scan prompt (risk scores only) |
| `/scan/output` | POST | Parallel scan output (risk scores only) |
| `/healthz` | GET | Health check |
| `/readyz` | GET | Readiness check |
| `/metrics` | GET | Prometheus metrics (if enabled) |

All scan/analyze endpoints accept `scanners_suppress` to skip specific scanners per-request.

## Scanner Reference

### Input Scanners

| Scanner | Purpose | Model/Engine | ML? |
|---|---|---|---|
| **Anonymize** | PII detection & redaction (names, emails, IPs, SSNs, credit cards, etc.) | Presidio + DeBERTa ai4privacy | Yes |
| **BanCode** | Block code in prompts | vishnun/codenlbert-sm | Yes |
| **BanCompetitors** | Block competitor name mentions | guishe/nuner-v1_orgs (NER) | Yes |
| **BanSubstrings** | Block specific strings/words | Built-in string matching | No |
| **BanTopics** | Block specific topics | Zero-shot DeBERTa classifier | Yes |
| **Code** | Detect/allow specific programming languages | philomath-1209/programming-language-identification | Yes |
| **EmotionDetection** | Block prompts with specific emotions | ML classifier | Yes |
| **Gibberish** | Filter nonsensical text | madhurjindal/autonlp-Gibberish-Detector | Yes |
| **InvisibleText** | Remove hidden Unicode characters (steganography attacks) | Unicode category filtering | No |
| **Language** | Enforce allowed languages | papluca/xlm-roberta-base-language-detection | Yes |
| **PromptInjection** | Detect prompt injection attacks | ProtectAI/deberta-v3-base-prompt-injection-v2 | Yes |
| **Regex** | Match/block/redact by regex patterns | Built-in regex | No |
| **Secrets** | Detect API keys, tokens, private keys | detect-secrets (Yelp) | No |
| **Sentiment** | Filter by sentiment score | NLTK VADER | No |
| **TokenLimit** | Enforce token count limits | tiktoken | No |
| **Toxicity** | Detect toxic/harmful content | unitary/unbiased-toxic-roberta | Yes |

### Output Scanners

All input scanners above are also available as output scanners, plus:

| Scanner | Purpose | Model/Engine |
|---|---|---|
| **Bias** | Detect biased content | valurank/distilroberta-bias |
| **Deanonymize** | Restore anonymized values from Vault | Vault data structures |
| **FactualConsistency** | Detect contradictions via NLI | deberta-v3-base-zeroshot (entailment/contradiction) |
| **JSON** | Validate and repair JSON output | json_repair library |
| **LanguageSame** | Ensure output language matches input | xlm-roberta-base-language-detection |
| **MaliciousURLs** | Detect phishing/malware URLs | DunnBC22/codebert-base-Malicious_URLs |
| **NoRefusal** | Detect model refusal responses | ProtectAI/distilroberta-base-rejection-v1 |
| **ReadingTime** | Enforce max reading time, optional truncation | Word count heuristic (200 wpm) |
| **Relevance** | Ensure output is relevant to prompt | BAAI/bge embedding + cosine similarity |
| **Sensitive** | Detect PII leakage in output | Same as Anonymize (Presidio + DeBERTa) |
| **URLReachability** | Verify URLs are accessible | HTTP requests |

### NIST attack categories covered

- **Availability**: TokenLimit (DoS prevention)
- **Integrity**: PromptInjection, Language, LanguageSame, Relevance, FactualConsistency, BanTopics
- **Privacy**: Anonymize, Sensitive, Secrets
- **Abuse**: Bias, Toxicity, BanCompetitors

## Key Details

- Python >=3.10,<3.13. Ruff line length: 100. Current version: 0.3.16.
- `torch.set_num_threads(1)` is set in `scanner.py` — intentional for multi-worker deployment.
- Scanners that use ML models default to `use_onnx=True` in the API layer for performance (significant speedup, e.g. PromptInjection: ~50K QPS with ONNX vs ~4.7K without on GPU).
- Lazy loading (`lazy_load: true` in config) defers scanner initialization until first request.
- `scan_fail_fast` mode stops scanning after the first failure.
- Auth supports `http_bearer` or `http_basic` via config.
- Minimum 16GB RAM recommended during startup when loading multiple scanners.
- Models are downloaded from HuggingFace on first use. Use `model_path` in scanner config to load from disk instead (set `local_files_only: True`).
- `low_cpu_mem_usage` can be set in model kwargs to reduce memory consumption.
- OpenAPI/Swagger UI only available when `log_level: DEBUG`.
