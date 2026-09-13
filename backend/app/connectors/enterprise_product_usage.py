"""Synthetic DIGIMON product activity, not entitlement consumption or agent collection."""
from datetime import date
from hashlib import sha256
import pyarrow as pa

VERSION = 'product-usage-v1'


def seed(value):
    return int.from_bytes(sha256(value.encode()).digest()[:4], 'big')


class ProductUsageScenario:
    def __init__(self, machines, products, installations):
        self.machines = {m['machine_id']:m for m in machines}
        self.products = {p['software_id']:p for p in products}
        if len(self.machines) != len(machines) or len(self.products) != len(products):
            raise ValueError('Duplicate entity identifier')
        self.rows = sorted((i for i in installations if not self.products[i['software_id']].get('license_pool_id')), key=lambda i:i['installation_id'])
        if len({i['installation_id'] for i in self.rows}) != len(self.rows):
            raise ValueError('Duplicate installation identifier')
        if len({(i['machine_id'],i['software_id']) for i in self.rows}) != len(self.rows):
            raise ValueError('Duplicate machine/product installation')
        self.machine_seeds = {mid:seed(mid) for mid in self.machines}
        self.installation_seeds = [seed(i['installation_id']) for i in self.rows]
        self.columns = {k:pa.array([i[k] for i in self.rows],type=pa.string()) for k in ('installation_id','machine_id','software_id')}
        kinds = {'operating_system':'system_uptime','service':'service_runtime','application':'application_execution'}
        self.columns['measurement'] = pa.array([kinds[self.products[i['software_id']]['category']] for i in self.rows],type=pa.string())
        for i in self.rows:
            if i['machine_id'] not in self.machines:
                raise ValueError('Installation refers to unknown machine')
        for machine in machines:
            if machine.get('host_id') and machine['host_id'] not in self.machines:
                raise ValueError('Virtual machine refers to unknown host')

    def table(self, day: date):
        ordinal = day.toordinal()
        uptime = {}
        visiting = set()
        def machine_uptime(mid):
            if mid in uptime:
                return uptime[mid]
            if mid in visiting:
                raise ValueError('Host cycle')
            visiting.add(mid)
            machine = self.machines[mid]
            value = self.machine_seeds[mid]
            server = machine.get('asset_type') == 'server'
            active = value % 251 != 0 and (server or day.weekday() < 5 or value % 12 == 0)
            minutes = (1440 if server else 360 + (value + ordinal) % 241) if active else 0
            if machine.get('host_id'):
                minutes = min(minutes, machine_uptime(machine['host_id']))
            uptime[mid] = minutes
            visiting.remove(mid)
            return minutes
        for mid in self.machines:
            machine_uptime(mid)
        observed, used, minutes = [], [], []
        for item, value in zip(self.rows, self.installation_seeds):
            category = self.products[item['software_id']]['category']
            present = not (value % 997 == 0 and ordinal % 17 == 0)
            machine_minutes = uptime[item['machine_id']]
            active = machine_minutes > 0
            if category == 'application':
                active = active and value % 41 != 0 and (value + ordinal * 13) % 7 < 4
            elif category == 'service':
                active = active and value % 83 != 0
            duration = machine_minutes if category == 'operating_system' else min(machine_minutes, 10 + (value + ordinal) % 360)
            observed.append(present)
            used.append(active if present else None)
            minutes.append((duration if active else 0) if present else None)
        return pa.table({**self.columns,
            'observation_date':pa.array([day]*len(self.rows),type=pa.date32()),
            'observed':pa.array(observed,type=pa.bool_()),
            'used':pa.array(used,type=pa.bool_()),
            'duration_minutes':pa.array(minutes,type=pa.int16())})
