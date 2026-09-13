"""Plan or remove obsolete inventory projections; retain lake and run metadata."""
import argparse
import json
from app.business.store import BusinessStore
from app.business.index_retention import prune_index_cache
from app.config import get_settings
from app.dependencies import get_pipeline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Remove only unreferenced SQL projection rows')
    args=parser.parse_args()
    print(json.dumps(prune_index_cache(BusinessStore(get_settings().database_url),get_pipeline().store,apply=args.apply)))


if __name__=='__main__': main()
