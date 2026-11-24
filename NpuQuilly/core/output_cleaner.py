"""Post-process LLM text outputs: strip template leakage, never content.

Small models often echo scaffolding from the prompt (<text> tags, ChatML
markers, fences, "here is the corrected..." preambles) despite instructions.
This removes that wrapping deterministically. It runs in run_action, so every
caller (hotkeys, popup, repeat) gets clean text.
"""
import re

_CHATML_RE = re.compile(r"^<\|im_start\|>assistant\s*\n(.*?)<\|im_end\|>$", re.DOTALL)
_FENCE_RE = re.compile(r"^```\w*\s*\n?(.*?)\n?```\s*$", re.DOTALL)
_PREAMBLE_RE = re.compile(
    r"^(here is the corrected (text|sentence|version)|corrected( text| sentence)?|"
    r"grammar correction|the corrected version is)\s*:\s*\n+", re.IGNORECASE)
_OPEN_TAG_RE = re.compile(r"^\s*<text>\s*", re.IGNORECASE)
_CLOSE_TAG_RE = re.compile(r"\s*</text>\s*$", re.IGNORECASE)


def clean_output(text: str, original: str = "") -> str:
    out = (text or "").strip()
    if not out:
        return out
    source = original.strip()
    if out == source:
        return out
    out = _CHATML_RE.sub(r"\1", out).strip()
    if not source.startswith("```"):
        out = _FENCE_RE.sub(r"\1", out).strip()
    # A literal tag can end a selection that starts with ordinary prose.
    # Only surplus tags at the edges can be generated wrappers.
    folded_out, folded_source = out.lower(), source.lower()
    extra_open = folded_out.count("<text>") - folded_source.count("<text>")
    extra_close = folded_out.count("</text>") - folded_source.count("</text>")
    source_heading = _PREAMBLE_RE.match(source)
    for _ in range(3):
        previous = out
        if extra_open > 0 and _OPEN_TAG_RE.match(out):
            out = _OPEN_TAG_RE.sub("", out, count=1)
            extra_open -= 1
        if extra_close > 0 and _CLOSE_TAG_RE.search(out):
            out = _CLOSE_TAG_RE.sub("", out, count=1)
            extra_close -= 1
        heading = _PREAMBLE_RE.match(out)
        if heading:
            body = out[heading.end():]
            if not source_heading or _PREAMBLE_RE.match(body):
                out = body
        if out == previous:
            break
    return out.strip()
