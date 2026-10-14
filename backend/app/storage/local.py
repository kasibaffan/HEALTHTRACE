from pathlib import Path

from app.storage.base import StorageBackend


class LocalStorage(StorageBackend):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe(self, relative: str) -> Path:
        target = (self.root / relative).resolve()
        if self.root != target and self.root not in target.parents:
            raise ValueError("Path escapes the storage root")
        return target

    def save(self, key: str, data: bytes) -> str:
        target = self._safe(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    def read(self, path: str) -> bytes:
        return self._safe(path).read_bytes()

    def exists(self, path: str) -> bool:
        try:
            return self._safe(path).is_file()
        except ValueError:
            return False
