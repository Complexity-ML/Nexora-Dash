"""Conservative dependency inventory for retention planning; never deletes data."""
import json

KEY_FIELDS = {'key', 'manifest_key', 'enterprise_manifest', 'index_manifest_key',
              'previous_manifest', 'base_manifest', 'index_manifest', 'license_source_key', 'detail_key'}


def dependency_inventory(lake, artifacts):
    objects, tables, pending = set(), set(), list(artifacts)
    def safe(key):
        if not isinstance(key, str) or key.split('/')[0] not in ('bronze', 'silver', 'gold') or '..' in key.split('/'):
            raise ValueError('Invalid dependency key')
        return key
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, dict):
            if value.get('format') == 'delta':
                path = safe(value['path'])
                version = value['version']
                if type(version) is not int or version < 0:
                    raise ValueError('Invalid dependency version')
                tables.add((path, version))
            for field, item in value.items():
                if field in KEY_FIELDS and isinstance(item, str):
                    key = safe(item)
                    if key not in objects:
                        objects.add(key)
                        if key.endswith('.json'):
                            pending.append(json.loads(lake.get_bytes(key)))
                elif isinstance(item, (dict, list)):
                    pending.append(item)
    return {'objects': sorted(objects),
            'delta_versions': [{'path': path, 'version': version} for path, version in sorted(tables)]}
