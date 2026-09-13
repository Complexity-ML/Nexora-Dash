from functools import lru_cache
from zoneinfo import ZoneInfo
from typing import Annotated
from pydantic import Field, StrictInt, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    business_timezone: str = "Europe/Paris"

    @field_validator('business_timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError('Fuseau IANA invalide') from exc
        return value

    database_url: str = ""
    sam_demo_password: str = ""
    demo_accounts_enabled: bool = False
    demo_tools_enabled: bool = False
    sam_data_source: str = "mock"
    bi_enabled: bool = False
    bi_namespace: str = ""
    collection_enabled: bool = False
    collection_minimum_counts: dict[str, Annotated[StrictInt, Field(ge=0)]] = Field(default_factory=dict)
    collection_minimum_retained_fraction: float = Field(default=0.9, gt=0, le=1)
    collection_source: str = "digimon"
    collection_scope: str = "group"
    digimon_base_url: str = ""
    digimon_timeout: float = 10.0
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "sam-data"
    s3_region: str = "us-east-1"
    spark_master: str = "local[*]"
    underutilization_threshold: float = 0.35
    recovery_buffer_rate: float = 0.10


@lru_cache
def get_settings() -> Settings:
    return Settings()
