"""Fetch the self-hosted WebLLM model for in-browser inbox classification.

`web/lib/webllm-classify.ts` runs a small local LLM (WebLLM) in the browser to
triage recruiter emails. By default WebLLM downloads ~1GB of weights from
huggingface.co at runtime, which some networks block outright (the symptom is
"Could not load the in-browser model: TypeError: Failed to fetch"). We instead
serve the model + wasm same-origin from `web/public/models/` (gitignored).

Run this once after cloning (or to refresh the files):

    python scripts/fetch_webllm_model.py

It pulls per-file via /resolve/ paths (the HF metadata/tree API is what blocked
networks reject; the file paths themselves usually work, directly or via the
hf-mirror.com mirror). The wasm lib comes from GitHub's raw CDN.
"""
from __future__ import annotations

import json
import os
import sys
import time

import requests

REPO = "mlc-ai/Llama-3.2-1B-Instruct-q4f16_1-MLC"
WASM = "Llama-3.2-1B-Instruct-q4f16_1_cs1k-webgpu.wasm"
WASM_URL = (
    "https://raw.githubusercontent.com/mlc-ai/binary-mlc-llm-libs/main/"
    f"web-llm-models/v0_2_84/base/{WASM}"
)
# Try the mirror first (works on HF-blocked networks), then HF directly.
RESOLVE_BASES = [
    f"https://hf-mirror.com/{REPO}/resolve/main",
    f"https://huggingface.co/{REPO}/resolve/main",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Nest under resolve/main/ so it matches WebLLM's cleanModelUrl() expectation
# and web/lib/webllm-classify.ts's MODEL_BASE (served same-origin from public/).
MODEL_DIR = os.path.join(
    ROOT, "web", "public", "models", REPO.split("/", 1)[1], "resolve", "main"
)
LIBS_DIR = os.path.join(ROOT, "web", "public", "models", "libs")
UA = {"User-Agent": "Mozilla/5.0"}

session = requests.Session()


def _get(url: str, *, binary: bool, retries: int = 6):
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, headers=UA, allow_redirects=True, timeout=90, stream=binary)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"    retry {attempt}/{retries}: {e}", flush=True)
            time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def fetch(dest_dir: str, fname: str, *, binary: bool, bases=RESOLVE_BASES) -> str | None:
    dest = os.path.join(dest_dir, fname)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"  skip (exists) {fname}", flush=True)
        with open(dest, "rb" if binary else "r", encoding=None if binary else "utf-8") as fh:
            return None if binary else fh.read()
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    last = None
    for base in bases:
        try:
            r = _get(f"{base}/{fname}", binary=binary)
        except RuntimeError as e:
            last = e
            continue
        if binary:
            total = 0
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
                    total += len(chunk)
            print(f"  ok {fname} ({total / 1e6:.1f} MB)", flush=True)
            return None
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(r.text)
        print(f"  ok {fname} ({len(r.text)} bytes)", flush=True)
        return r.text
    raise SystemExit(f"FAILED {fname}: {last}")


def main() -> None:
    os.makedirs(MODEL_DIR, exist_ok=True)
    print(f"model -> {MODEL_DIR}", flush=True)

    cfg = json.loads(fetch(MODEL_DIR, "mlc-chat-config.json", binary=False))
    # web-llm 0.2.x reads tensor-cache.json (not ndarray-cache.json) as the
    # shard manifest; both exist in the repo and list the same params. Fetch
    # both — tensor-cache.json is what the engine actually requires at load.
    cache = json.loads(fetch(MODEL_DIR, "tensor-cache.json", binary=False))
    fetch(MODEL_DIR, "ndarray-cache.json", binary=False)

    misc = list(cfg.get("tokenizer_files", []))
    shards = sorted({rec["dataPath"] for rec in cache.get("records", []) if rec.get("dataPath")})
    print(f"tokenizer files: {misc}", flush=True)
    print(f"param shards: {len(shards)}", flush=True)

    for f in misc:
        # tokenizer.model (sentencepiece) is binary; .json/.txt are text
        fetch(MODEL_DIR, f, binary=not f.endswith((".json", ".txt")))
    for f in shards:
        fetch(MODEL_DIR, f, binary=True)

    print(f"\nwasm -> {LIBS_DIR}", flush=True)
    fetch(LIBS_DIR, WASM, binary=True, bases=[os.path.dirname(WASM_URL)])

    print("\nALL DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
