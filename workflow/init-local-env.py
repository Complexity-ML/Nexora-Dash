"""Create local Compose secrets without printing them or overwriting existing values."""
import os
from pathlib import Path
import secrets

path = Path(__file__).resolve().parents[1] / '.env'
if path.exists():
    raise SystemExit('Le fichier .env existe déjà ; aucune valeur remplacée.')
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    for key in ('POSTGRES_PASSWORD', 'SAM_DEMO_PASSWORD'):
        output.write(f'{key}={secrets.token_hex(24)}\n')
print('Secrets locaux créés dans .env (permissions 600). Ne pas committer ce fichier.')
