"""Deterministic synthetic enterprise; counts are scenario assumptions, not DIGIMON facts."""
from datetime import datetime
from app.connectors.demo import CATALOG

SUBSIDIARIES = [
    ('SAE', 'Safran Aircraft Engines'),
    ('SED', 'Safran Electronics & Defense'),
    ('SHE', 'Safran Helicopter Engines'),
    ('SLS', 'Safran Landing Systems'),
    ('SAB', 'Safran Aero Boosters'),
    ('SNA', 'Safran Nacelles'),
    ('SST', 'Safran Seats'),
    ('STS', 'Safran Transmission Systems'),
    ('SAO', 'Safran Aerosystems'),
    ('SCA', 'Safran Cabin'),
    ('SAFRAN GROUP', 'Safran Group'),
    ('SAFRAN SIÈGE', 'Safran Siège'),
]
EMPLOYEES = 110_000
CONTRACTORS = 16_500
WORKSTATIONS = 100_000
PHYSICAL_SERVERS = 2_000
VIRTUAL_SERVERS = 20_000
GEOGRAPHY = [
    ('France', 'Île-de-France', 'Paris'), ('France', 'Occitanie', 'Toulouse'),
    ('Canada', 'Québec', 'Montréal'), ('Allemagne', 'Bavière', 'Munich'),
    ('Espagne', 'Madrid', 'Madrid'), ('Royaume-Uni', 'Angleterre', 'Bristol'),
    ('États-Unis', 'Texas', 'Dallas'), ('Maroc', 'Casablanca-Settat', 'Casablanca'),
]
DEPARTMENTS = ['Ingénierie', 'Production', 'Finance', 'Achats', 'Ressources humaines', 'Informatique', 'Qualité', 'Logistique']


# Scenario weights only: these are not actual subsidiary headcounts.
SUBSIDIARY_WEIGHTS = [24,18,9,12,5,7,6,3,6,6,2,2]
SITE_COUNTS = [34,26,18,22,10,14,16,6,14,14,3,3]


