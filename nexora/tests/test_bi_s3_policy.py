import pytest
from scripts.bi_s3_policy import policy


def test_reader_can_only_list_and_read_published_gold():
    statements = policy('nexora-lake','demo/gold/bi')['Statement']
    assert {a for s in statements for a in s['Action']} == {'s3:GetBucketLocation','s3:ListBucket','s3:GetObject'}
    assert statements[1]['Condition']['StringLike']['s3:prefix'] == ['demo/gold/bi/','demo/gold/bi/*']
    assert statements[2]['Resource'] == ['arn:aws:s3:::nexora-lake/demo/gold/bi/*']


@pytest.mark.parametrize('prefix',['','demo','silver/inventory','demo/gold/*','demo/gold/../silver'])
def test_refuses_broad_or_non_gold_access(prefix):
    with pytest.raises(ValueError):
        policy('nexora-lake',prefix)
