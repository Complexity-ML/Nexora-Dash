"""Versioned Delta tables; published manifests pin every table version.

Raw source payloads remain immutable objects. Consumers must read Delta's log,
never enumerate the Parquet files inside a Delta table.
"""
from dataclasses import asdict, dataclass
from datetime import date
import re
from uuid import uuid4

import pyarrow as pa
from deltalake import CommitProperties, DeltaTable, write_deltalake


@dataclass(frozen=True)
class DeltaReference:
    path: str
    version: int
    format: str = 'delta'
    observation_date: str | None = None

    def to_dict(self):
        return asdict(self)


class DeltaTables:
    def __init__(self, root: str, storage_options: dict[str, str] | None = None):
        self.root = root.rstrip('/')
        self.storage_options = storage_options or {}

    def uri(self, path: str):
        if not re.fullmatch(r'(silver|gold)/[a-zA-Z0-9_/-]+', path) or '..' in path:
            raise ValueError('Invalid Delta table path')
        return f'{self.root}/{path}'

    def open(self, reference: DeltaReference):
        if reference.format != 'delta' or type(reference.version) is not int or reference.version < 0:
            raise ValueError('Invalid Delta reference')
        return DeltaTable(self.uri(reference.path), version=reference.version,
                          storage_options=self.storage_options)

    def read(self, reference: DeltaReference, *, columns=None, filters=None):
        if reference.observation_date is not None:
            partition = ('observation_date', '=', date.fromisoformat(reference.observation_date))
            if filters and isinstance(filters[0], list):
                filters = [group + [partition] for group in filters]
            else:
                filters = list(filters or []) + [partition]
        return self.open(reference).to_pyarrow_table(columns=columns, filters=filters)

    def replace(self, path: str, rows: pa.Table):
        """Atomically replace a dimension or Gold table, preserving its old versions."""
        return self._write(path, rows)

    def replace_day(self, path: str, day: date, rows: pa.Table):
        """Idempotent daily snapshot, with a typed partition and strict schema."""
        if 'observation_date' not in rows.column_names:
            rows = rows.append_column('observation_date', pa.array([day] * len(rows), type=pa.date32()))
        dates = rows.column('observation_date')
        if dates.type != pa.date32() or any(value != day for value in dates.to_pylist()):
            raise ValueError('Partition contains an invalid observation date')
        return self._write(path, rows, partition_by=['observation_date'],
                           predicate=f"observation_date = '{day.isoformat()}'")

    def _write(self, path, rows, **options):
        operation = str(uuid4())
        write_deltalake(self.uri(path), rows, mode='overwrite',
                        storage_options=self.storage_options,
                        commit_properties=CommitProperties(custom_metadata={'nexora_operation': operation}),
                        **options)
        # A second writer may commit before this read. Pin our commit, not theirs.
        table = DeltaTable(self.uri(path), storage_options=self.storage_options)
        commits = table.history(limit=1)
        if not commits or commits[0].get('nexora_operation') != operation:
            commits = table.history()
        if table.version() % 10 == 0:
            table.create_checkpoint()
        for commit in commits:
            if commit.get('nexora_operation') == operation:
                return DeltaReference(path, commit['version'])
        raise RuntimeError('Committed Delta version could not be identified')

    def compact(self, reference: DeltaReference, *, target_size=134217728):
        """Produce a compacted candidate; never advance a publication or vacuum.

        Callers must publish the returned reference through their manifest CAS.
        Concurrent commits are distinguished by an operation marker.
        """
        if type(target_size) is not int or not 1048576 <= target_size <= 1073741824:
            raise ValueError('Compaction target must be between 1 MiB and 1 GiB')
        table = self.open(reference)
        if self.latest(reference.path).version != reference.version:
            raise ValueError('Compaction requires the current table version')
        operation = str(uuid4())
        metrics = table.optimize.compact(target_size=target_size, max_concurrent_tasks=1,
            commit_properties=CommitProperties(custom_metadata={'nexora_operation': operation,
                'nexora_maintenance': 'compaction', 'nexora_base_version': str(reference.version)}))
        if not metrics.get('numFilesAdded') and not metrics.get('numFilesRemoved'):
            return reference, metrics
        # Never select another writer's newest commit as our compacted candidate.
        latest = DeltaTable(self.uri(reference.path), storage_options=self.storage_options)
        for commit in latest.history():
            if commit.get('nexora_operation') == operation:
                return DeltaReference(reference.path, commit['version'],
                                      observation_date=reference.observation_date), metrics
        raise RuntimeError('Compaction commit could not be identified')

    def latest(self, path: str):
        table = DeltaTable(self.uri(path), storage_options=self.storage_options)
        return DeltaReference(path, table.version())


def s3_delta_tables(settings, prefix: str):
    # Conditional puts provide concurrency control on MinIO. Never enable unsafe rename.
    options = {
        'AWS_ENDPOINT_URL': settings.s3_endpoint_url,
        'AWS_ACCESS_KEY_ID': settings.s3_access_key,
        'AWS_SECRET_ACCESS_KEY': settings.s3_secret_key,
        'AWS_REGION': settings.s3_region,
        'AWS_VIRTUAL_HOSTED_STYLE_REQUEST': 'false',
        'conditional_put': 'etag',
    }
    if settings.s3_endpoint_url.startswith('http://'):
        options['allow_http'] = 'true'
    return DeltaTables(f's3://{settings.s3_bucket}/{prefix.strip("/")}', options)
