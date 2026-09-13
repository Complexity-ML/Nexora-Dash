"""Deterministic fictional license pools for the local SAM demonstration."""
from datetime import datetime
import math
import random

VERSION = "sam-demo-v2"
CATALOG = [
    ("flex-cad", "Autodesk Product Design", 800, "underused"),
    ("flex-matlab", "MATLAB", 800, "stable"),
    ("flex-adobe", "Adobe Creative Cloud", 2000, "growth"),
    ("flex-ansys", "Ansys Mechanical", 240, "saturated"),
    ("flex-abaqus", "SIMULIA Abaqus", 350, "capacity-drop"),
    ("flex-solidworks", "SOLIDWORKS", 420, "seasonal"),
    ("flex-catia", "CATIA", 180, "underused"),
    ("flex-creo", "PTC Creo", 260, "growth"),
    ("flex-nx", "Siemens NX", 120, "capacity-rise"),
    ("flex-comsol", "COMSOL Multiphysics", 300, "stable"),
    ("flex-arcgis", "ArcGIS Pro", 600, "seasonal"),
    ("flex-maple", "Maple", 140, "underused"),
]


def snapshot(at: datetime) -> dict:
    day = (at.date() - datetime(2026, 1, 1).date()).days
    pools = []
    for index, (pool, name, base, scenario) in enumerate(CATALOG):
        noise = random.Random(f"{VERSION}:{pool}:{at.date()}").uniform(-.025, .025)
        weekend = .85 if at.weekday() >= 5 else 1
        capacity = base
        if scenario == "underused": rate = .19 + .04 * math.sin(day / 11)
        elif scenario == "stable": rate = .53 + .06 * math.sin(day / 17)
        elif scenario == "growth": rate = min(.98, max(.15, .40 + day * .0018))
        elif scenario == "saturated": rate = .96 + .025 * math.sin(day / 7)
        elif scenario == "capacity-drop":
            capacity = base if day < 210 else int(base * .55)
            rate = (base * .48) / capacity
        elif scenario == "capacity-rise":
            capacity = base if day < 180 else int(base * 1.6)
            rate = (base * .65) / capacity
        else: rate = .58 + .23 * math.sin((day + index * 15) / 35)
        used = max(0, min(capacity, round(capacity * (rate + noise) * weekend)))
        pools.append({"poolKey": pool, "product": {"key": pool.removeprefix("flex-"), "name": name},
            # Explicit fictional configuration; never infer a manager from a product name.
            "licenseManager": "other" if pool in {"flex-adobe", "flex-catia", "flex-arcgis"} else "flexnet",
            "entitlement": capacity, "consumed": used, "demoScenario": scenario})
    from app.connectors.demo_inventory import inventory
    return {"inventory": inventory(at), "capturedAt": at.isoformat(), "provider": "digimon-mock", "demoVersion": VERSION, "pools": pools}
