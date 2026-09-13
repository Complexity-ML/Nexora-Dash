"""Provision a scoped BI reader into a private file, never standard output."""
import argparse
import json
import os
from pathlib import Path
from app.bi.auth import issue_reader
from app.business.store import BusinessStore
from app.config import get_settings


def provision(store, *, namespace, audience, output, lifetime_hours=24):
    path = Path(output)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # Pin the parent directory and refuse existing files, including symlinks.
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                             0o600, dir_fd=directory)
        with os.fdopen(descriptor, 'w') as stream:
            def deliver(credential):
                json.dump({**credential, 'namespace':namespace, 'audience':audience}, stream)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
                os.fsync(directory)
            credential = issue_reader(store, namespace=namespace, audience=audience,
                                      lifetime_hours=lifetime_hours, deliver=deliver)
    finally:
        os.close(directory)
    # Keep any failed output for inspection, never remove a replaced path.
    return {key:credential[key] for key in ('id', 'expires_at')}



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--namespace')
    scope.add_argument('--root', action='store_true')
    parser.add_argument('--audience', required=True)
    parser.add_argument('--output', required=True, help='New file in a private directory outside Git')
    parser.add_argument('--lifetime-hours', type=int, default=24)
    args = parser.parse_args()
    if not args.root and not args.namespace.strip():
        parser.error('An explicit non-empty namespace is required')
    try:
        result = provision(BusinessStore(get_settings().database_url),
                           namespace='' if args.root else args.namespace,
                           audience=args.audience, output=args.output,
                           lifetime_hours=args.lifetime_hours)
    except Exception:
        print(json.dumps({'status':'failed', 'error_code':'BI_PROVISIONING_FAILED'}))
        return 1
    print(json.dumps({'status':'created', **result}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
