"""ChatML helpers: render {{text}}/{{instruction}} templates, parse <|im_start|> blocks."""
import re

ROLE_RE = re.compile(r"<\|im_start\|>\s*(\w+)\s*\n(.*?)<\|im_end\|>", re.DOTALL)


def render(template: str, text: str = "", instruction: str = "") -> str:
    values = {"text": text or "", "instruction": instruction or ""}
    return re.sub(r"\{\{(text|instruction)\}\}", lambda m: values[m[1]], template)


def build_messages(template: str, text: str = "", instruction: str = ""):
    """Parse trusted template boundaries before inserting arbitrary selected text."""
    return [{**m, "content": render(m["content"], text, instruction)}
            for m in parse_messages(template)]


def parse_messages(rendered: str):
    """Parse rendered ChatML into OpenAI messages list. Falls back to single user msg."""
    msgs = []
    for role, content in ROLE_RE.findall(rendered):
        role = role.strip().lower()
        if role not in ("system", "user", "assistant"):
            role = "user"
        msgs.append({"role": role, "content": content.strip()})
    if not msgs:
        msgs = [{"role": "user", "content": rendered.strip()}]
    return msgs
