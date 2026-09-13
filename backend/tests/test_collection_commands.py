"""Documented module entrypoints must work without an implicit PYTHONPATH."""
import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.parametrize('module', ['import_collection_history', 'recover_collections', 'collection_status'])
def test_collection_command_help_from_backend_root(module):
    env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    result = subprocess.run([sys.executable, '-m', 'scripts.' + module, '--help'],
                            cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout
