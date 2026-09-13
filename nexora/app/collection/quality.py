"""Publication anomaly gate; baseline retention is not source completeness."""
from collections import Counter
from typing import Annotated
from pydantic import BaseModel, Field, StrictInt
from app.storage.table_reader import read_table


class CoveragePolicy(BaseModel):
    minimum_retained_fraction: float = Field(default=0.9, gt=0, le=1)
    minimum_counts: dict[str, Annotated[StrictInt, Field(ge=0)]] = Field(default_factory=dict)

    def identity(self):
        # Preserve pre-existing transformation identities when no floors are set.
        return self.model_dump(exclude={'minimum_counts'} if not self.minimum_counts else set())


class CoverageRejected(ValueError):
    pass


def profile(rows):
    counts = {}
    sites = {r['site_id']: r.get('subsidiary_id') for r in rows('sites')}
    for entity in ('machines', 'users'):
        groups = Counter()
        for row in rows(entity):
            groups[sites.get(row.get('site_id')) or '__unassigned__'] += 1
        counts[entity] = sum(groups.values())
        counts.update({f'{entity}/subsidiary/{key}': value for key, value in groups.items()})
    counts['sites'] = len(sites)
    products = Counter(row['software_id'] for row in rows('installations'))
    counts['installations'] = sum(products.values())
    counts.update({f'installations/product/{key}': value for key, value in products.items()})
    rights = Counter()
    for row in rows('entitlements'):
        if row.get('quantity') is not None or row['metric'] == 'unmetered':
            rights[f"{row['software_id']}/{row.get('subsidiary_id') or '__group__'}/{row['metric']}"] += 1
    counts.update({f'entitlements/{key}': value for key, value in rights.items()})
    return counts


def snapshot_profile(snapshot):
    if snapshot is None:
        return {}
    return profile(lambda name: (item.model_dump() for item in getattr(snapshot, name)))


def enterprise_profile(lake, manifest):
    columns = {'sites': ['site_id', 'subsidiary_id'], 'machines': ['site_id'],
               'users': ['site_id'], 'installations': ['software_id'],
               'entitlements': ['software_id', 'subsidiary_id', 'metric', 'quantity']}
    def rows(name):
        ref = manifest['dimensions'].get(name)
        if ref is None:
            return iter(())
        table = read_table(lake, ref, columns=columns[name])
        return (row for batch in table.to_batches(max_chunksize=8192) for row in batch.to_pylist())
    return profile(rows)


def compare_coverage(previous, current, policy):
    changes = [{'dimension': key, 'previous': value, 'received': current.get(key, 0)}
               for key, value in sorted(previous.items())
               if value > 0 and current.get(key, 0) < value * policy.minimum_retained_fraction]
    shortfalls = [{'dimension': key, 'minimum': value, 'received': current.get(key, 0)}
                  for key, value in sorted(policy.minimum_counts.items()) if current.get(key, 0) < value]
    return {'accepted': not changes and not shortfalls, 'shortfalls': shortfalls, 'policy': policy.model_dump(),
            'baseline_available': bool(previous), 'decreases': changes}
