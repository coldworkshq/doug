"""Thin create-only Google Cloud Storage adapter for hosted Example Packs."""

from __future__ import annotations

import time
from collections.abc import Callable

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage
from google.cloud.storage.retry import (
    DEFAULT_RETRY,
    DEFAULT_RETRY_IF_GENERATION_SPECIFIED,
    ConditionalRetryPolicy,
)

from .example_pack import ContentCollisionError


class CaptureBudgetExceeded(TimeoutError):
    """The total object-storage budget was consumed."""


class ObjectStoreError(RuntimeError):
    """A bounded storage failure safe to surface through internal layers."""


class StorageBudget:
    def __init__(
        self,
        *,
        seconds: float = 5.0,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if seconds <= 0:
            raise ValueError("storage budget must be positive")
        self._seconds = seconds
        self._monotonic = monotonic
        self._started_at = monotonic()

    def remaining(self) -> float:
        remaining = self._seconds - (self._monotonic() - self._started_at)
        if remaining <= 0:
            raise CaptureBudgetExceeded("object storage budget exhausted")
        return remaining


def _conditional_retry(deadline: float) -> ConditionalRetryPolicy:
    base = DEFAULT_RETRY_IF_GENERATION_SPECIFIED
    return ConditionalRetryPolicy(
        base.retry_policy.with_deadline(deadline),
        base.conditional_predicate,
        base.required_kwargs,
    )


class GcsObjectStore:
    """Object operations with no overwrite, delete, ACL, or URL surface."""

    LIST_LIMIT = 500

    def __init__(
        self,
        bucket_name: str,
        *,
        client: storage.Client | None = None,
        budget: StorageBudget | None = None,
    ):
        if not bucket_name:
            raise ValueError("bucket_name is required")
        self._client = storage.Client() if client is None else client
        self._bucket = self._client.bucket(bucket_name)
        self._budget = budget or StorageBudget()

    @staticmethod
    def _failure(exc: Exception) -> ObjectStoreError:
        return ObjectStoreError(f"object storage failed: {type(exc).__name__}")

    def _download(self, key: str) -> bytes:
        remaining = self._budget.remaining()
        try:
            return self._bucket.blob(key).download_as_bytes(
                timeout=remaining,
                retry=DEFAULT_RETRY.with_deadline(remaining),
            )
        except NotFound:
            raise FileNotFoundError("object not found") from None
        except CaptureBudgetExceeded:
            raise
        except Exception as exc:
            raise self._failure(exc) from None

    def create(self, key: str, data: bytes, *, content_type: str) -> None:
        remaining = self._budget.remaining()
        blob = self._bucket.blob(key)
        try:
            blob.upload_from_string(
                data,
                content_type=content_type,
                if_generation_match=0,
                timeout=remaining,
                retry=_conditional_retry(remaining),
            )
            return
        except PreconditionFailed:
            existing = self._download(key)
            if existing == data:
                return
            raise ContentCollisionError("different bytes already exist") from None
        except CaptureBudgetExceeded:
            raise
        except Exception as exc:
            raise self._failure(exc) from None

    def read(self, key: str) -> bytes:
        return self._download(key)

    def list(self, prefix: str) -> tuple[str, ...]:
        remaining = self._budget.remaining()
        try:
            blobs = self._client.list_blobs(
                self._bucket,
                prefix=prefix,
                max_results=self.LIST_LIMIT + 1,
                timeout=remaining,
                retry=DEFAULT_RETRY.with_deadline(remaining),
            )
            names = tuple(sorted(blob.name for blob in blobs))
        except CaptureBudgetExceeded:
            raise
        except Exception as exc:
            raise self._failure(exc) from None
        if len(names) > self.LIST_LIMIT:
            raise ObjectStoreError(f"too many objects: limit {self.LIST_LIMIT}")
        return names
