"""DIGIMON boundary. Only ``map_digimon_payload`` knows its provisional DTO."""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from app.models.canonical import LicenseStock, LicenseUsage, UsageSnapshot


class DigimonConnector(ABC):
    @abstractmethod
    async def get_raw_snapshot(self) -> dict[str, Any]: ...

    async def get_current_usage(self) -> list[LicenseUsage]:
        return map_digimon_payload(await self.get_raw_snapshot()).usage

    async def get_license_stock(self) -> list[LicenseStock]:
        return map_digimon_payload(await self.get_raw_snapshot()).stock

    async def get_license_details(self) -> list[dict[str, Any]]:
        return list((await self.get_raw_snapshot()).get("pools", []))


class HttpDigimonConnector(DigimonConnector):
    """HTTP adapter. Replace the placeholder path here when DIGIMON is known."""
    def __init__(self, base_url: str, timeout: float = 10):
        if not base_url:
            raise ValueError("DIGIMON_BASE_URL is required in digimon mode")
        self.base_url, self.timeout = base_url.rstrip("/"), timeout

    async def get_raw_snapshot(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # TODO(DIGIMON contract): configure the real route/auth server-side.
            response = await client.get(f"{self.base_url}/api/licenses/snapshot")
            response.raise_for_status()
            return response.json()


class MockDigimonConnector(DigimonConnector):
    def __init__(self, at: datetime | None = None):
        self.at = at

    async def get_raw_snapshot(self) -> dict[str, Any]:
        from app.connectors.demo import snapshot
        return snapshot(self.at or datetime.now(timezone.utc))



def _whole_quantity(value):
    """Accept integral source quantities without truncation or boolean coercion."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError('Expected a non-negative integral pool quantity')
    if isinstance(value, float) and not value.is_integer():
        raise ValueError('Expected a non-negative integral pool quantity')
    try:
        quantity = int(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError('Expected a non-negative integral pool quantity') from exc
    if quantity < 0:
        raise ValueError('Expected a non-negative integral pool quantity')
    return quantity


def _required_field(record, field):
    if not isinstance(record, dict) or field not in record:
        raise ValueError(f'Missing required source field: {field}')
    return record[field]


def _required_text(record, field):
    value = _required_field(record, field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Expected non-empty source text: {field}')
    return value


def map_digimon_payload(payload: dict[str, Any]) -> UsageSnapshot:
    """Map the documented mock/intermediate DIGIMON DTO to canonical SAM."""
    timestamp = datetime.fromisoformat(_required_text(payload, "capturedAt").replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Source capturedAt must include a timezone offset")
    usage, stock = [], []
    pool_ids = set()
    pools = payload.get('pools', [])
    if not isinstance(pools, list):
        raise ValueError('Source pools must be a list')
    for raw in pools:
        pool_id = _required_text(raw, 'poolKey')
        if not pool_id.strip() or pool_id in pool_ids:
            raise ValueError('Missing or duplicate license pool identifier')
        pool_ids.add(pool_id)
        capacity, used = _whole_quantity(_required_field(raw, "entitlement")), _whole_quantity(_required_field(raw, "consumed"))
        product = _required_field(raw, "product")
        common = dict(license_pool_id=pool_id, software_id=_required_text(product, "key"),
                      software_name=_required_text(product, "name"), timestamp=timestamp,
                      capacity=capacity, used=used, available=max(0, capacity-used),
                      source=str(payload.get("provider", "digimon")))
        usage.append(LicenseUsage(**common))
        stock.append(LicenseStock(**common, license_manager=raw.get("licenseManager")))
    return UsageSnapshot(snapshot_id=str(uuid4()), timestamp=timestamp,
                         source=str(payload.get("provider", "digimon")), usage=usage, stock=stock)
