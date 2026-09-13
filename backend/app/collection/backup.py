"""Plan the files required to restore pinned Delta versions; no deletion or copy."""
from app.storage.delta_tables import DeltaReference


def delta_backup_files(lake, references):
    files = set()
    versions = {}
    root = lake.delta.root.rstrip('/') + '/'
    for item in references:
        ref = DeltaReference(item['path'], item['version'])
        table = lake.delta.open(ref)
        versions[ref.path] = max(versions.get(ref.path, -1), ref.version)
        for uri in table.file_uris():
            if not uri.startswith(root):
                raise ValueError('Delta file is outside the lake root')
            key = uri[len(root):]
            if '..' in key.split('/') or not key.startswith(ref.path.rstrip('/') + '/'):
                raise ValueError('Delta file is outside its table')
            files.add(key)
    for path, maximum in versions.items():
        prefix = path.rstrip('/') + '/_delta_log/'
        logs = lake.list_keys(prefix)
        found = False
        for key in logs:
            relative = key[len(prefix):] if key.startswith(prefix) else ''
            if '..' in relative.split('/'):
                raise ValueError('Invalid Delta log key')
            # Avoid a _last_checkpoint pointer to a version not in this backup.
            if relative.startswith('_sidecars/'):
                files.add(key)
            elif len(relative) > 20 and relative[:20].isdigit() and int(relative[:20]) <= maximum:
                files.add(key)
                found = True
        if not found:
            raise ValueError('No Delta log available for pinned table')
    return sorted(files)
