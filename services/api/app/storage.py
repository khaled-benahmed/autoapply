from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from .config import settings


class ObjectStorage:
    def __init__(self) -> None:
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            region_name="us-east-1",
        )
        self.bucket = settings.storage_bucket

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put_pdf(self, object_name: str, file_object: BinaryIO) -> str:
        self.ensure_bucket()
        self.client.upload_fileobj(
            file_object,
            self.bucket,
            object_name,
            ExtraArgs={"ContentType": "application/pdf"},
        )
        return f"s3://{self.bucket}/{object_name}"