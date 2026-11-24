"""Device guardrails: NPU prefers short prompts; auto-suggest GPU fallback."""
VALID = ("GPU", "NPU", "CPU")
NPU_MAX_PROMPT_CHARS = 4000  # ~1024 tokens heuristic for grammar path


def normalize(device: str) -> str:
    d = (device or "GPU").upper()
    return d if d in VALID else "GPU"


def should_warn_npu(device: str, text_len: int) -> str | None:
    if normalize(device) == "NPU" and text_len > NPU_MAX_PROMPT_CHARS:
        return ("Long selection on NPU may be slow/truncated (static 1024-token path). "
                "Consider GPU for this one.")
    return None
