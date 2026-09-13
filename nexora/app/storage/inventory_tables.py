"""Explicit Arrow types for nullable inventory fields, including empty dimensions."""
from datetime import date, datetime
from types import UnionType
from typing import Literal, Union, get_args, get_origin
import pyarrow as pa
from app.models.inventory import (Subsidiary, Site, Machine, InventoryUser, SoftwareObservation)
from app.models.software_inventory import SoftwareProduct, SoftwareInstallation, SoftwareEntitlement

MODELS = dict(subsidiaries=Subsidiary, sites=Site, machines=Machine, users=InventoryUser,
              observations=SoftwareObservation, products=SoftwareProduct,
              installations=SoftwareInstallation, entitlements=SoftwareEntitlement)


def arrow_type(annotation):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        members = [a for a in args if a is not type(None)]
        if len(members) != 1:
            raise TypeError(f'Ambiguous inventory type: {annotation}')
        return arrow_type(members[0])
    if origin is Literal:
        return arrow_type(type(args[0]))
    if origin is list:
        return pa.list_(arrow_type(args[0]))
    return {str: pa.string(), int: pa.int64(), bool: pa.bool_(), float: pa.float64(),
            date: pa.date32(), datetime: pa.timestamp('us', tz='UTC')}[annotation]


def inventory_table(name, rows):
    schema = pa.schema([pa.field(k, arrow_type(v.annotation)) for k, v in MODELS[name].model_fields.items()])
    if isinstance(rows, pa.Table):
        if set(rows.column_names) - set(schema.names):
            raise ValueError(f'Unexpected columns in {name}')
        columns = [rows[f.name].cast(f.type) if f.name in rows.column_names
                   else pa.nulls(rows.num_rows, type=f.type) for f in schema]
        return pa.Table.from_arrays(columns, schema=schema)
    return pa.Table.from_pylist(rows, schema=schema)