def enterprise_site(index: int, servers: bool = False) -> int:
    weights = [12,18,10,12,4,5,4,4,6,5,12,8] if servers else SUBSIDIARY_WEIGHTS
    bucket = ((index * 2654435761) & 0xffffffff) % sum(weights)
    subsidiary = 1
    for weight in weights:
        if bucket < weight:
            break
        bucket -= weight
        subsidiary += 1
    count = SITE_COUNTS[subsidiary-1]
    bucket = ((index * 2246822519) & 0xffffffff) % (count * (count+1) // 2)
    location = 0
    for weight in range(count, 0, -1):
        if bucket < weight:
            break
        bucket -= weight
        location += 1
    return sum(SITE_COUNTS[:subsidiary-1]) + location + 1


def enterprise_inventory(at: datetime, employees: int = EMPLOYEES,
                         workstations: int = WORKSTATIONS,
                         physical_servers: int = PHYSICAL_SERVERS,
                         virtual_servers: int = VIRTUAL_SERVERS,
                         contractors: int = 0) -> dict:
    if not (employees >= workstations > 0 and physical_servers > 0 and virtual_servers >= 0 and contractors >= 0):
        raise ValueError('Invalid enterprise scenario sizes')
    def workstation_for(person):
        return (person-1)%workstations+1 if person<=employees else workstations+person-employees

    subsidiaries = [{'subsidiary_id':f'ent-sub-{i:02}', 'name':name,'code':code} for i,(code,name) in enumerate(SUBSIDIARIES,1)]
    sites = []
    for subsidiary, count in enumerate(SITE_COUNTS, 1):
        for local in range(count):
            i = len(sites)+1
            country,region,city = GEOGRAPHY[(i-1)%len(GEOGRAPHY)] if subsidiary < 11 else GEOGRAPHY[0]
            sites.append({'site_id':f'ent-site-{i:03}','name':f'{city} · Site fictif {i:02}',
                          'country':country,'region':region,'city':city,'subsidiary_id':f'ent-sub-{subsidiary:02}'})
    users = []
    for i in range(1,employees+contractors+1):
        users.append({'user_id':f'ent-user-{i:06}','display_name':f'Salarié démo {i:06}' if i<=employees else f'Prestataire démo {i-employees:06}',
                      'email':f'employee-{i:06}@enterprise.example.invalid' if i<=employees else f'contractor-{i-employees:06}@enterprise.example.invalid',
                      'department':(['Finance','Achats','Ressources humaines','Informatique'][i%4] if enterprise_site(workstation_for(i))>sum(SITE_COUNTS[:10]) else ['Ingénierie','Production','Production','Qualité','Logistique'][i%5]),
                      'employment_type':'employee' if i<=employees else 'contractor',
                      'status':'inactive' if i%101 == 0 else 'active',
                      'site_id':f'ent-site-{enterprise_site(workstation_for(i)):03}'})
    machines = []
    observations = []
    day = at.date().toordinal()
    for i in range(1,workstations+contractors+1):
        linux = i<=workstations and i%20 == 0
        machines.append({'machine_id':f'ent-pc-{i:06}','name':f'WS-{i:06}',
                         'form_factor':'desktop' if i<=workstations and (linux or i%3==0) else 'laptop',
                         'kind':'physical','asset_type':'workstation','environment':'production',
                         'operating_system':'Red Hat Enterprise Linux 9' if linux else 'Windows 11 Enterprise',
                         'cpu_cores':8 if i%4 else 16,'memory_gb':16 if i%4 else 32,
                         'site_id':f'ent-site-{enterprise_site(i):03}',
                         'services':[], 'applications':['Firefox','LibreOffice'] if linux else ['Microsoft 365 Apps','Microsoft Teams','Microsoft Edge','Adobe Acrobat Reader']})
    for i in range(1,physical_servers+1):
        machines.append({'machine_id':f'ent-host-{i:05}','name':f'HV-{i:05}',
                         'form_factor':'server','kind':'physical','asset_type':'server','environment':'production',
                         'operating_system':'Red Hat Enterprise Linux 9',
                         'cpu_cores':64,'memory_gb':512,'site_id':f'ent-site-{enterprise_site(i, servers=True):03}',
                         'services':['KVM'],'applications':['Cockpit','OpenSSH']})
    for i in range(1,virtual_servers+1):
        host = (i-1)%physical_servers+1
        windows = i%3 == 0
        machines.append({'machine_id':f'ent-vm-{i:06}','name':f'VM-{i:06}',
                         'form_factor':'virtual','kind':'virtual','asset_type':'server',
                         'environment':['production','production','test','development'][i%4],
                         'operating_system':'Windows Server 2022' if windows else 'Red Hat Enterprise Linux 9',
                         'cpu_cores':[2,4,8,16][i%4],'memory_gb':[8,16,32,64][i%4],
                         'host_id':f'ent-host-{host:05}','site_id':f'ent-site-{enterprise_site(host, servers=True):03}',
                         'services':['IIS'] if windows else ['Nginx' if i%2 else 'PostgreSQL'],
                         'applications':['Microsoft Defender','.NET Runtime'] if windows else ['OpenSSH','rsyslog']})
    for machine in machines:
        machine['digimon_reported_source'] = 'SCCM' if machine['operating_system'].startswith('Windows') else 'Flexera One'
    for i in range(1,employees+contractors+1):
        workstation = machines[workstation_for(i)-1]
        available = [c for c in CATALOG if c[0] in ('flex-matlab','flex-abaqus','flex-ansys','flex-comsol','flex-maple')] if workstation['operating_system'].startswith('Red Hat') else CATALOG
        # Several employees can share a workstation; no fabricated personal identity.
        for slot in range(2):
            product = available[(i+slot)%len(available)]
            if product[1] not in workstation['applications']:
                workstation['applications'].append(product[1])
            observations.append({'machine_id':f'ent-pc-{workstation_for(i):06}',
                                 'user_id':f'ent-user-{i:06}',
                                 'license_pool_id':product[0],
                                 'software_version':f'{2023+i%3}.{slot+1}',
                                 'used':i%101 != 0 and (i+slot+day)%7 < 4})
    return {'subsidiaries':subsidiaries,'sites':sites,'machines':machines,
            'users':users,'observations':observations}


def daily_observation(row: dict, at: datetime) -> None:
    """Synthetic execution measurements, independent of concurrent seat consumption."""
    i = int(row['user_id'].rsplit('-', 1)[1])
    used = i % 101 != 0 and at.weekday() < 5 and (i + at.date().toordinal()) % 7 < 4
    row['used'] = used
    # Missing telemetry remains unknown, never converted into zero usage minutes.
    measured = i % 5 != 0
    row['execution_minutes'] = (15 + (i + at.date().toordinal()) % 420 if used else 0) if measured else None
    row['execution_count'] = (1 + i % 6 if used else 0) if measured else None
