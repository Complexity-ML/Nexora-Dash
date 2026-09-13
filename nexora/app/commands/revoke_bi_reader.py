"""Revoke one BI reader by identity, without accepting or displaying its secret."""
import argparse
import json
from uuid import UUID
from app.bi.auth import revoke_reader
from app.business.store import BusinessStore
from app.config import get_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--namespace')
    scope.add_argument('--root', action='store_true')
    parser.add_argument('--reader-id', required=True, type=UUID)
    args = parser.parse_args()
    if not args.root and not args.namespace.strip():
        parser.error('An explicit non-empty namespace is required')
    try:
        found = revoke_reader(BusinessStore(get_settings().database_url),
                              namespace='' if args.root else args.namespace,
                              reader_id=str(args.reader_id))
    except Exception:
        print(json.dumps({'status':'failed', 'error_code':'BI_REVOCATION_FAILED'}))
        return 1
    print(json.dumps({'status':'revoked' if found else 'not_found', 'id':str(args.reader_id)}))
    return 0 if found else 1


if __name__ == '__main__':
    raise SystemExit(main())
