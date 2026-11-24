"""Exercise the real app/client/server/model path and save a reviewable report.

python eval/validate.py --device GPU --model grammar-fast
python eval/validate.py --device NPU --model grammar-battery
python eval/validate.py --action rewrite --model rewrite-alt --limit 2
"""
import argparse
import json
import re
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "NpuQuilly"))

from app.application import NpuQuillyApp
from core.ai_provider import AIProvider
from core.config_manager import ConfigManager
from core.prompt_manager import PromptManager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--device", choices=["GPU", "NPU", "CPU"], default="GPU")
    parser.add_argument("--model", default="grammar-fast")
    parser.add_argument("--action", choices=["grammar", "rewrite"], default="grammar")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = "sentences.json" if args.action == "grammar" else "rewrite_samples.json"
    samples = json.loads((ROOT / "eval" / source).read_text(encoding="utf-8"))
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        samples = samples[:args.limit]
    model_slug = re.sub(r"[^a-zA-Z0-9._-]", "_", args.model)
    output = args.output or ROOT / "eval" / "reports" / f"validation_{args.action}_{model_slug}_{args.device}.json"
    results = []
    # Isolate validation from the user's real settings and hotkeys.
    with tempfile.TemporaryDirectory(prefix="npuquilly-eval-", dir=ROOT) as tmp:
        app = NpuQuillyApp.__new__(NpuQuillyApp)
        app.cfg = ConfigManager(Path(tmp) / "config.json")
        app.cfg.data.update(base_url=args.base, model=args.model, device=args.device)
        app.prompts = PromptManager()
        app.last_action, app.last_instruction = "grammar_check", ""
        app.provider = AIProvider()
        app._wire_provider()
        try:
            for sample in samples:
                row = dict(sample, model=app.resolve_model(app.ACTION_MAP[args.action]), device=args.device)
                try:
                    text, seconds = app.run_action(sample["input"], args.action)
                    row.update(output=text, latency_s=round(seconds, 3))
                    if "expected" in sample:
                        row["exact_match"] = text == sample["expected"]
                    print(f"{sample['id']} {seconds:.2f}s: {text}", flush=True)
                except Exception as e:
                    row["error"] = f"{type(e).__name__}: {e}"
                    print(f"{sample['id']}: {row['error']}", flush=True)
                results.append(row)
        finally:
            app.provider.close()
    latencies = [r["latency_s"] for r in results if "latency_s" in r]
    report = {"model": args.model, "device": args.device, "action": args.action,
              "errors": sum("error" in r for r in results),
              "exact_matches": sum(r.get("exact_match", False) for r in results),
              "median_latency_s": statistics.median(latencies) if latencies else None,
              "note": "Exact matching is a reference comparison, not a quality score; review alternate valid corrections.",
              "results": results}
    if args.output is None:
        output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {output} ({len(results)} samples, {report['errors']} errors)")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
