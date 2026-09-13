"""Run all backend tests against the explicitly dedicated PostgreSQL test database."""
import os
import subprocess
from urllib.parse import urlsplit, urlunsplit
def main():
    url = urlsplit(os.environ['DATABASE_URL'])
    test_url = urlunsplit(url._replace(path='/sam_business_test'))
    env = {**os.environ, 'DATABASE_URL':test_url, 'BUSINESS_TEST_DATABASE_URL':test_url, 'SPARK_LOCAL_IP':'127.0.0.1'}
    subprocess.run(['alembic','upgrade','head'],env=env,check=True)
    subprocess.run(['pytest','-q','/app/tests'],env=env,check=True)


if __name__ == "__main__":
    main()
