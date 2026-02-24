# LLM Guard API — Offline Docker Image

Internet erişimi olmayan Linux x64 sunuculara deploy etmek icin hazirlanmis Docker image. Build sirasinda tum ML modelleri, spaCy modeli ve Python bagimliliklari indirilir. Runtime'da hicbir dis baglanti gerekmez.

## Icindekiler

- [On Kosullar](#on-kosullar)
- [Build (Internet Gereken Makine)](#build-internet-gereken-makine)
- [Image Transfer (Offline Sunucuya Tasima)](#image-transfer-offline-sunucuya-tasima)
- [Run (Offline Sunucu)](#run-offline-sunucu)
- [Dogrulama](#dogrulama)
- [Konfigürasyon](#konfigurasyon)
- [Troubleshooting](#troubleshooting)

---

## On Kosullar

### Build makinesi (internet olan)
- Docker Engine 20.10+ veya Docker Desktop
- En az 30 GB bos disk alani (build sirasinda modeller + intermediate layers)
- Internet erisimi (HuggingFace, PyPI, GitHub)

### Hedef sunucu (offline)
- Linux x86_64 (amd64)
- Docker Engine 20.10+
- En az 16 GB RAM (scanner'lar yuklenirken)
- En az 20 GB bos disk alani (image ~15 GB)

---

## Build (Internet Gereken Makine)

### 1. Repo'yu klonla

```bash
git clone https://github.com/kenan2x/llmguard-test.git
cd llmguard-test
```

### 2. Docker image olustur

```bash
# Repo root dizininden calistirin (llm_guard_api/ degil!)
docker build --platform linux/amd64 \
  -f llm_guard_api/Dockerfile.offline \
  -t llm-guard-api:offline \
  .
```

> **Not:** Build suresi internet hizina bagli olarak 15-30 dakika surebilir. 22 ML modeli (toplam ~10 GB) indirilecektir.

> **Not:** Mac (Apple Silicon) uzerinde build yapiyorsaniz, `--platform linux/amd64` QEMU emulasyonu kullanir ve daha yavas olur. Mumkunse Linux x64 makine uzerinde build yapin.

### 3. Image boyutunu kontrol et

```bash
docker images llm-guard-api:offline
```

Beklenen boyut: ~15 GB (modeller dahil)

---

## Image Transfer (Offline Sunucuya Tasima)

### Yontem 1: docker save/load (en basit)

```bash
# Build makinesinde — image'i tar dosyasina kaydet
docker save llm-guard-api:offline | gzip > llm-guard-api-offline.tar.gz

# Dosyayi offline sunucuya kopyala (USB, SCP, vs.)
scp llm-guard-api-offline.tar.gz user@offline-server:/tmp/

# Offline sunucuda — image'i yukle
docker load < /tmp/llm-guard-api-offline.tar.gz
```

### Yontem 2: Private Registry

Eger ic aginizda bir Docker registry varsa:

```bash
# Build makinesinde
docker tag llm-guard-api:offline registry.internal:5000/llm-guard-api:offline
docker push registry.internal:5000/llm-guard-api:offline

# Offline sunucuda (registry'ye erisilebiliyorsa)
docker pull registry.internal:5000/llm-guard-api:offline
```

---

## Run (Offline Sunucu)

### Basit calistirma

```bash
docker run -d \
  --name llm-guard \
  -p 8000:8000 \
  llm-guard-api:offline
```

### Production calistirma (volume ile)

```bash
# Data dizini olustur (SQLite DB icin)
mkdir -p /opt/llm-guard/data

# Calistir
docker run -d \
  --name llm-guard \
  --restart unless-stopped \
  -p 8000:8000 \
  -v /opt/llm-guard/data:/home/user/app/data \
  -e LOG_LEVEL=INFO \
  llm-guard-api:offline
```

### Ortam degiskenleri

| Degisken | Varsayilan | Aciklama |
|----------|-----------|----------|
| `LOG_LEVEL` | `DEBUG` | Log seviyesi (DEBUG, INFO, WARNING, ERROR) |
| `APP_WORKERS` | `1` | Uvicorn worker sayisi |
| `CONFIG_FILE` | `./config/scanners.yml` | Scanner konfigurasyonu |
| `SCAN_FAIL_FAST` | `false` | Ilk hata'da dur |
| `SCAN_PROMPT_TIMEOUT` | `30` | Prompt tarama timeout (saniye) |
| `SCAN_OUTPUT_TIMEOUT` | `30` | Output tarama timeout (saniye) |

### Loglari izle

```bash
docker logs -f llm-guard
```

---

## Dogrulama

### 1. Health check

```bash
curl http://localhost:8000/healthz
# Beklenen: {"status":"alive"}
```

### 2. Readiness check

```bash
curl http://localhost:8000/readyz
# Beklenen: {"status":"ready"}
```

### 3. PII maskeleme testi

```bash
curl -X POST http://localhost:8000/analyze/prompt \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Ahmet Yilmaz ahmet@example.com adresinden 5551234567 numarasina mesaj gonderdi"}'
```

Beklenen: Kisi adi, email ve telefon numarasi maskelenmis olarak donecek.

### 4. Offline test (network olmadan)

```bash
docker run --rm --network none -p 8000:8000 llm-guard-api:offline
# Baska bir terminal'de:
curl http://localhost:8000/healthz
```

### 5. Web UI

Tarayicida: `http://<sunucu-ip>:8000/web/`

---

## Konfigurasyon

Scanner konfigurasyonu `config/scanners.yml` dosyasinda tanimlidir. Mevcut aktif scanner'lar:

- **Secrets** — API anahtarlari, token'lar, ozel anahtarlar
- **DynamicLookup** — Dahili varlik isimleri (VM, hostname, DB)
- **Anonymize** (Turkce) — Kisi adi, email, telefon, TC kimlik, IBAN, plaka vs.
- **Regex** — JDBC connection string'leri, dahili domain'ler
- **Deanonymize** — Maskelenmis degerleri geri cevir (output)

Ozel konfigürasyon kullanmak icin:

```bash
docker run -d \
  -p 8000:8000 \
  -v /path/to/custom-scanners.yml:/home/user/app/config/scanners.yml:ro \
  llm-guard-api:offline
```

---

## Image Icindeki Modeller

| Model | Scanner | Boyut (yaklasik) |
|-------|---------|-----------------|
| savasy/bert-base-turkish-ner-cased | Anonymize TR | ~500 MB |
| Isotonic/deberta-v3-base_finetuned_ai4privacy_v2 | Anonymize EN | ~800 MB |
| Isotonic/mdeberta-v3-base_finetuned_ai4privacy_v2 | Anonymize TR (secondary) | ~800 MB |
| protectai/deberta-v3-base-prompt-injection-v2 | PromptInjection | ~800 MB |
| unitary/unbiased-toxic-roberta + ONNX | Toxicity | ~500 MB |
| papluca/xlm-roberta-base-language-detection + ONNX | Language | ~1 GB |
| madhurjindal/autonlp-Gibberish-Detector | Gibberish | ~500 MB |
| philomath-1209/programming-language-identification | Code | ~500 MB |
| vishnun/codenlbert-sm + ONNX | BanCode | ~300 MB |
| MoritzLaurer/roberta-base-zeroshot-v2.0-c + ONNX | BanTopics | ~500 MB |
| guishe/nuner-v1_orgs + ONNX | BanCompetitors | ~500 MB |
| valurank/distilroberta-bias + ONNX | Bias | ~400 MB |
| DunnBC22/codebert-base-Malicious_URLs + ONNX | MaliciousURLs | ~500 MB |
| ProtectAI/distilroberta-base-rejection-v1 | NoRefusal | ~500 MB |
| BAAI/bge-small-en-v1.5 | Relevance | ~130 MB |

---

## Troubleshooting

### Container baslamiyor / OOM

Scanner'lar yuklenirken cok fazla RAM kullanilabilir. En az 16 GB RAM olmalidir.

```bash
# Memory limit ile calistirma
docker run -d -p 8000:8000 --memory=16g llm-guard-api:offline
```

### Ilk istek yavas

Ilk istekte modeller belege yuklenir (`lazy_load: false` ise baslangicta yuklenir). Ilk istek 30-60 saniye surebilir, sonrakiler hizli olacaktir.

### Scanner timeout

`SCAN_PROMPT_TIMEOUT` degerini artirin:

```bash
docker run -d -p 8000:8000 -e SCAN_PROMPT_TIMEOUT=60 llm-guard-api:offline
```

### Image cok buyuk

Image ~15 GB buyuklugundedir. Bunun buyuk kismi ML modelleridir. Kullanilmayan modelleri `download_models.py`'dan cikarip yeniden build edebilirsiniz.

### "No such file" hatalari

Core library overlay dosyalarinin dogru kopyalandigini kontrol edin:

```bash
docker run --rm llm-guard-api:offline python -c "from llm_guard.input_scanners import DynamicLookup; print('OK')"
```
