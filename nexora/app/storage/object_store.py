from abc import ABC, abstractmethod
from datetime import date
from io import BytesIO
import json

import boto3
import pyarrow as pa
import pyarrow.parquet as pq


class ObjectStore(ABC):
    """Replaceable Bronze/Silver/Gold object-storage contract."""
    @abstractmethod
    def put_json(self, key: str, value: object) -> None: ...
    @abstractmethod
    def put_parquet(self, key: str, rows: list[dict] | pa.Table) -> None: ...
    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]: ...
    @abstractmethod
    def get_bytes(self, key: str) -> bytes: ...


class S3ParquetStore(ObjectStore):
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, region: str, prefix: str = ""):
        self.prefix = prefix
        self.bucket = bucket
        from app.storage.delta_tables import DeltaTables
        options = {'AWS_ENDPOINT_URL': endpoint, 'AWS_ACCESS_KEY_ID': access_key,
                   'AWS_SECRET_ACCESS_KEY': secret_key, 'AWS_REGION': region,
                   'AWS_VIRTUAL_HOSTED_STYLE_REQUEST': 'false', 'conditional_put': 'etag'}
        if endpoint.startswith('http://'):
            options['allow_http'] = 'true'
        self.delta = DeltaTables(f's3://{bucket}/{prefix.strip("/")}', options)
        self.client = boto3.client("s3", endpoint_url=endpoint,
            aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region)
        try:
            self.client.head_bucket(Bucket=bucket)
        except Exception:
            self.client.create_bucket(Bucket=bucket)

    def put_json(self, key: str, value: object) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self.prefix+key,
            Body=json.dumps(value, default=str).encode(), ContentType="application/json")

    def put_parquet(self, key: str, rows: list[dict] | pa.Table) -> None:
        if not rows: return
        output = BytesIO()
        pq.write_table(rows if isinstance(rows, pa.Table) else pa.Table.from_pylist(rows), output, compression="snappy")
        self.client.put_object(Bucket=self.bucket, Key=self.prefix+key, Body=output.getvalue(),
                               ContentType="application/vnd.apache.parquet")

    def list_keys(self, prefix: str) -> list[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        return [
            item["Key"][len(self.prefix):]
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix+prefix)
            for item in page.get("Contents", [])
        ]

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self.prefix+key)["Body"].read()

    def usage_revision(self) -> str:
        """Detect additions, removals and overwrites without downloading Parquet."""
        import hashlib
        from app.storage import pool_tables
        if pool_tables.enabled(self):
            ref = pool_tables.reference(self)
            return f'delta:{ref.path}:{ref.version}' if ref else 'delta:empty'
        entries = [
            (item['Key'], item['ETag'], item['Size'])
            for page in self.client.get_paginator('list_objects_v2').paginate(
                Bucket=self.bucket, Prefix=self.prefix+'silver/usage/')
            for item in page.get('Contents', [])
        ]
        return hashlib.sha256(json.dumps(sorted(entries)).encode()).hexdigest()


def partition_key(layer: str, dataset: str, day: date, name: str) -> str:
    return f"{layer}/{dataset}/date={day.isoformat()}/{name}"
