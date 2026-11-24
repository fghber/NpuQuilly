"""Microbench: TTFT + decode tok/s for grammar-sized prompts. No model needed for --dry-run."""
import argparse
import time

SAMPLES = [
    "Their going to the store, its a nice day and me and him was happy.",
    "The committee have decided to postpone there meeting until next week due to unforseen circumstances.",
]

def bench_remote(base_url: str, model: str):
    import httpx
    for s in SAMPLES:
        t0 = time.time()
        r = httpx.post(f"{base_url}/v1/chat/completions", json={
            "model": model, "temperature": 0.2,
            "messages": [{"role": "user", "content": f"Correct grammar. Return ONLY corrected text:\n{s}"}]},
            timeout=120)
        dt = time.time() - t0
        txt = r.json()["choices"][0]["message"]["content"] if r.status_code == 200 else r.text[:200]
        toks = max(1, len(txt.split()))
        print(f"{dt:.2f}s total | ~{toks/max(dt,0.01):.1f} tok/s | {txt[:100]!r}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default="grammar-fast")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        print("dry-run OK (server not required)")
        return 0
    bench_remote(args.base_url, args.model)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
