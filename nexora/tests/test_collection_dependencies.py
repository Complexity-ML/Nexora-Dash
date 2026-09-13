from types import SimpleNamespace
import json
import pytest
from app.collection.dependencies import dependency_inventory


def test_dependencies_follow_imports_previous_generations_and_delta_versions():
    files = {
        'gold/current.json': {'enterprise_manifest': 'gold/inventory.json', 'previous_manifest': 'gold/old.json'},
        'gold/inventory.json': {'dimensions': {'machines': {'format': 'delta', 'path': 'silver/machines', 'version': 2}}},
        'gold/old.json': {'previous_manifest': 'gold/current.json',
                          'daily': [{'usage': {'format': 'delta', 'path': 'silver/machines', 'version': 1},
                                     'bronze': {'key': 'bronze/payload.json'}}]},
        'bronze/payload.json': {'payload_json': '{"key":"private/source-field"}'},
    }
    lake = SimpleNamespace(get_bytes=lambda key: json.dumps(files[key]).encode())
    result = dependency_inventory(lake, [{'manifest_key': 'gold/current.json'}])
    assert result['objects'] == sorted(files)
    assert result['delta_versions'] == [{'path': 'silver/machines', 'version': 1}, {'path': 'silver/machines', 'version': 2}]


def test_missing_dependency_stops_inventory():
    def missing(key):
        raise FileNotFoundError(key)
    with pytest.raises(FileNotFoundError):
        dependency_inventory(SimpleNamespace(get_bytes=missing), [{'key': 'gold/missing.json'}])


def test_dependency_rejects_relative_escape():
    with pytest.raises(ValueError):
        dependency_inventory(None, [{'key': 'gold/../../secret.json'}])
