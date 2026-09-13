"""Observed installations and explicitly scoped entitlement quantities.

Metrics are supplied by the source/contract mapping, never inferred from an OS name.
"""
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class SoftwareProduct(BaseModel):
    software_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: Literal['operating_system', 'application', 'service']
    license_pool_id: str | None = None


class SoftwareInstallation(BaseModel):
    installation_id: str = Field(min_length=1)
    software_id: str
    machine_id: str
    version: str | None = None


class SoftwareEntitlement(BaseModel):
    entitlement_id: str = Field(min_length=1)
    software_id: str
    metric: Literal['named_user', 'device', 'concurrent', 'core', 'host', 'unmetered']
    quantity: int | None = Field(default=None, ge=0)
    subsidiary_id: str | None = None
    annual_unit_cost_cents: int | None = Field(default=None, ge=0)
    currency: str = 'EUR'
    synthetic: bool = False

    @model_validator(mode='after')
    def validate_quantity(self):
        if self.metric == 'unmetered' and self.quantity is not None:
            raise ValueError('Unmetered software has no purchased quantity')
        return self
