"""Retire BI reader credentials in one restored namespace before reopening access."""
import argparse
import json
from app.bi.auth import revoke_namespace_readers
from app.business.store import BusinessStore
from app.config import get_settings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    scope=parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--namespace')
    scope.add_argument('--root', action='store_true', help='Select exactly the empty root namespace')
    parser.add_argument('--apply', action='store_true', help='Revoke all existing readers in this namespace')
    args=parser.parse_args()
    if not args.root and not args.namespace.strip():
        parser.error('An explicit non-empty namespace is required')
    try:
        result=revoke_namespace_readers(BusinessStore(get_settings().database_url),
                                        namespace='' if args.root else args.namespace,apply=args.apply)
    except Exception:
        print(json.dumps({'status':'failed','error_code':'BI_RECONCILIATION_FAILED'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
