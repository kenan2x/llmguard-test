# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bu proje **LLM Guard API**'nin kurumsal bir fork'udur. Amac: Turkce PII maskeleme, dahili varlik (VM, hostname, DB) maskeleme ve tamamen **offline calisabilen** bir Docker image uretmek. Hedef ortam internet erisimi olmayan Linux x64 sunuculardır.

**GitHub:** https://github.com/kenan2x/llmguard-test

## Repository Structure

Monorepo yapisi:

```
llm-guard/                          # Repo root (Docker build context)
├── llm_guard/                      # Core scanner library (upstream + custom modifications)
│   ├── input_scanners/
│   │   ├── __init__.py             # MODIFIED: DynamicLookup eklendi
│   │   ├── dynamic_lookup.py       # NEW: Dahili varlik maskeleme scanner'i
│   │   ├── util.py                 # MODIFIED: DynamicLookup icin get_scanner_by_name guncellendi
│   │   └── anonymize_helpers/
│   │       └── regex_patterns.py   # MODIFIED: Turkce PII pattern'leri eklendi
│   └── output_scanners/
├── llm_guard_api/                  # API deployment layer (ana calisma dizini)
│   ├── app/
│   │   ├── app.py                  # FastAPI app factory + asset routes + web UI mount
│   │   ├── scanner.py              # Scanner yukleyici (TR Anonymize, mDeBERTa, placeholder koruma)
│   │   ├── config.py               # Pydantic config + YAML loader + dynamic_lookup config
│   │   ├── db.py                   # NEW: SQLite asset store (CachedAssetStore)
│   │   ├── routes_assets.py        # NEW: CRUD API routes for masked assets
│   │   ├── schemas.py              # Request/response models (entity_types_suppress eklendi)
│   │   ├── otel.py                 # OpenTelemetry setup
│   │   └── util.py                 # Logging + resource monitoring
│   ├── config/
│   │   ├── scanners.yml            # AKTIF config (Secrets, DynamicLookup, Anonymize TR, Regex, Deanonymize)
│   │   └── scanners.yml.old        # Eski/ornek config (tum scanner tipleri)
│   ├── web/
│   │   └── index.html              # Tek sayfa Web UI (maskeleme test + varlik yonetimi)
│   ├── data/
│   │   └── masked_assets.db        # SQLite DB (gitignore'da, volume mount noktasi)
│   ├── Dockerfile.offline          # Offline Docker image (multi-stage, 22 model icinde)
│   ├── download_models.py          # HuggingFace model indirici (build sirasinda calisir)
│   ├── Dockerfile                  # Orijinal Dockerfile (online, model indirmez)
│   ├── entrypoint.sh               # Uvicorn baslatici
│   ├── pyproject.toml              # Python dependencies
│   └── README-offline-docker.md    # Offline deploy dokumantasyonu
├── .dockerignore                   # Docker build context filtreleme
├── README.md                       # Offline deploy dokumantasyonu (kok dizin kopyasi)
└── tests/                          # Test suite (upstream)
```

## Yapilan Ozellesirmeler (Upstream'den Farklar)

Bu repo protectai/llm-guard upstream'inin fork'udur. Asagidaki dosyalar degistirilmis veya yeni eklenmistir:

### Yeni Dosyalar
| Dosya | Aciklama |
|-------|----------|
| `llm_guard/input_scanners/dynamic_lookup.py` | DynamicLookup scanner — SQLite'dan okunan dahili varlik isimlerini maskeler |
| `llm_guard_api/app/db.py` | SQLiteAssetStore + CachedAssetStore — thread-safe, WAL mode, cache TTL |
| `llm_guard_api/app/routes_assets.py` | REST API: CRUD + bulk import + cache sync + stats |
| `llm_guard_api/Dockerfile.offline` | Multi-stage offline Docker build (22 ML model icinde) |
| `llm_guard_api/download_models.py` | Build sirasinda tum HF modellerini indirir |
| `llm_guard_api/web/index.html` | Tek sayfa Web UI (PII maskeleme test + varlik yonetimi paneli) |

