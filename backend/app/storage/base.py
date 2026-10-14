from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Swap this for S3 / Azure Blob / GCS without touching the API or services."""

    @abstractmethod
    def save(self, key: str, data: bytes) -> str:
        """Persist bytes under a server-generated key and return the storage path."""

    @abstractmethod
    def read(self, path: str) -> bytes: ...

    @abstractmethod
    def exists(self, path: str) -> bool: ...
