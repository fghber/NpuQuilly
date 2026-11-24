"""Download pre-exported OpenVINO IR models (no conversion step)."""
import argparse
import os
import sys
from pathlib import Path

import yaml

REGISTRY = Path(__file__).parent / "models.yaml"

def download(repo: str, dest: str):
    from huggingface_hub import snapshot_download
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {repo} -> {out} ...")
    # Hub metadata makes this resumable, even if the directory is nonempty.
    snapshot_download(repo_id=repo, local_dir=str(out))
    print("Done.")
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alias", default="all", help="model alias from models.yaml or 'all'")
    ap.add_argument("--registry", default=str(REGISTRY))
    args = ap.parse_args()
    registry = Path(args.registry).resolve()
    with registry.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    selected = [m for m in cfg["models"] if args.alias == "all" or m["alias"] == args.alias]
    if not selected:
        ap.error(f"Unknown alias {args.alias!r}. Available: {[m['alias'] for m in cfg['models']]}")
    seen_dirs = set()
    for m in selected:
        if m["dir"] in seen_dirs:
            print(f"Alias {m['alias']} shares dir {m['dir']} (already handled)")
            continue
        seen_dirs.add(m["dir"])
        try:
            download(m["repo"], str((registry.parent / m["dir"]).resolve()))
        except Exception as e:
            print(f"FAILED {m['repo']}: {e}", file=sys.stderr)
            print("Tip: `hf auth login` — anonymous downloads of multi-GB files often stall.", file=sys.stderr)
            return 1
    return 0

if __name__ == "__main__":
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    raise SystemExit(main())
