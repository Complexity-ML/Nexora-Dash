"""Inventory entities and observed usage; independent of license entitlements."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from app.models.software_inventory import SoftwareProduct, SoftwareInstallation, SoftwareEntitlement


class Subsidiary(BaseModel):
    code: str | None = None
    subsidiary_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class Site(BaseModel):
    site_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    subsidiary_id: str | None = None
    region: str | None = None
    city: str | None = None
    country: str | None = None


class Machine(BaseModel):
    machine_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal['physical', 'virtual']
    operating_system: str
    form_factor: Literal['desktop', 'laptop', 'server', 'virtual'] | None = None
    asset_type: Literal['workstation', 'server'] | None = None
    environment: Literal['production', 'test', 'development'] | None = None
    cpu_cores: int | None = Field(default=None, gt=0)
    memory_gb: int | None = Field(default=None, gt=0)
    services: list[str] = Field(default_factory=list)
    applications: list[str] = Field(default_factory=list)
    digimon_reported_source: Literal['SCCM', 'Flexera One'] | None = None
    host_id: str | None = None
    site_id: str | None = None


class InventoryUser(BaseModel):
    user_id: str = Field(min_length=1)
    display_name: str
    email: str | None = None
    employment_type: Literal['employee', 'contractor'] | None = None
    status: Literal['active', 'inactive'] | None = None
    department: str | None = None
    site_id: str | None = None


class SoftwareObservation(BaseModel):
    machine_id: str
    user_id: str | None = None
    license_pool_id: str
    used: bool
    software_version: str | None = None
    execution_minutes: int | None = Field(default=None, ge=0, le=1440)
    execution_count: int | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def validate_usage(self):
        if not self.used and ((self.execution_minutes or 0) > 0 or (self.execution_count or 0) > 0):
            raise ValueError('Execution metrics require observed usage')
        return self


class InventorySnapshot(BaseModel):
    captured_at: datetime
    source: str
    subsidiaries: list[Subsidiary] = Field(default_factory=list)
    sites: list[Site] = Field(default_factory=list)
    machines: list[Machine] = Field(default_factory=list)
    users: list[InventoryUser] = Field(default_factory=list)
    products: list[SoftwareProduct] = Field(default_factory=list)
    installations: list[SoftwareInstallation] = Field(default_factory=list)
    entitlements: list[SoftwareEntitlement] = Field(default_factory=list)
    observations: list[SoftwareObservation] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_links(self):
        subsidiary_ids = {s.subsidiary_id for s in self.subsidiaries}
        if len(subsidiary_ids) != len(self.subsidiaries):
            raise ValueError('Duplicate subsidiary identifiers')
        if any(s.subsidiary_id is not None and s.subsidiary_id not in subsidiary_ids for s in self.sites):
            raise ValueError('Unknown subsidiary in inventory')
        site_ids = {s.site_id for s in self.sites}
        if len(site_ids) != len(self.sites):
            raise ValueError('Duplicate site identifiers')
        if any(item.site_id and item.site_id not in site_ids for item in [*self.machines, *self.users]):
            raise ValueError('Unknown site in inventory')
        machine_ids = {m.machine_id for m in self.machines}
        user_ids = {u.user_id for u in self.users}
        if len(machine_ids) != len(self.machines) or len(user_ids) != len(self.users):
            raise ValueError('Duplicate inventory identifiers')
        if any(m.host_id == m.machine_id or (m.host_id and m.host_id not in machine_ids) for m in self.machines):
            raise ValueError('Unknown or self-referencing host')
        hosts = {m.machine_id:m.host_id for m in self.machines}
        for machine_id in hosts:
            seen = set()
            current = machine_id
            while current is not None:
                if current in seen:
                    raise ValueError('Cyclic host relationships')
                seen.add(current)
                current = hosts[current]
        products = {p.software_id for p in self.products}
        if len(products) != len(self.products):
            raise ValueError('Duplicate software product identifiers')
        for name in ('installations', 'entitlements'):
            items = getattr(self, name)
            key = 'installation_id' if name == 'installations' else 'entitlement_id'
            if len({getattr(item, key) for item in items}) != len(items):
                raise ValueError(f'Duplicate {name} identifiers')
            if any(item.software_id not in products for item in items):
                raise ValueError(f'Unknown software product in {name}')
        installation_pairs = set()
        for installation in self.installations:
            if installation.machine_id not in machine_ids:
                raise ValueError('Unknown machine in installation')
            pair = (installation.machine_id, installation.software_id)
            if pair in installation_pairs:
                raise ValueError('Duplicate software installation')
            installation_pairs.add(pair)
        for entitlement in self.entitlements:
            if entitlement.subsidiary_id is not None and entitlement.subsidiary_id not in subsidiary_ids:
                raise ValueError('Unknown subsidiary in entitlement')
        pool_products = {p.license_pool_id:p.software_id for p in self.products if p.license_pool_id}
        if len(pool_products) != sum(bool(p.license_pool_id) for p in self.products):
            raise ValueError('Ambiguous product for license pool')
        links = set()
        for o in self.observations:
            if o.machine_id not in machine_ids or (o.user_id is not None and o.user_id not in user_ids):
                raise ValueError('Unknown machine or user in observation')
            if self.products and (o.machine_id, pool_products.get(o.license_pool_id)) not in installation_pairs:
                raise ValueError('Usage has no matching software installation')
            key = (o.machine_id, o.user_id, o.license_pool_id)
            if key in links:
                raise ValueError('Duplicate software observation')
            links.add(key)
        return self


def map_inventory_payload(payload: dict) -> InventorySnapshot | None:
    # Absence means unavailable, never synthesize inventory for a real source.
    if 'inventory' not in payload:
        return None
    value = InventorySnapshot.model_validate({
        **payload['inventory'], 'captured_at': payload['capturedAt'],
        'source': payload.get('provider', 'digimon'),
    })
    pools = {str(p['poolKey']) for p in payload.get('pools', [])}
    if any(o.license_pool_id not in pools for o in value.observations):
        raise ValueError('Unknown license pool in inventory observation')
    return value
