"""Prepare a journaled publication from existing Delta; activation is separate."""
import argparse
import json
from app.dependencies import get_pipeline
from app.config import get_settings
from app.business.store import BusinessStore
from app.collection.journal import CollectionJournal
from app.collection.import_existing import prepare_existing, activate_existing, verify_existing


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--activate-artifact',help='Path to JSON returned by preparation')
    mode.add_argument('--verify-artifact',help='Verify a prepared import without activating it')
    parser.add_argument('--writers-stopped',action='store_true')
    args=parser.parse_args()
    settings=get_settings()
    if settings.collection_enabled:
        raise RuntimeError('Run import before enabling collection mode')
    pipeline=get_pipeline(); journal=CollectionJournal(BusinessStore(settings.database_url))
    if args.verify_artifact:
        from pathlib import Path
        artifact=json.loads(Path(args.verify_artifact).read_text())
        result=verify_existing(pipeline,journal,artifact)
        print(json.dumps({'verified':True,'activated':False,'run_id':result['run_id'],
            'enterprise_checks':journal.checkpoints(result['run_id'])['validated']['enterprise_checks']}))
    elif args.activate_artifact:
        if not args.writers_stopped:
            raise RuntimeError('Stop legacy writers and explicitly acknowledge --writers-stopped')
        from pathlib import Path
        artifact=json.loads(Path(args.activate_artifact).read_text())
        result=activate_existing(pipeline,journal,artifact)
        print(json.dumps({'activated':True,'run_id':result['run_id']}))
    else:
        result=prepare_existing(pipeline,journal,source='digimon-mock' if settings.sam_data_source=='mock' else settings.collection_source,scope=settings.collection_scope)
        print(json.dumps(result))


if __name__=='__main__': main()
