"""Playbooks: conhecimento de ofício por papel, em Markdown com frontmatter (no espírito das Agent Skills).

Ficam em `hive/playbooks/*.md`, são injetados no prompt de sistema dos agentes do papel indicado
e cada delegação registra nome, versão e hash do conteúdo usado, para a auditoria.
"""

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PLAYBOOK_DIR = Path(__file__).resolve().parent.parent / "playbooks"


@dataclass(frozen=True)
class Playbook:
    name: str
    title: str
    version: str
    roles: tuple[str, ...]
    body: str
    digest: str

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}#{self.digest[:8]}"


def parse(text: str) -> Playbook:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("playbook sem frontmatter")
    meta = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    roles = tuple(r.strip() for r in meta.get("roles", "").strip("[]").split(",") if r.strip())
    body = m.group(2).strip()
    return Playbook(name=meta["name"], title=meta.get("title", meta["name"]), version=meta.get("version", "0"),
                    roles=roles, body=body, digest=hashlib.sha256(text.encode()).hexdigest())


@lru_cache
def load(directory: Path = PLAYBOOK_DIR) -> tuple[Playbook, ...]:
    return tuple(parse(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.md")))


def for_role(role: str) -> list[Playbook]:
    return [p for p in load() if role in p.roles]
