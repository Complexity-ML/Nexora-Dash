"""Verify least-privilege BI access using a disposable MinIO user and bucket."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', default='docker')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo/'nexora'))
    from scripts.bi_s3_policy import policy
    name = 'bi-proof-' + uuid4().hex
    secret = secrets.token_urlsafe(32)
    folder = '/tmp/' + name
    compose = [args.docker, 'compose']
    def execute(parts, data=None, check=True):
        return subprocess.run(compose + parts, cwd=repo, input=data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)
    def inside(parts, data=None, check=True):
        return execute(['exec', '-T', 'minio', *parts], data, check)
    def mc(*parts, data=None, check=True):
        return inside(['mc', '--config-dir', folder, *parts], data, check)
    bucket_created = False
    try:
        inside(['sh', '-c', 'mkdir -p "$1"; mc --config-dir "$1" alias set proof http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"', 'sh', folder])
        mc('mb', 'proof/' + name)
        bucket_created = True
        for key in ('gold/bi/report.json', 'gold/other/report.json', 'bronze/raw.json', 'silver/inventory.json'):
            mc('pipe', 'proof/' + name + '/' + key, data=b'{"synthetic":true}')
        inside(['sh', '-c', 'cat > "$1"', 'sh', folder + '/policy.json'],
               json.dumps(policy(name, 'gold/bi')).encode())
        mc('admin', 'policy', 'create', 'proof', name, folder + '/policy.json')
        # Piped keys avoid exposing the temporary secret in process arguments or logs.
        mc('admin', 'user', 'add', 'proof', data=(name+'\n'+secret+'\n').encode())
        mc('admin', 'policy', 'attach', 'proof', name, '--user', name)
        seed = """
import json,sys
import pyarrow as pa
from app.config import get_settings
from app.storage.delta_tables import s3_delta_tables
settings=get_settings().model_copy(update={'s3_bucket':json.load(sys.stdin)['bucket']})
tables=s3_delta_tables(settings,'')
first=tables.replace('gold/bi/usage',pa.table({'used':[10]}))
second=tables.replace('gold/bi/usage',pa.table({'used':[20]}))
assert first.version==0 and second.version==1
"""
        execute(['run', '--rm', '--no-deps', '-T', '-v', str(repo/'nexora')+':/app', 'dash', 'python', '-c', seed],
                json.dumps({'bucket':name}).encode())
        code = '''
import json,sys
import boto3
from botocore.exceptions import ClientError
r=json.load(sys.stdin)
s=boto3.client('s3',endpoint_url='http://minio:9000',aws_access_key_id=r['key'],aws_secret_access_key=r['secret'],region_name='us-east-1')
b=r['bucket']
assert s.get_object(Bucket=b,Key='gold/bi/report.json')['Body'].read()==b'{"synthetic":true}'
keys=[o['Key'] for o in s.list_objects_v2(Bucket=b,Prefix='gold/bi/')['Contents']]
assert 'gold/bi/report.json' in keys and all(k.startswith('gold/bi/') for k in keys)
s.get_bucket_location(Bucket=b)
checks={
 'bronze_read':lambda:s.get_object(Bucket=b,Key='bronze/raw.json'),
 'silver_read':lambda:s.get_object(Bucket=b,Key='silver/inventory.json'),
 'other_gold_read':lambda:s.get_object(Bucket=b,Key='gold/other/report.json'),
 'root_list':lambda:s.list_objects_v2(Bucket=b),
 'silver_list':lambda:s.list_objects_v2(Bucket=b,Prefix='silver/'),
 'write':lambda:s.put_object(Bucket=b,Key='gold/bi/forbidden.json',Body=b'test'),
 'delete':lambda:s.delete_object(Bucket=b,Key='gold/bi/report.json')}
for label,operation in checks.items():
 try: operation()
 except ClientError as e:
  assert e.response['Error']['Code']=='AccessDenied', label
 else: raise AssertionError('Unexpected permission: '+label)
from types import SimpleNamespace
from app.storage.delta_tables import s3_delta_tables,DeltaReference
settings=SimpleNamespace(s3_endpoint_url='http://minio:9000',s3_access_key=r['key'],s3_secret_key=r['secret'],s3_region='us-east-1',s3_bucket=b)
tables=s3_delta_tables(settings,'')
assert tables.read(DeltaReference('gold/bi/usage',0)).to_pylist()==[{'used':10}]
assert tables.read(tables.latest('gold/bi/usage')).to_pylist()==[{'used':20}]
print(json.dumps({'gold_read':True,'gold_list':True,'delta_pinned_version':0,'delta_latest_version':1,'denied':list(checks)}))
'''
        result = execute(['run', '--rm', '--no-deps', '-T', '-v', str(repo/'nexora')+':/app', 'dash', 'python', '-c', code],
                         json.dumps({'key':name, 'secret':secret, 'bucket':name}).encode())
        print(result.stdout.decode().strip())
    finally:
        # Only names generated for this fixture are removed; never the demo bucket.
        cleanup = [mc('admin', 'user', 'remove', 'proof', name, check=False),
                   mc('admin', 'policy', 'remove', 'proof', name, check=False)]
        if bucket_created:
            cleanup.extend([mc('rm', '--recursive', '--force', 'proof/'+name, check=False),
                            mc('rb', 'proof/'+name, check=False)])
        inside(['rm', '-rf', folder], check=False)
        if any(item.returncode for item in cleanup):
            raise RuntimeError('Temporary BI fixture cleanup requires inspection')


if __name__ == '__main__':
    main()
