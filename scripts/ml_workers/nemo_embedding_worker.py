#!/usr/bin/env python3
"""Runs INSIDE the isolated `.envs/env-nemo` interpreter. Never imported
by the base interpreter, and never imports anything from
`aarya_voice_lab` — the filesystem-contract boundary
`identity.embeddings.EmbeddingProvider`'s own docstring describes.

`identity.embeddings.LocalNeuralEmbeddingProvider` (base interpreter)
invokes this script as a subprocess with two file paths: a request JSON
and a response JSON. This script never touches the network, never reads
`data/source/`, and never receives or resolves an arbitrary path from
the request that isn't the exact WAV file the caller wrote for it.

Request JSON:
    {"mode": "probe"} -- load the real model and report whether it
        actually loaded (never merely whether the package imports).
    {"mode": "embed", "wav_path": "<abs path>"} -- load the model,
        compute a real embedding for that WAV file, and report it.

Response JSON (always written, even on failure):
    {"ok": true, "model_load_seconds": ..., ...mode-specific fields}
    {"ok": false, "error": "<message>"}
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MODEL_NAME = "titanet_large"
EXPECTED_DIMENSION = 192
EXPECTED_SAMPLE_RATE = 16000


def _load_model():
    from nemo.collections.asr.models import EncDecSpeakerLabelModel

    model = EncDecSpeakerLabelModel.from_pretrained(MODEL_NAME, map_location="cpu")
    model.eval()
    return model


def _run_probe() -> dict:
    started = time.monotonic()
    _load_model()
    load_seconds = time.monotonic() - started
    return {
        "ok": True,
        "model_name": MODEL_NAME,
        "model_load_seconds": round(load_seconds, 4),
        "embedding_dimension": EXPECTED_DIMENSION,
        "sample_rate": EXPECTED_SAMPLE_RATE,
    }


def _run_embed(wav_path: str) -> dict:
    path = Path(wav_path)
    if not path.is_file():
        return {"ok": False, "error": f"wav_path does not exist: {wav_path}"}

    load_started = time.monotonic()
    model = _load_model()
    load_seconds = time.monotonic() - load_started

    embed_started = time.monotonic()
    embedding = model.get_embedding(str(path))
    embed_seconds = time.monotonic() - embed_started

    values = embedding.flatten().tolist()
    if len(values) != EXPECTED_DIMENSION:
        return {
            "ok": False,
            "error": f"model produced {len(values)}-dim output, expected {EXPECTED_DIMENSION}",
        }

    return {
        "ok": True,
        "model_name": MODEL_NAME,
        "model_load_seconds": round(load_seconds, 4),
        "embedding_seconds": round(embed_seconds, 4),
        "embedding_dimension": len(values),
        "sample_rate": EXPECTED_SAMPLE_RATE,
        "values": values,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: nemo_embedding_worker.py <request.json> <response.json>", file=sys.stderr)
        return 2

    request_path, response_path = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        mode = request.get("mode")
        if mode == "probe":
            response = _run_probe()
        elif mode == "embed":
            response = _run_embed(request["wav_path"])
        else:
            response = {"ok": False, "error": f"unknown mode: {mode!r}"}
    except Exception as exc:  # noqa: BLE001 -- always report failure via the response file, never a bare traceback the caller must parse
        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    response_path.write_text(json.dumps(response), encoding="utf-8")
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
