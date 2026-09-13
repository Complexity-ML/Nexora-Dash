"""Completion marker for a verified local database-and-lake backup archive."""
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile

MARKER = 'backup-complete.json'


def digest(path):
    value=sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            value.update(chunk)
    return value.hexdigest()


def checked_path(root,key):
    path=PurePosixPath(key)
    if not key or path.is_absolute() or '..' in path.parts or str(path) != key or key == MARKER:
        raise ValueError('Invalid archive member')
    candidate=root/key
    if not candidate.resolve().is_relative_to(root.resolve()) or candidate.is_symlink():
        raise ValueError('Archive member escapes its root')
    return candidate


def check_files(root,files):
    if not isinstance(files,dict) or not {'database.dump','snapshot.json'} <= files.keys():
        raise ValueError('Database dump and frozen snapshot metadata are required')
    for key,expected in files.items():
        if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):
            raise ValueError('Invalid archive checksum')
        if digest(checked_path(root,key)) != expected:
            raise ValueError('Backup member checksum mismatch')
    snapshot = json.loads((root/'snapshot.json').read_text())
    required = snapshot.get('required_archive_members')
    if (not isinstance(required, list) or not required
            or any(not isinstance(key, str) for key in required)
            or len(set(required)) != len(required)
            or not {'database.dump', 'snapshot.json'} <= set(required)):
        raise ValueError('Frozen archive member plan is required')
    for key in required:
        checked_path(root, key)
    if not set(required) <= files.keys():
        raise ValueError('Backup omits required archive members')



def sync_members(root, files):
    """Persist copied members and directory entries before publishing completion.

    The archive directory must remain private and unmodified during sealing.
    """
    root = root.resolve()
    directories = {root}
    for key in files:
        path = checked_path(root, key)
        with path.open('rb') as stream:
            os.fsync(stream.fileno())
        parent = path.parent
        while parent != root:
            directories.add(parent)
            parent = parent.parent
    # Persist child entries before their parents.
    for directory in sorted(directories, key=lambda path:len(path.parts), reverse=True):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def seal_archive(root,files):
    root=Path(root)
    check_files(root,files)
    sync_members(root,files)
    manifest={'format_version':1,'files':files}
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=root,delete=False) as stream:
            temporary=Path(stream.name)
            json.dump(manifest,stream,sort_keys=True)
            stream.flush();os.fsync(stream.fileno())
        # Publish once. A failed or interrupted copy must never have a marker.
        os.link(temporary,root/MARKER)
        descriptor=os.open(root,os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return manifest


def verify_archive(root):
    root=Path(root)
    manifest=json.loads((root/MARKER).read_text())
    if type(manifest.get('format_version')) is not int or manifest['format_version'] != 1:
        raise ValueError('Unsupported backup archive')
    check_files(root,manifest['files'])
    return manifest