### Degistirilen Dosyalar
| Dosya | Degisiklik |
|-------|-----------|
| `llm_guard/input_scanners/__init__.py` | DynamicLookup import + `__all__`'a eklendi |
| `llm_guard/input_scanners/util.py` | `get_scanner_by_name()` DynamicLookup destegi |
| `llm_guard/input_scanners/anonymize_helpers/regex_patterns.py` | Turkce PII: TC_KIMLIK, IBAN_TR, TURKISH_PHONE, TAX_NUMBER_TR, TR_LICENSE_PLATE, EMAIL_ADDRESS_RE, CREDIT_CARD_RE |
| `llm_guard_api/app/app.py` | Asset store init, asset routes, web UI mount, entity_types_suppress |
| `llm_guard_api/app/scanner.py` | TR Anonymize (BERT Turkish NER + mDeBERTa secondary), placeholder koruma wrapping |
| `llm_guard_api/app/config.py` | DynamicLookupConfig eklendi |
| `llm_guard_api/config/scanners.yml` | Aktif scanner pipeline: Secrets → DynamicLookup → Anonymize(tr) → Regex → Deanonymize |

## Aktif Scanner Pipeline

Siralama onemlidir — scanner'lar bu sirada calisir:

1. **Secrets** — API key, token, private key tespiti (detect-secrets)
2. **DynamicLookup** — Dahili varliklar (VM adlari, hostname'ler, DB isimleri) SQLite'dan okunur, `[REDACTED_HOSTNAME_1]` seklinde maskelenir
3. **Anonymize (TR)** — Turkce PII: kisi adi (BERT Turkish NER + mDeBERTa), email, telefon, TC kimlik, IBAN, plaka, vergi no vs. Onceki scanner'larin `[REDACTED_*]` placeholder'larini korur
4. **Regex** — JDBC connection string'leri, dahili domain pattern'leri
5. **Deanonymize** (output) — Vault'taki maskelenmis degerleri geri cevirir

### Onemli Tasarim Kararlari

- **Turkish BERT NER (`savasy/bert-base-turkish-ner-cased`)**: ONNX versiyonu YOK, `use_onnx=False` zorunlu
- **mDeBERTa AI4Privacy**: Anonymize scanner'a secondary recognizer olarak enjekte edilir (`scanner._analyzer.registry.add_recognizer`)
- **Placeholder koruma**: DynamicLookup'tan gelen `[REDACTED_*_N]` placeholder'lari Anonymize'da NER tarafindan bozulmasin diye gecici safe token'larla (`_ve0_`, `_ve1_`) degistirilir, sonra geri konur
- **Entity type suppression**: `/analyze/prompt` endpoint'i `entity_types_suppress` parametresi kabul eder — Web UI'dan belirli entity tipleri devre disi birakilabilir
- **spaCy**: `en_core_web_sm` kullanilir (Turkce spaCy modeli yok, English fallback yeterli tokenization icin)

## Offline Docker Image

### Build (repo root'tan)
```bash
docker build --platform linux/amd64 -f llm_guard_api/Dockerfile.offline -t llm-guard-api:offline .
```

### Mimari
- **Stage 1 (builder):** pip install `.[cpu]` + spacy download + `download_models.py` (22 HF model)
- **Stage 2 (runtime):** site-packages + HF cache kopyala, app dosyalari, core library overlay (4 modified dosya), `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1`
- **Core library overlay:** Modified `llm_guard/` dosyalari pip ile kurulan paketin uzerine kopyalanir
- Platform: `linux/amd64`, Base: `python:3.12-slim`, Non-root user (uid 1000)
- Image boyutu: ~15 GB

### 22 Baked-in Model
Tum modeller `download_models.py`'da listelenmistir. Hem orijinal hem ONNX versiyonlari indirilir.

### Test
```bash
# Offline calisma testi
docker run --rm --network none -p 8000:8000 llm-guard-api:offline
curl http://localhost:8000/healthz
curl -X POST http://localhost:8000/analyze/prompt -H "Content-Type: application/json" \
  -d '{"prompt":"Ahmet Yilmaz ahmet@example.com adresinden mesaj gonderdi"}'
```

## Common Commands

### Run the API locally
```bash
# From llm_guard_api/
make run-uvicorn
# Or directly:
uvicorn app.app:create_app --host=0.0.0.0 --port=8000 --workers=1
```

### Install dependencies
```bash
# API with CPU optimizations (from llm_guard_api/)
make install  # equivalent to: pip install ".[cpu]"
# Core library dev dependencies (from repo root)
pip install ".[dev]"
```

### Run tests (from repo root)
```bash
python -m pytest --exitfirst --verbose --failed-first --cov=. --color=yes
python -m pytest tests/input_scanners/test_anonymize.py -v
```

### Lint and format (from repo root)
```bash
ruff check --fix .
ruff format .
pyright
```

### Docker
```bash
# Offline build (repo root'tan)
docker build --platform linux/amd64 -f llm_guard_api/Dockerfile.offline -t llm-guard-api:offline .
# Proxy ile build
docker build --platform linux/amd64 -f llm_guard_api/Dockerfile.offline \
  --build-arg HTTP_PROXY=http://proxy:8080 --build-arg HTTPS_PROXY=http://proxy:8080 \
  -t llm-guard-api:offline .
# Offline run
docker run --rm --network none -p 8000:8000 llm-guard-api:offline
# Production run
docker run -d --restart unless-stopped -p 8000:8000 \
  -v /opt/llm-guard/data:/home/user/app/data -e LOG_LEVEL=INFO llm-guard-api:offline
```

### Push to GitHub
```bash
cd /path/to/llm-guard
git remote add target https://github.com/kenan2x/llmguard-test.git  # sadece ilk seferde
git push target main
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/analyze/prompt` | POST | Sequential scan + sanitize prompt |
| `/analyze/output` | POST | Sequential scan + sanitize output |
| `/scan/prompt` | POST | Parallel scan prompt (risk scores only) |
| `/scan/output` | POST | Parallel scan output (risk scores only) |
| `/healthz` | GET | Health check |
| `/readyz` | GET | Readiness check |
| `/metrics` | GET | Prometheus metrics (if enabled) |
| `/api/v1/masked-assets/` | GET/POST | List/create masked assets |
| `/api/v1/masked-assets/{id}` | PUT/DELETE | Update/delete masked asset |
| `/api/v1/masked-assets/bulk` | POST | Bulk import assets |
| `/api/v1/masked-assets/sync` | POST | Refresh asset cache |
| `/api/v1/masked-assets/stats` | GET | Asset statistics |
| `/web/` | GET | Web UI |

## Key Details

- Python >=3.10,<3.13. Ruff line length: 100. Current version: 0.3.16.
- `torch.set_num_threads(1)` is set in `scanner.py` — intentional for multi-worker deployment.
- ML model scanners default to `use_onnx=True` EXCEPT Turkish BERT NER (no ONNX available).
- `scan_fail_fast` mode stops scanning after the first failure.
- Minimum 16GB RAM recommended during startup when loading multiple scanners.
- `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` are set in Docker image — no network calls at runtime.
- DynamicLookup uses SQLite with WAL mode, thread-safe locking, and in-memory cache with configurable TTL.
- Asset categories: VM_NAME, HOSTNAME, DB_NAME, TABLE_NAME, STORAGE_RESOURCE, NETWORK_RESOURCE, INTERNAL_URL, INTERNAL_SERVICE, PROJECT_NAME.
- Web UI served from `/web/` via FastAPI StaticFiles mount.
- OpenAPI/Swagger UI only available when `log_level: DEBUG`.
