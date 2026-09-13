from app.storage.object_store import S3ParquetStore

class Paginator:
    def paginate(self, **kwargs):
        assert kwargs == {"Bucket":"sam","Prefix":"silver/"}
        return [{"Contents":[{"Key":"silver/one"}]},{"Contents":[{"Key":"silver/two"}]}]
class Client:
    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return Paginator()

def test_s3_listing_consumes_every_page():
    store=S3ParquetStore.__new__(S3ParquetStore)
    store.prefix=""; store.bucket="sam"; store.client=Client()
    assert store.list_keys("silver/") == ["silver/one","silver/two"]

def test_generation_namespace_is_applied_to_reads_writes_and_listing():
    from io import BytesIO
    class NamespacedClient:
        def __init__(self): self.values = {}
        def put_object(self, Bucket, Key, Body, **kwargs):
            assert Bucket == 'sam'
            self.values[Key] = Body
        def get_object(self, Bucket, Key):
            return {'Body': BytesIO(self.values[Key])}
        def get_paginator(self, _): return self
        def paginate(self, Bucket, Prefix):
            assert Prefix == 'demo-generations/test/silver/'
            return [{'Contents':[{'Key':k} for k in self.values if k.startswith(Prefix)]}]
    store = S3ParquetStore.__new__(S3ParquetStore)
    store.bucket='sam'; store.prefix='demo-generations/test/'; store.client=NamespacedClient()
    store.put_json('silver/example.json', {'value':1})
    store.put_parquet('silver/example.parquet', [{'value':2}])
    assert store.list_keys('silver/') == ['silver/example.json', 'silver/example.parquet']
    assert store.get_bytes('silver/example.json') == b'{"value": 1}'
    assert store.get_bytes('silver/example.parquet').startswith(b'PAR1')
