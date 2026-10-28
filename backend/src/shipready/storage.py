"""Object storage for uploaded files: any S3-compatible service, configured from the environment.

SeaweedFS runs locally (docker-compose.yml); Cloudflare R2 is used when deployed. Both speak the S3
API, so only the environment differs.

    uv run --env-file .env python -m shipready.storage    # create the local bucket once
"""

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    # Type stubs are a development dependency only.
    from mypy_boto3_s3 import S3Client

_REQUIRED = ("S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")


@dataclass(frozen=True)
class StorageSettings:
    endpoint_url: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str = "auto"  # R2 takes "auto"; MinIO accepts any region


def settings_from_env() -> StorageSettings:
    missing = [name for name in _REQUIRED if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"{', '.join(missing)} not set; see backend/.env.example")
    return StorageSettings(
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        bucket=os.environ["S3_BUCKET"],
        access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        region=os.environ.get("S3_REGION", "auto"),
    )


class Storage:
    def __init__(self, client: "S3Client", bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    def put(self, key: str, data: bytes, media_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=media_type)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def make_storage(settings: StorageSettings) -> Storage:
    client = boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name=settings.region,
        # Fail in seconds rather than hang a request when storage is unreachable.
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
    )
    return Storage(client, settings.bucket)


def ensure_bucket(storage: Storage) -> bool:
    """Create the bucket if it does not exist; True if it was created. For local storage only:
    deployed buckets are created in the provider's console, and API tokens may not create them."""
    try:
        storage.client.head_bucket(Bucket=storage.bucket)
        return False
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
            raise
    storage.client.create_bucket(Bucket=storage.bucket)
    return True


def main() -> None:
    storage = make_storage(settings_from_env())
    created = ensure_bucket(storage)
    print(f"bucket {storage.bucket} {'created' if created else 'already exists'}")


if __name__ == "__main__":
    main()
