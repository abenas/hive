"""Armazenamento de artefatos. Local: sistema de arquivos. AWS: S3 (mesma interface)."""

import hashlib
from pathlib import Path
from typing import Protocol


class ArtifactStore(Protocol):
    def put(self, mission_id: str, name: str, version: int, content: str | bytes) -> tuple[str, str, int]:
        """Grava e devolve (uri, sha256, tamanho)."""
        ...

    def get(self, uri: str) -> str: ...

    def get_bytes(self, uri: str) -> bytes: ...


class LocalArtifactStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def put(self, mission_id: str, name: str, version: int, content: str | bytes) -> tuple[str, str, int]:
        data = content if isinstance(content, bytes) else content.encode()
        path = self.root / mission_id / f"v{version}" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"file://{path}", hashlib.sha256(data).hexdigest(), len(data)

    def get(self, uri: str) -> str:
        return self.get_bytes(uri).decode("utf-8")

    def get_bytes(self, uri: str) -> bytes:
        path = Path(uri.removeprefix("file://")).resolve()
        if self.root not in path.parents:
            raise PermissionError("URI fora do repositório de artefatos")
        return path.read_bytes()
