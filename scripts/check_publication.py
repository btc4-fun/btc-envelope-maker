"""Check the Git index without ever printing matched secret values."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {'.venv', 'venv', 'out', 'secrets', '__pycache__', 'backups', 'data', 'state'}
FORBIDDEN_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.pdf', '.pem', '.key', '.kdbx', '.csv'}
PRIVATE_KEY = re.compile(rb'-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----')


def check_index():
    names = subprocess.check_output(['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'], cwd=ROOT).decode().split('\0')
    failures = []
    needles = []
    secret_file = os.environ.get('PUBLICATION_SECRET_FILE')
    if secret_file:
        needles = [value for value in Path(secret_file).read_bytes().splitlines() if len(value) >= 4]
    for name in filter(None, names):
        path = Path(name)
        if (set(path.parts) & FORBIDDEN_PARTS or path.suffix.lower() in FORBIDDEN_SUFFIXES
                or re.search(r'\.(?:db|sqlite|sqlite3)-(?:wal|shm|journal)$', path.name, re.IGNORECASE)
                or path.name.lower() in {'config.toml', 'todo', 'todo.txt', 'privatekey.png', 'publickey.png'} or path.suffix == '.env'
                or (path.name.startswith('.env') and path.name != '.env.example')):
            failures.append((name, 'forbidden publication path'))
            continue
        data = subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT)
        if PRIVATE_KEY.search(data):
            failures.append((name, 'private-key material'))
        if any(value in data for value in needles):
            failures.append((name, 'operator credential match'))
        for match in re.finditer(rb'(?:postgres(?:ql)?://)([^:@\s\x22\x27]+):([^*@\s\x22\x27]+)@', data, flags=re.IGNORECASE):
            if not (match.group(1) == b'user' and match.group(2) in {b'password', b'pass'}):
                failures.append((name, 'credential-bearing database URI'))
    for name, reason in failures:
        print(f'BLOCKED {name}: {reason}')
    print(f'Publication path/credential guard: {len(list(filter(None, names)))} staged files; {len(failures)} violations')
    return not failures


if __name__ == '__main__':
    raise SystemExit(0 if check_index() else 1)
