"""Generate the least-privilege policy for a dedicated BI reader (no credentials)."""
import argparse
import json
import re


def policy(bucket, prefix):
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
        raise ValueError('Invalid bucket')
    prefix = prefix.strip('/')
    if not prefix or any(c in prefix for c in '*?') or '..' in prefix.split('/'):
        raise ValueError('An explicit Gold prefix is required')
    if not prefix.startswith('gold/') and '/gold/' not in prefix:
        raise ValueError('BI access must be limited to Gold')
    arn = f'arn:aws:s3:::{bucket}'
    return {'Version':'2012-10-17','Statement':[
        {'Effect':'Allow','Action':['s3:GetBucketLocation'],'Resource':[arn]},
        {'Effect':'Allow','Action':['s3:ListBucket'],'Resource':[arn],
         'Condition':{'StringLike':{'s3:prefix':[prefix+'/',prefix+'/*']}}},
        {'Effect':'Allow','Action':['s3:GetObject'],'Resource':[arn+'/'+prefix+'/*']},
    ]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bucket',required=True)
    parser.add_argument('--prefix',required=True,help='Published BI Gold prefix, including lake namespace')
    args = parser.parse_args()
    print(json.dumps(policy(args.bucket,args.prefix),indent=2))
