from __future__ import annotations

from collections.abc import Iterable

import pytest
from google.api_core.exceptions import PreconditionFailed
from google.cloud.storage.retry import ConditionalRetryPolicy

from doug.example_pack import ContentCollisionError
from doug.example_pack_gcs import (
    CaptureBudgetExceeded,
    GcsObjectStore,
    ObjectStoreError,
    StorageBudget,
)


class Clock:
    def __init__(self, *values: float):
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


class FakeBlob:
    def __init__(self, name: str, objects: dict[str, bytes]):
        self.name = name
        self.objects = objects
        self.uploads: list[tuple[bytes, dict[str, object]]] = []
        self.downloads: list[dict[str, object]] = []

    def upload_from_string(self, data: bytes, **kwargs: object) -> None:
        self.uploads.append((data, kwargs))
        if self.name in self.objects:
            raise PreconditionFailed("server response must not escape")
        self.objects[self.name] = data

    def download_as_bytes(self, **kwargs: object) -> bytes:
        self.downloads.append(kwargs)
        if self.name not in self.objects:
            raise RuntimeError("not found at gs://secret-bucket/private-object")
        return self.objects[self.name]


class FakeBucket:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.blobs: dict[str, FakeBlob] = {}

    def blob(self, name: str) -> FakeBlob:
        return self.blobs.setdefault(name, FakeBlob(name, self.objects))


class FakeClient:
    def __init__(self, names: Iterable[str] = ()):  # complete external boundary
        self.objects = {name: name.encode() for name in names}
        self.bucket_value = FakeBucket(self.objects)
        self.list_calls: list[dict[str, object]] = []

    def bucket(self, name: str) -> FakeBucket:
        assert name == "private-evidence"
        return self.bucket_value

    def list_blobs(self, bucket: FakeBucket, **kwargs: object) -> list[FakeBlob]:
        assert bucket is self.bucket_value
        self.list_calls.append(kwargs)
        prefix = str(kwargs["prefix"])
        maximum = int(kwargs["max_results"])
        matching = [
            FakeBlob(name, self.objects)
            for name in sorted(self.objects)
            if name.startswith(prefix)
        ]
        return matching[:maximum]


def test_create_is_generation_zero_and_bounded_by_one_budget():
    client = FakeClient()
    budget = StorageBudget(seconds=5, monotonic=Clock(10.0, 11.25))
    store = GcsObjectStore("private-evidence", client=client, budget=budget)

    store.create("cohorts/c1/cohort.json", b"{}", content_type="application/json")

    [(data, kwargs)] = client.bucket_value.blob("cohorts/c1/cohort.json").uploads
    assert data == b"{}"
    assert kwargs["if_generation_match"] == 0
    assert kwargs["content_type"] == "application/json"
    assert kwargs["timeout"] == pytest.approx(3.75)
    assert isinstance(kwargs["retry"], ConditionalRetryPolicy)
    assert kwargs["retry"].retry_policy._deadline == pytest.approx(3.75)


def test_create_only_collision_is_idempotent_only_for_identical_bytes():
    client = FakeClient(["cohorts/c1/cohort.json"])
    client.objects["cohorts/c1/cohort.json"] = b"same"
    store = GcsObjectStore("private-evidence", client=client)

    store.create("cohorts/c1/cohort.json", b"same", content_type="application/json")
    with pytest.raises(ContentCollisionError, match="different bytes"):
        store.create("cohorts/c1/cohort.json", b"different", content_type="application/json")


def test_budget_expiry_prevents_the_next_storage_call():
    client = FakeClient()
    budget = StorageBudget(seconds=5, monotonic=Clock(10.0, 15.0))
    store = GcsObjectStore("private-evidence", client=client, budget=budget)

    with pytest.raises(CaptureBudgetExceeded, match="budget exhausted"):
        store.create("cohorts/c1/cohort.json", b"{}", content_type="application/json")

    assert client.bucket_value.blobs == {}


def test_list_is_prefix_scoped_sorted_and_refuses_a_partial_501st_result():
    names = [f"cohorts/c1/packs/sha256/{index:04d}.json" for index in range(501)]
    client = FakeClient(reversed(names))
    store = GcsObjectStore("private-evidence", client=client)

    with pytest.raises(ObjectStoreError, match="too many objects"):
        store.list("cohorts/c1/packs/sha256/")

    [call] = client.list_calls
    assert call["prefix"] == "cohorts/c1/packs/sha256/"
    assert call["max_results"] == 501


def test_external_exception_details_are_reduced_to_the_error_class():
    client = FakeClient()
    store = GcsObjectStore("private-evidence", client=client)

    with pytest.raises(ObjectStoreError) as raised:
        store.read("cohorts/c1/missing.json")

    assert str(raised.value) == "object storage failed: RuntimeError"
    assert "secret-bucket" not in str(raised.value)
