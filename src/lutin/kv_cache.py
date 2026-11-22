"""How much memory the conversation cache of a model takes, read from its Hugging Face `config.json` (every EXL3 or safetensors repository carries one).

Engines reserve the cache of the whole conversation window when they load a model (TabbyAPI `cache_size`, llama.cpp `-c`, Ollama `num_ctx`). Without the
model's own numbers Lutin counted 120 MB per 1,000 tokens for any model: right for a 7B, half of what a 32B with 64 layers asks. The figure here is in
the unit of the catalogue (`kv_mo_1k`: MB per 1,000 tokens, keys and values at 16 bits), so `model_selection.required_memory_gb` uses it unchanged."""
import json
import threading
from pathlib import Path

_lock = threading.Lock()
_folders = {}          # str(folder) -> (mtime of its config.json, value)


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def mb_per_1k(config):
    """MB of keys and values per 1,000 tokens at 16 bits, or None when the file does not say (never guessed)."""
    if not isinstance(config, dict):
        return None
    text = config.get("text_config") if isinstance(config.get("text_config"), dict) else config          # vision models keep the language model's numbers apart
    layers, heads = _int(text.get("num_hidden_layers")), _int(text.get("num_attention_heads"))
    kv_heads = _int(text.get("num_key_value_heads")) or heads
    head_dim = _int(text.get("head_dim")) or (_int(text.get("hidden_size")) // heads if heads else 0)
    kinds = text.get("layer_types")
    if isinstance(kinds, list) and kinds:
        layers = sum(1 for k in kinds if "attention" in str(k) and "linear" not in str(k))          # a linear-attention layer keeps a fixed state, not a cache that grows with the window
    elif _int(text.get("full_attention_interval")):
        layers //= text["full_attention_interval"]
    if not (layers and kv_heads and head_dim):
        return None
    return max(1, round(2 * layers * kv_heads * head_dim * 2 * 1000 / 1e6))


def of_folder(folder):
    """`mb_per_1k` of a model on disk (its `config.json`), read again only when the file changes; None when it cannot be read."""
    path = Path(folder) / "config.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    with _lock:
        kept = _folders.get(str(folder))
    if kept and kept[0] == mtime:
        return kept[1]
    try:
        value = mb_per_1k(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        value = None
    with _lock:
        _folders[str(folder)] = (mtime, value)
    return value
