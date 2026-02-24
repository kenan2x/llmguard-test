"""Download all ML models for offline Docker deployment.

Run during Docker build to populate the HuggingFace cache.
All models will be stored in ~/.cache/huggingface/hub/.
"""

from huggingface_hub import snapshot_download


MODELS = [
    # Anonymize - Turkish NER (primary, no ONNX)
    "savasy/bert-base-turkish-ner-cased",
    # Anonymize - English AI4Privacy (has ONNX in onnx/ subfolder)
    "Isotonic/deberta-v3-base_finetuned_ai4privacy_v2",
    # Anonymize - Turkish AI4Privacy secondary (has ONNX in onnx/ subfolder)
    "Isotonic/mdeberta-v3-base_finetuned_ai4privacy_v2",
    # PromptInjection
    "protectai/deberta-v3-base-prompt-injection-v2",
    # Toxicity
    "unitary/unbiased-toxic-roberta",
    "ProtectAI/unbiased-toxic-roberta-onnx",
    # Language detection
    "papluca/xlm-roberta-base-language-detection",
    "ProtectAI/xlm-roberta-base-language-detection-onnx",
    # Gibberish
    "madhurjindal/autonlp-Gibberish-Detector-492513457",
    # Code language identification
    "philomath-1209/programming-language-identification",
    # BanCode
    "vishnun/codenlbert-sm",
    "protectai/vishnun-codenlbert-sm-onnx",
    # BanTopics
    "MoritzLaurer/roberta-base-zeroshot-v2.0-c",
    "protectai/MoritzLaurer-roberta-base-zeroshot-v2.0-c-onnx",
    # BanCompetitors
    "guishe/nuner-v1_orgs",
    "protectai/guishe-nuner-v1_orgs-onnx",
    # Bias (output scanner)
    "valurank/distilroberta-bias",
    "ProtectAI/distilroberta-bias-onnx",
    # MaliciousURLs (output scanner)
    "DunnBC22/codebert-base-Malicious_URLs",
    "ProtectAI/codebert-base-Malicious_URLs-onnx",
    # NoRefusal (output scanner)
    "ProtectAI/distilroberta-base-rejection-v1",
    # Relevance (output scanner)
    "BAAI/bge-small-en-v1.5",
]


def main():
    total = len(MODELS)
    for i, model_id in enumerate(MODELS, 1):
        print(f"[{i}/{total}] Downloading {model_id} ...")
        snapshot_download(repo_id=model_id)
        print(f"  OK: {model_id}")

    print(f"\nAll {total} models downloaded successfully.")


if __name__ == "__main__":
    main()
