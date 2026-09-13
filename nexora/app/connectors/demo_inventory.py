"""Small deterministic inventory sample; it does not represent the whole licensed fleet."""
from datetime import datetime
from app.connectors.demo import CATALOG


def inventory(at: datetime) -> dict:
    subsidiaries = [
        {'subsidiary_id': 'demo-subsidiary-1', 'name': 'Filiale démo Alpha'},
        {'subsidiary_id': 'demo-subsidiary-2', 'name': 'Filiale démo Beta'},
    ]
    sites = [
        {'site_id': 'demo-site-1', 'name': 'Site démo Paris', 'city': 'Paris',
         'region': 'Île-de-France', 'country': 'France', 'subsidiary_id': 'demo-subsidiary-1'},
        {'site_id': 'demo-site-2', 'name': 'Site démo Toulouse', 'city': 'Toulouse',
         'region': 'Occitanie', 'country': 'France', 'subsidiary_id': 'demo-subsidiary-2'},
        {'site_id': 'demo-site-3', 'name': 'Site démo Montréal', 'city': 'Montréal',
         'region': 'Québec', 'country': 'Canada', 'subsidiary_id': 'demo-subsidiary-2'},
    ]
    users = [{'user_id':f'demo-user-{i:03}', 'display_name':f'Utilisateur démo {i:03}',
              'department':['Ingénierie','Études','Support'][i % 3], 'site_id':f'demo-site-{i%3+1}'} for i in range(1, 61)]
    machines = []
    observations = []
    day = at.date().toordinal()
    for i in range(1, 121):
        vm = i > 80
        machine_id = f'demo-machine-{i:03}'
        machines.append({'machine_id':machine_id, 'name':f'DEMO-{ "VM" if vm else "PC" }-{i:03}',
            'kind':'virtual' if vm else 'physical', 'site_id':f'demo-site-{((i-81)//4+1 if vm else i)%3+1}',
            'operating_system':'Red Hat Enterprise Linux' if i % 3 == 0 else 'Windows',
            'host_id':f'demo-machine-{(i-81)//4+1:03}' if vm else None})
        for slot in range(2):
            observations.append({'machine_id':machine_id,'user_id':f'demo-user-{(i-1)%60+1:03}',
                'license_pool_id':CATALOG[(i+slot)%len(CATALOG)][0],
                'used':(i+slot+day)%5 != 0})
    return {'subsidiaries':subsidiaries,'sites':sites,'machines':machines,'users':users,'observations':observations}
