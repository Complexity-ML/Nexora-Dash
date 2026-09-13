"""Start PostgreSQL with a per-job credential on an isolated CI runner."""
import os
import secrets
import subprocess
import time
from pathlib import Path
password=secrets.token_hex(24)
print(f'::add-mask::{password}',flush=True)
subprocess.run(['docker','run','-d','--name','sam-test-postgres','-p','127.0.0.1:5432:5432',
                '-e','POSTGRES_USER=sam','-e','POSTGRES_DB=sam_test','-e','POSTGRES_PASSWORD',
                'postgres:17-alpine'],env={**os.environ,'POSTGRES_PASSWORD':password},check=True)
for attempt in range(30):
    result=subprocess.run(['docker','exec','sam-test-postgres','pg_isready','-U','sam','-d','sam_test'],capture_output=True)
    if result.returncode==0:break
    time.sleep(1)
else:raise SystemExit('PostgreSQL did not become ready')
url=f'postgresql://sam:{password}@127.0.0.1:5432/sam_test'
with Path(os.environ['GITHUB_ENV']).open('a') as output:
    output.write(f'DATABASE_URL={url}\nBUSINESS_TEST_DATABASE_URL={url}\n')
