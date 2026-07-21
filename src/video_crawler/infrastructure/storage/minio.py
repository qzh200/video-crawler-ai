from __future__ import annotations

import asyncio
import io
from collections.abc import Iterable
from typing import Protocol, cast

from minio import Minio
from minio.commonconfig import CopySource

from video_crawler.domain.artifacts import ObjectInfo, ObjectStat
from video_crawler.domain.artifacts import build_object_key as build_object_key


class ObjectClient(Protocol):
    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: io.BytesIO,
        length: int,
        **kwargs: object,
    ) -> object: ...

    def stat_object(self, bucket_name: str, object_name: str) -> ObjectStat: ...

    def copy_object(self, bucket_name: str, object_name: str, source: CopySource) -> object: ...

    def remove_object(self, bucket_name: str, object_name: str) -> None: ...

    def list_objects(
        self, bucket_name: str, prefix: str = "", recursive: bool = False
    ) -> Iterable[ObjectInfo]: ...


class MinioRawArtifactStore:
    """Small async facade over the synchronous MinIO Python SDK."""

    def __init__(
        self,
        client: ObjectClient | None = None,
        *,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool = False,
    ) -> None:
        if client is not None:
            self.client = client
        elif endpoint and access_key and secret_key:
            self.client = cast(
                ObjectClient,
                Minio(
                    endpoint,
                    access_key=access_key,
                    secret_key=secret_key,
                    secure=secure,
                ),
            )
        else:
            raise ValueError("client or MinIO connection settings are required")

    async def put(
        self,
        bucket: str,
        object_key: str,
        content: bytes,
        *,
        content_type: str,
        compression: str,
        sha256: str,
    ) -> ObjectStat:
        metadata = {
            "x-amz-meta-sha256": sha256,
            "x-amz-meta-compression": compression,
        }
        await asyncio.to_thread(
            self.client.put_object,
            bucket,
            object_key,
            io.BytesIO(content),
            len(content),
            content_type=content_type,
            metadata=metadata,
        )
        return await asyncio.to_thread(self.client.stat_object, bucket, object_key)

    async def stat(self, bucket: str, object_key: str) -> ObjectStat:
        return await asyncio.to_thread(self.client.stat_object, bucket, object_key)

    async def copy(self, bucket: str, source_key: str, destination_key: str) -> ObjectStat:
        await asyncio.to_thread(
            self.client.copy_object,
            bucket,
            destination_key,
            CopySource(bucket, source_key),
        )
        return await self.stat(bucket, destination_key)

    async def remove(self, bucket: str, object_key: str) -> None:
        await asyncio.to_thread(self.client.remove_object, bucket, object_key)

    async def list(self, bucket: str, prefix: str) -> tuple[ObjectInfo, ...]:
        return await asyncio.to_thread(
            lambda: tuple(self.client.list_objects(bucket, prefix=prefix, recursive=True))
        )
