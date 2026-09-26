"""Cloudflare R2 Object Storage Service and Deterministic Mock Adapter.

Provides:
1. BaseStorageService: Abstract contract for multi-tenant document storage.
2. MockR2Storage: Deterministic in-memory storage adapter for offline tests (Rule 5).
3. CloudflareR2Storage: Production S3 API adapter for Cloudflare R2 bucket.
4. get_storage_service: Factory resolver returning active adapter.
"""

import os
import threading
from abc import ABC, abstractmethod
from typing import Any

from django.conf import settings


class BaseStorageService(ABC):
    """Abstract interface for cloud object storage operations."""

    @abstractmethod
    def upload_file_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/pdf",
    ) -> str:
        """Uploads raw bytes to the specified key. Returns the object key or URI."""
        ...

    @abstractmethod
    def generate_presigned_download_url(self, key: str, expires_in: int = 900) -> str:
        """Generates a cryptographically signed presigned download URL with given TTL in seconds."""
        ...

    @abstractmethod
    def get_file_bytes(self, key: str) -> bytes:
        """Retrieves raw bytes for the specified key. Raises FileNotFoundError if missing."""
        ...

    @abstractmethod
    def file_exists(self, key: str) -> bool:
        """Checks if an object exists at the specified key."""
        ...

    @abstractmethod
    def delete_file(self, key: str) -> bool:
        """Deletes an object at the specified key. Returns True if deleted or False if not found."""
        ...


class MockR2Storage(BaseStorageService):
    """Deterministic in-memory storage adapter for offline execution and automated tests.

    Thread-safe storage backing all unit and integration tests without network latency.
    """

    _storage: dict[str, bytes] = {}
    _lock = threading.Lock()

    def upload_file_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/pdf",
    ) -> str:
        with self._lock:
            self._storage[key] = data
        return key

    def generate_presigned_download_url(self, key: str, expires_in: int = 900) -> str:
        # Deterministic mock presigned URL pointing to local edge simulator
        return f"https://mock-r2.local/{key}?expires={expires_in}&sig=mock_valid_signature"

    def get_file_bytes(self, key: str) -> bytes:
        with self._lock:
            if key not in self._storage:
                raise FileNotFoundError(f"Mock R2 object '{key}' does not exist.")
            return self._storage[key]

    def file_exists(self, key: str) -> bool:
        with self._lock:
            return key in self._storage

    def delete_file(self, key: str) -> bool:
        with self._lock:
            if key in self._storage:
                del self._storage[key]
                return True
            return False

    @classmethod
    def clear(cls) -> None:
        """Test utility to clear all stored objects."""
        with cls._lock:
            cls._storage.clear()


class CloudflareR2Storage(BaseStorageService):
    """Production Cloudflare R2 adapter communicating via the S3 API with boto3."""

    def __init__(self) -> None:
        import boto3
        import botocore.config

        self.bucket_name = getattr(
            settings,
            "CLOUDFLARE_R2_BUCKET_NAME",
            os.getenv("R2_BUCKET_NAME", "magebooks-documents"),
        )
        account_id = getattr(
            settings,
            "CLOUDFLARE_ACCOUNT_ID",
            os.getenv("CLOUDFLARE_ACCOUNT_ID", ""),
        )
        endpoint_url = getattr(
            settings,
            "CLOUDFLARE_R2_ENDPOINT_URL",
            os.getenv(
                "R2_ENDPOINT_URL",
                f"https://{account_id}.r2.cloudflarestorage.com" if account_id else "",
            ),
        )
        access_key = getattr(
            settings,
            "CLOUDFLARE_R2_ACCESS_KEY_ID",
            os.getenv("R2_ACCESS_KEY_ID", ""),
        )
        secret_key = getattr(
            settings,
            "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
            os.getenv("R2_SECRET_ACCESS_KEY", ""),
        )

        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=botocore.config.Config(signature_version="s3v4"),
        )

    def upload_file_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/pdf",
    ) -> str:
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    def generate_presigned_download_url(self, key: str, expires_in: int = 900) -> str:
        url: str = self.client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )
        return url

    def get_file_bytes(self, key: str) -> bytes:
        import botocore.exceptions

        try:
            response: dict[str, Any] = self.client.get_object(Bucket=self.bucket_name, Key=key)
            return response["Body"].read()
        except botocore.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"R2 object '{key}' not found.") from exc
            raise

    def file_exists(self, key: str) -> bool:
        import botocore.exceptions

        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except botocore.exceptions.ClientError:
            return False

    def delete_file(self, key: str) -> bool:
        self.client.delete_object(Bucket=self.bucket_name, Key=key)
        return True


# Global mock singleton instance for test consistency
_mock_storage_singleton = MockR2Storage()


def get_storage_service() -> BaseStorageService:
    """Factory function returning the active cloud storage adapter.

    Returns MockR2Storage when IS_TESTING is True or when live Cloudflare R2
    credentials are absent from environment, otherwise CloudflareR2Storage.
    """
    if getattr(settings, "IS_TESTING", False):
        return _mock_storage_singleton

    access_key = getattr(settings, "CLOUDFLARE_R2_ACCESS_KEY_ID", "")
    secret_key = getattr(settings, "CLOUDFLARE_R2_SECRET_ACCESS_KEY", "")
    if not access_key or not secret_key:
        return _mock_storage_singleton

    try:
        return CloudflareR2Storage()
    except Exception:
        # Fallback to mock adapter if boto3 initialization fails
        return _mock_storage_singleton
