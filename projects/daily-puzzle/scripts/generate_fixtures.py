"""Bundled stand-ins for Hugging Face files, so CI and the offline demo need no network (deterministic, seeded).

    python scripts/generate_fixtures.py

fixtures/tiny-mlp/model.safetensors     4 → 8 → 3 MLP (fc1, fc2), float32, trained a little on flowers.csv
fixtures/flowers/flowers.csv            150 fictional flowers, 3 species, 4 measurements (iris-like, synthetic)
fixtures/word-vectors/                  36 words × 16 dims with topic clusters (markets, data/AI, animals, fruit)
All synthetic and released under the project's MIT licence (cc0 for the CSV).
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from safetensors.numpy import save_file

ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def flowers(rng) -> tuple[np.ndarray, np.ndarray, list[str]]:
    species = ["alba", "rubra", "viola"]
    centres = np.array([[5.0, 3.4, 1.5, 0.25], [5.9, 2.8, 4.3, 1.3], [6.6, 3.0, 5.5, 2.0]])
    spread = np.array([[0.35, 0.38, 0.17, 0.1], [0.5, 0.31, 0.47, 0.2], [0.63, 0.32, 0.55, 0.27]])
    X, y = [], []
    for k in range(3):
        X.append(np.round(centres[k] + rng.normal(size=(50, 4)) * spread[k], 1).clip(0.1))
        y += [k] * 50
    X = np.vstack(X)
    order = rng.permutation(150)
    X, y = X[order], np.array(y)[order]
    d = ROOT / "flowers"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "flowers.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "species", "sepal_length", "sepal_width", "petal_length", "petal_width"])
        for i, (row, k) in enumerate(zip(X, y), 1):
            w.writerow([i, species[k], *[f"{v:.1f}" for v in row]])
    return X, y, species


def tiny_mlp(rng, X, y) -> None:
    Xs = (X - X.mean(0)) / X.std(0)
    W1, b1 = rng.normal(scale=0.6, size=(8, 4)), rng.normal(scale=0.1, size=8)
    W2, b2 = rng.normal(scale=0.4, size=(3, 8)), np.zeros(3)
    for _ in range(40):                                # a short warm-up so the head is sensible but not finished
        H = np.maximum(Xs @ W1.T + b1, 0)
        z = H @ W2.T + b2
        p = np.exp(z - z.max(1, keepdims=True)); p /= p.sum(1, keepdims=True)
        p[np.arange(len(y)), y] -= 1
        W2 -= 0.05 * p.T @ H / len(y); b2 -= 0.05 * p.mean(0)
    d = ROOT / "tiny-mlp"
    d.mkdir(parents=True, exist_ok=True)
    save_file({"fc1.weight": W1.astype("float32"), "fc1.bias": b1.astype("float32"),
               "fc2.weight": W2.astype("float32"), "fc2.bias": b2.astype("float32")}, str(d / "model.safetensors"),
              metadata={"format": "np", "note": "synthetic fixture for daily-puzzle"})


def word_vectors(rng) -> None:
    topics = {"markets": ["stock", "bond", "equity", "yield", "hedge", "dividend", "broker", "margin", "option"],
              "data": ["tensor", "matrix", "vector", "gradient", "embedding", "token", "layer", "python", "query"],
              "animals": ["tiger", "otter", "eagle", "zebra", "panda", "falcon", "koala", "walrus", "heron"],
              "fruit": ["apple", "mango", "peach", "lemon", "grape", "cherry", "papaya", "melon", "plum"]}
    centres = {t: rng.normal(size=16) for t in topics}
    vocab, rows = [], []
    for t, ws in topics.items():
        for w in ws:
            vocab.append(w)
            rows.append(centres[t] + rng.normal(scale=0.55, size=16))
    d = ROOT / "word-vectors"
    d.mkdir(parents=True, exist_ok=True)
    (d / "vocab.txt").write_text("\n".join(vocab) + "\n")
    save_file({"embeddings": np.array(rows, dtype="float32")}, str(d / "vectors.safetensors"))


if __name__ == "__main__":
    rng = np.random.default_rng(20261004)
    X, y, _ = flowers(rng)
    tiny_mlp(rng, X, y)
    word_vectors(rng)
    (ROOT / "README.md").write_text(__doc__.split("\n\n", 1)[1])
    print("fixtures written to", ROOT)
