"""S3-compatible object storage service.

ARCH-002: Single source of truth for all S3 operations (upload, download, bucket creation).
"""

import functools
import io

import boto3
import structlog
from botocore.config import Config
from botocore.exceptions import ClientError

logger = structlog.get_logger()


@functools.lru_cache(maxsize=4)
def get_s3_client(endpoint_url: str, region: str, access_key: str, secret_key: str):
    """Get a cached boto3 S3 client (one instance per unique settings combination)."""
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            s3={"addressing_style": "path"},
            proxies={},  # bypass system proxy for local MinIO
        ),
    )


def ensure_bucket(
    endpoint_url: str,
    region: str,
    access_key: str,
    secret_key: str,
    bucket: str,
) -> None:
    """Ensure the S3 bucket exists, creating it if necessary."""
    client = get_s3_client(endpoint_url, region, access_key, secret_key)
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)
        logger.info("s3_bucket_created", bucket=bucket)


def upload_document(
    endpoint_url: str,
    region: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    object_key: str,
    document_bytes: bytes,
) -> None:
    """Upload a document to S3-compatible storage."""
    client = get_s3_client(endpoint_url, region, access_key, secret_key)
    try:
        client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=io.BytesIO(document_bytes),
            ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        logger.info("document_uploaded", key=object_key, size=len(document_bytes))
    except ClientError as e:
        logger.error("s3_upload_failed", key=object_key, error=str(e))
        raise


def generate_presigned_url(
    endpoint_url: str,
    region: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    object_key: str,
    expires_in: int = 7 * 24 * 60 * 60,
) -> str:
    """Generate a pre-signed URL for downloading an object."""
    client = get_s3_client(endpoint_url, region, access_key, secret_key)
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_key},
        ExpiresIn=expires_in,
    )


def download_document(
    endpoint_url: str,
    region: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    object_key: str,
) -> bytes:
    """Download a document from S3-compatible storage."""
    client = get_s3_client(endpoint_url, region, access_key, secret_key)
    try:
        response = client.get_object(Bucket=bucket, Key=object_key)
        return response["Body"].read()
    except ClientError as e:
        logger.error("s3_download_failed", key=object_key, error=str(e))
        raise
