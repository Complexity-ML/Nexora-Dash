"""Read a single committed collection version, never a mixture of latest tables."""
import json
from io import BytesIO
import pyarrow.parquet as pq
import pyarrow as pa
from app.collection.journal import fingerprint
from app.collection.runner import encoded
from app.models.canonical import AnalyticsSummary
from app.models.inventory import InventorySnapshot
from app.storage.table_reader import read_table


class PublishedCollection:
    def __init__(self,lake,journal,source,scope):
        head=journal.published_artifact(lake.prefix,source,scope)
        self.lake=lake
        self.manifest=None
        self.manifest_key=None
        if head is None or head['run_id'] is None:
            return
        artifact=head['artifact']
        if not artifact or artifact['manifest_key'] != head['manifest_key']:
            raise ValueError('Publication does not match its Gold checkpoint')
        manifest=json.loads(lake.get_bytes(head['manifest_key']))
        if fingerprint(encoded(manifest)) != artifact['fingerprint'] or manifest['run_id'] != head['run_id']:
            raise ValueError('Publication metadata integrity check failed')
        if manifest['source'] != source or manifest['scope'] != scope:
            raise ValueError('Publication scope mismatch')
        self.manifest=manifest
        self.manifest_key=head['manifest_key']

    def summary(self):
        if self.manifest is None:
            return None
        rows=read_table(self.lake,self.manifest['gold']).to_pylist()
        if len(rows)!=1:
            raise ValueError('Invalid published Gold summary')
        return AnalyticsSummary.model_validate_json(rows[0]['summary_json'])

    def usage(self):
        if self.manifest is None:
            return None
        tables=[read_table(self.lake,item['usage']) for _,item in sorted(self.manifest['daily'].items())]
        return pa.concat_tables([t.drop(['observation_date']) if 'observation_date' in t.column_names else t for t in tables])

    def inventory(self):
        if not self.manifest or not self.manifest['daily']:
            return None
        latest=self.manifest['daily'][max(self.manifest['daily'])]
        if latest['inventory'] is None:
            return None  # An older inventory is not presented as today's observation.
        rows=read_table(self.lake,latest['inventory']).to_pylist()
        if len(rows)!=1:
            raise ValueError('Invalid published inventory')
        return InventorySnapshot.model_validate_json(rows[0]['snapshot_json'])

    def latest_snapshot(self):
        if not self.manifest or not self.manifest['daily']:
            return None
        from app.connectors.digimon import map_digimon_payload
        latest=self.manifest['daily'][max(self.manifest['daily'])]
        reference=latest['bronze']
        envelope = (pq.read_table(BytesIO(self.lake.get_bytes(reference['key']))).to_pylist()[reference.get('row_index',0)]
                    if reference.get('format') == 'parquet' else json.loads(self.lake.get_bytes(reference['key'])))
        if fingerprint(envelope['payload_json'].encode()) != reference['fingerprint']:
            raise ValueError('Published source integrity check failed')
        return map_digimon_payload(json.loads(envelope['payload_json']))
