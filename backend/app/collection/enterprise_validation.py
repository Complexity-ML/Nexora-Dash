"""Validate retained enterprise dependencies before importing their manifest."""
import json
from app.collection.journal import fingerprint
from app.collection.runner import encoded
from app.storage.table_reader import read_table


def verify_enterprise(lake, manifest):
    counts = {}
    for name, reference in manifest['dimensions'].items():
        count = read_table(lake, reference, columns=[]).num_rows
        if reference.get('rows') is not None and count != reference['rows']:
            raise ValueError(f'Inventory dimension count mismatch: {name}')
        counts[name] = count
    histories = {}
    for field in ('daily', 'product_usage_daily'):
        days = {}
        for reference in manifest.get(field, []):
            day = reference['date']
            if day in days:
                raise ValueError(f'Duplicate enterprise observation day: {field}')
            if reference.get('format') == 'delta' and reference.get('observation_date') != day:
                raise ValueError(f'Enterprise partition does not match observation day: {field}')
            count = read_table(lake, reference, columns=[]).num_rows
            if count != reference['rows']:
                raise ValueError(f'Enterprise history count mismatch: {field}')
            days[day] = count
        histories[field] = {'days': len(days), 'rows': sum(days.values())}
    report_evidence = None
    report_meta = manifest.get('installation_usage')
    if report_meta:
        body = lake.get_bytes(report_meta['key'])
        report = json.loads(body)
        detail = report_meta.get('detail_key') or report['detail_key']
        report_evidence = {'fingerprint': fingerprint(body),
                           'detail_rows': read_table(lake, detail, columns=[]).num_rows}
    return {'manifest_fingerprint': fingerprint(encoded(manifest)),
            'dimensions': counts, 'histories': histories, 'installation_usage': report_evidence}
