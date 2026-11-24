"""Local, non-streaming OpenAI-compatible OpenVINO GenAI server.

HOST, PORT, MODELS_YAML, CACHE_DIR and DEVICE optionally override defaults.
"""
import os
import gc
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

BASE = Path(__file__).resolve().parent
MODELS_YAML = Path(os.environ.get("MODELS_YAML", str(BASE / "models.yaml"))).resolve()
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
DEVICE_OVERRIDE = os.environ.get("DEVICE", "").upper()
CACHE_DIR = os.environ.get("CACHE_DIR", str(BASE / ".ovcache"))
NPU_MAX_PROMPT_LEN = 1024
NPU_MIN_RESPONSE_LEN = 256
MAX_NEW_TOKENS = 4096

_pipes: dict[tuple[str, str], Any] = {}
_registry: dict[str, dict[str, Any]] = {}
# LLMPipeline and its KV cache are stateful. Serialize compilation AND generation.
_inference_lock = threading.Lock()


def unload_models():
    """Release cached pipelines after active inference has finished."""
    with _inference_lock:
        _pipes.clear()
        gc.collect()


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=65536)


class ChatRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    model: str = "grammar-fast"
    messages: list[Message] = Field(min_length=1, max_length=64)
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=MAX_NEW_TOKENS, strict=True)
    stream: bool = False
    device: Literal["GPU", "NPU", "CPU"] | None = None


class GrammarRequest(BaseModel):
    text: str = Field(min_length=1, max_length=65536)
    model: str = "grammar-fast"
    device: Literal["GPU", "NPU", "CPU"] | None = None


def load_registry():
    with MODELS_YAML.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    registry = {}
    for model in cfg["models"]:
        alias = model["alias"]
        if alias in registry:
            raise ValueError(f"Duplicate model alias: {alias}")
        registry[alias] = dict(model, device=model.get("device", cfg.get("device_default", "GPU")))
    _registry.clear()
    _registry.update(registry)
    return _registry


def selected_device(alias: str, requested: str | None = None) -> str:
    if alias not in _registry:
        raise HTTPException(404, f"Unknown model '{alias}'. Available: {sorted(_registry)}")
    device = DEVICE_OVERRIDE or requested or _registry[alias]["device"]
    if device not in ("GPU", "NPU", "CPU"):
        raise HTTPException(400, f"Unsupported device: {device}")
    if device == "NPU" and not _registry[alias].get("npu_compatible", False):
        raise HTTPException(400, "This model is not configured for NPU. Select grammar-battery (symmetric INT4).")
    return device


