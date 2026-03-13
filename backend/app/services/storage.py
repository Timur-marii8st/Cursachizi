"""S3-compatible object storage service."""

import functools
import io
import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=4)
def get_s3_client(endpoint_url: str, region: str, access_key: str, secret_key: str):
    """Get a cached boto3 S3 client (one instance per unique settings combination)."""
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


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
        logger.info("document_uploaded", extra={"key": object_key, "size": len(document_bytes)})
    except ClientError as e:
        logger.error("s3_upload_failed", extra={"key": object_key, "error": str(e)})
        raise


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
        logger.error("s3_download_failed", extra={"key": object_key, "error": str(e)})
        raise
