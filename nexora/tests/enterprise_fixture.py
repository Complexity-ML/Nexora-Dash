"""Contract-test input from the enterprise lake generator; never loaded by Dash."""
from app.connectors.demo import snapshot as pool_snapshot
from app.connectors.enterprise_inventory import enterprise_inventory


def inventory(at):
    return enterprise_inventory(at, employees=110, workstations=100,
                                physical_servers=2, virtual_servers=20, contractors=16)


def snapshot(at):
    return {**pool_snapshot(at), 'inventory': inventory(at)}
