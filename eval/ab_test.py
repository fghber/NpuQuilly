"""A/B harness: Phi-4-mini vs Qwen3-4B-Instruct-2507 on the Option A server.
Stdlib only — no pip deps.

Modes:
  grammar: same grammar prompt both sides (temp 0.2). Sentence-level exactness.
  rewrite: same rewrite prompt both sides (temp 0.7). Judge style/flow subjectively.

Usage:
  python eval/ab_test.py --dry-run
  python eval/ab_test.py --action grammar --limit 2
  python eval/ab_test.py --action rewrite
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
GRAMMAR_SENTENCES = HERE / "sentences.json"
REWRITE_SENTENCES = HERE / "rewrite_samples.json"

SYSTEM_GRAMMAR = ("You are a grammar correction assistant. Correct all grammatical errors, "
                  "spelling mistakes, and punctuation issues. Preserve meaning, tone and "
                  "structure. Return ONLY the corrected text.")
SYSTEM_REWRITE = ("You are a professional editor. Rewrite the text to improve clarity, "
                  "readability, and flow while preserving the core meaning. Maintain the "
                  "original intent and key information. Return ONLY the rewritten text, "
                  "without any prefixes or meta-commentary.")

# First request per model pays one-time OV compile (30-70s+) server-side.
TIMEOUT = 600


def post_chat(base: str, model: str, messages, temperature: float, max_tokens: int,
              timeout=TIMEOUT) -> tuple[str, float]:
    payload = json.dumps({"model": model, "messages": messages,
                          "temperature": temperature, "stream": False,
                          "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=payload, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    dt = time.time() - t0
    return data["choices"][0]["message"]["content"].strip(), dt


def flags(inp: str, out: str):
    f = []
    if not out:
        f.append("EMPTY")
    if out.strip() == inp.strip():
        f.append("UNCHANGED")
    if "<|im_start|>" in out or "{{text}}" in out or "instruction" in out.lower()[:80]:
        f.append("ECHO_PROMPT")
    if len(out) > len(inp) * 2 and len(inp) > 0:
        f.append("TOO_LONG")
    return f


def run(base_a, model_a, base_b, model_b, action="grammar", sentences=None, limit=None):
    src = Path(sentences) if sentences else (REWRITE_SENTENCES if action == "rewrite" else GRAMMAR_SENTENCES)
    out_path = HERE / "reports" / f"results_ab_{action}.json"
    if action == "rewrite":
        system, temp = SYSTEM_REWRITE, 0.7
    else:
        system, temp = SYSTEM_GRAMMAR, 0.2
    items = json.loads(src.read_text(encoding="utf-8"))
    if limit:
        items = items[:limit]
    results = []
    for it in items:
        text = it["input"]
        budget = len(text.split()) + 256
        row = {"id": it["id"], "category": it["category"], "input": text,
               "expected": it.get("expected", ""), "goal": it.get("goal", "")}
        for side, base, model in (("A", base_a, model_a), ("B", base_b, model_b)):
            try:
                out, dt = post_chat(base, model, [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text}], temp, budget)
                row[side] = {"model": model,
                             "output": out, "latency_s": round(dt, 2),
                             "flags": flags(text, out)}
            except Exception as e:
                row[side] = {"model": model, "error": f"{type(e).__name__}: {e}"}
        results.append(row)
        a = row.get("A", {})
        b = row.get("B", {})
        print(f"{row['id']} [{row['category']}]")
        print(f"  IN: {text[:90]}")
        print(f"  A [{a.get('model','?')} {a.get('latency_s', '?')}s {a.get('flags', '')}]: {(a.get('output') or a.get('error'))[:200]}")
        print(f"  B [{b.get('model','?')} {b.get('latency_s', '?')}s {b.get('flags', '')}]: {(b.get('output') or b.get('error'))[:200]}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path} — judge winner per item, then decide routing.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", choices=["grammar", "rewrite"], default="grammar")
    ap.add_argument("--sentences", default=None)
    ap.add_argument("--base-a", default="http://127.0.0.1:8000")
    ap.add_argument("--model-a", default=None)
    ap.add_argument("--base-b", default=None)
    ap.add_argument("--model-b", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        g = json.loads(GRAMMAR_SENTENCES.read_text(encoding="utf-8"))
        r = json.loads(REWRITE_SENTENCES.read_text(encoding="utf-8"))
        assert len(g) == 20, f"expected 20 grammar sentences, got {len(g)}"
        assert all(k in g[0] for k in ("id", "input", "expected"))
        assert len(r) == 6, f"expected 6 rewrite samples, got {len(r)}"
        assert all(k in r[0] for k in ("id", "input", "goal"))
        print(f"dry-run OK: {len(g)} grammar + {len(r)} rewrite samples")
        return 0
    if args.action == "rewrite":
        model_a = args.model_a or "rewrite-alt"    # Qwen
        model_b = args.model_b or "grammar-fast"   # Phi baseline
    else:
        model_a = args.model_a or "grammar-fast"   # Phi
        model_b = args.model_b or "rewrite-alt"    # Qwen challenger
    base_b = args.base_b or "http://127.0.0.1:8000"
    return run(args.base_a, model_a, base_b, model_b,
               action=args.action, sentences=args.sentences, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