def get_pipe(alias: str, device: str):
    """Called under _inference_lock; no silent fallback to a different device."""
    key = (alias, device)
    if key in _pipes:
        return _pipes[key]
    model_dir = (MODELS_YAML.parent / _registry[alias]["dir"]).resolve()
    required = ("openvino_model.xml", "openvino_model.bin", "openvino_tokenizer.xml",
                "openvino_tokenizer.bin", "openvino_detokenizer.xml", "openvino_detokenizer.bin")
    missing = [name for name in required if not (model_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"Model files missing in {model_dir}: {', '.join(missing)}. "
                           f"Run: python server/download_model.py --alias {alias}")
    import openvino as ov
    import openvino_genai as ov_genai
    devices = ov.Core().available_devices
    if not any(d.split('.')[0] == device for d in devices):
        raise RuntimeError(f"{device} is unavailable; OpenVINO sees {devices}. "
                           "Check the Intel drivers or select an available device.")
    # Keep only the active model/device. Drop its native resources before loading
    # another model, rather than accumulating a separate pipeline for every choice.
    _pipes.clear()
    gc.collect()
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    props = {"CACHE_DIR": str(Path(CACHE_DIR).resolve())}
    if device == "NPU":
        props.update(MAX_PROMPT_LEN=NPU_MAX_PROMPT_LEN, MIN_RESPONSE_LEN=NPU_MIN_RESPONSE_LEN)
    print(f"[server] loading {alias} on {device} ...", flush=True)
    t0 = time.monotonic()
    pipe = ov_genai.LLMPipeline(str(model_dir), device, **props)
    print(f"[server] loaded {alias} on {device} in {time.monotonic()-t0:.1f}s", flush=True)
    _pipes[key] = pipe
    return pipe


def build_prompt(pipe, messages: list[dict[str, str]]) -> str:
    # Phi and Qwen use different control tokens. Use each model's own template.
    return pipe.get_tokenizer().apply_chat_template(messages, add_generation_prompt=True)


def generate_text(pipe, prompt: str, temperature: float, max_tokens: int):
    import openvino_genai as ov_genai
    config = ov_genai.GenerationConfig()
    config.max_new_tokens = max_tokens
    config.do_sample = temperature > 0
    if config.do_sample:
        config.temperature = temperature
    # build_prompt already applied the template exactly once.
    config.apply_chat_template = False
    # A one-item batch returns metrics, including the exact generated-token count.
    result = pipe.generate([prompt], config)
    text = result if isinstance(result, str) else result.texts[0]
    if hasattr(result, "perf_metrics"):
        return text, result.perf_metrics.get_num_generated_tokens()
    tokens = pipe.get_tokenizer().encode(text, add_special_tokens=False)
    return text, int(tokens.input_ids.shape[-1])


def create_app():
    load_registry()
    app = FastAPI(title="NpuQuilly local server")

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [
            {"id": k, "object": "model", "owned_by": "local", "device": DEVICE_OVERRIDE or m["device"]}
            for k, m in _registry.items()]}

    @app.get("/health")
    def health():
        import openvino as ov
        return {"ok": True, "service": "npuquilly", "pid": os.getpid(), "models": sorted(_registry),
                "devices": ov.Core().available_devices,
                "loaded": [{"model": a, "device": d} for a, d in list(_pipes)]}

    @app.post("/v1/chat/completions")
    def chat(body: ChatRequest):
        if body.stream:
            raise HTTPException(400, "Streaming is not supported; use stream=false.")
        messages = [m.model_dump() for m in body.messages]
        if not any(m["content"].strip() for m in messages):
            raise HTTPException(400, "messages must contain text")
        if sum(len(m["content"]) for m in messages) > 65536:
            raise HTTPException(400, "Selection too long; select a shorter passage.")
        device = selected_device(body.model, body.device)
        with _inference_lock:
            try:
                pipe = get_pipe(body.model, device)
                prompt = build_prompt(pipe, messages)
                prompt_tokens = int(pipe.get_tokenizer().encode(
                    prompt, add_special_tokens=False).input_ids.shape[-1])
                if device == "NPU" and prompt_tokens > NPU_MAX_PROMPT_LEN:
                    raise HTTPException(400, f"NPU prompt has {prompt_tokens} tokens; limit is "
                                        f"{NPU_MAX_PROMPT_LEN}. Select less text or use GPU/CPU.")
                budget = body.max_tokens
                if device == "NPU":
                    budget = min(budget, NPU_MAX_PROMPT_LEN + NPU_MIN_RESPONSE_LEN - prompt_tokens)
                text, completion_tokens = generate_text(pipe, prompt, body.temperature, budget)
            except HTTPException:
                raise
            except Exception as e:
                print(f"[server] {body.model} on {device}: {type(e).__name__} during inference", flush=True)
                raise HTTPException(503, f"Inference failed on {device}: {e}") from e
        return {"id": f"local-{uuid.uuid4().hex}", "object": "chat.completion",
                "created": int(time.time()), "model": body.model, "device": device,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                             "finish_reason": "length" if completion_tokens >= budget else "stop"}],
                "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                          "total_tokens": prompt_tokens + completion_tokens}}

    @app.post("/grammar")
    def grammar(body: GrammarRequest):
        if not body.text.strip():
            raise HTTPException(400, "text must not be blank")
        return chat(ChatRequest(model=body.model, device=body.device, temperature=0.0,
                    max_tokens=min(MAX_NEW_TOKENS, max(256, len(body.text.encode('utf-8')) + 128)),
                    messages=[Message(role="system", content=
                              "Correct grammar, spelling and punctuation only. Preserve meaning, tone "
                              "and formatting. If already correct, return unchanged. Return ONLY the corrected text."),
                              Message(role="user", content=body.text)]))
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    print(f"NpuQuilly server on {HOST}:{PORT} | registry={MODELS_YAML}")
    uvicorn.run(app, host=HOST, port=PORT)
