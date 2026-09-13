import asyncio
from app.connectors.digimon import MockDigimonConnector, map_digimon_payload

def test_maps_intermediate_digimon_dto_to_canonical_model():
    result=map_digimon_payload({"capturedAt":"2026-09-11T10:00:00Z","provider":"mock","pools":[
        {"poolKey":"p1","product":{"key":"s1","name":"CAD"},"entitlement":10,"consumed":7}]})
    assert result.usage[0].license_pool_id == "p1"
    assert result.usage[0].available == 3
    assert result.stock[0].software_name == "CAD"

def test_implicit_mock_timestamp_is_refreshed_for_each_snapshot():
    connector = MockDigimonConnector()
    first = asyncio.run(connector.get_raw_snapshot())["capturedAt"]
    second = asyncio.run(connector.get_raw_snapshot())["capturedAt"]
    assert second >= first


import pytest


@pytest.mark.parametrize('quantity', [10, 10.0, '10'])
def test_integral_quantity_encodings_preserve_exact_value(quantity):
    result = map_digimon_payload({'capturedAt':'2026-01-01T00:00:00Z', 'pools':[
        {'poolKey':'p', 'product':{'key':'s','name':'Product'}, 'entitlement':quantity,'consumed':0}]})
    assert result.stock[0].capacity == 10


@pytest.mark.parametrize('quantity', [1.5, True, None, -1, '1.5', float('inf'), float('nan')])
def test_invalid_quantities_are_not_coerced(quantity):
    with pytest.raises(ValueError, match='integral pool quantity'):
        map_digimon_payload({'capturedAt':'2026-01-01T00:00:00Z', 'pools':[
            {'poolKey':'p', 'product':{'key':'s','name':'Product'}, 'entitlement':10,'consumed':quantity}]})


@pytest.mark.parametrize('field', ['poolKey', 'key', 'name'])
@pytest.mark.parametrize('value', [None, True, 123, '', '   ', {}, []])
def test_product_identity_is_not_synthesized_from_invalid_values(field, value):
    row = {'poolKey':'p', 'product':{'key':'s','name':'Product'}, 'entitlement':10,'consumed':0}
    (row if field == 'poolKey' else row['product'])[field] = value
    with pytest.raises(ValueError, match='non-empty source text'):
        map_digimon_payload({'capturedAt':'2026-01-01T00:00:00Z', 'pools':[row]})


@pytest.mark.parametrize('captured_at', ['2026-01-01', '2026-01-01T04:00:00'])
def test_source_timestamp_requires_explicit_timezone(captured_at):
    with pytest.raises(ValueError, match='timezone offset'):
        map_digimon_payload({'capturedAt':captured_at, 'pools':[]})


def test_source_offset_and_calendar_day_are_preserved():
    from datetime import timedelta
    result = map_digimon_payload({'capturedAt':'2026-01-01T00:30:00+02:00', 'pools':[]})
    assert result.timestamp.isoformat() == '2026-01-01T00:30:00+02:00'
    assert result.timestamp.utcoffset() == timedelta(hours=2)
