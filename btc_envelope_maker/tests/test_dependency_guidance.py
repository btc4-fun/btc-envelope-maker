"""Missing-dependency recovery must retain the reviewed offline lock contract."""
import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1]


def assert_locked_guidance(message, *, database=False):
    assert 'DEPENDENCIES.md' in message
    assert 'requirements-runtime.txt' in message
    assert '--require-hashes' in message
    if database:
        assert 'requirements-db.txt' in message
    for stale in ('pip install', 'requirements.txt'):
        assert stale not in message


@pytest.mark.parametrize('missing', ['runtime', 'tzdata', 'postgres'])
def test_missing_dependency_uses_locked_recovery(tmp_path, missing):
    if missing == 'runtime':
        # No site packages: fail at imports, before configuration or entropy.
        args = ['-I', '-S', str(SOURCE / 'btc_envelope_maker.py'), '--help']
    elif missing == 'tzdata':
        # Force the real timezone-error path regardless of host tz database.
        args = ['-I', '-c', '''import sys, zoneinfo
sys.path.insert(0, sys.argv[1])
import btc_envelope_maker as gen
def missing_zone(name):
    raise zoneinfo.ZoneInfoNotFoundError(name)
zoneinfo.ZoneInfo = missing_zone
gen.now_local({'timezone': 'UTC'})
''', str(SOURCE)]
    else:
        # Both supported drivers absent; stop before any database connection.
        # -I removes the sibling module path; explicitly add only public source.
        args = ['-I', '-S', '-c', '''import sys
sys.path.insert(0, sys.argv.pop(1))
import btc_db
raise SystemExit(btc_db.main(sys.argv[1:]))
''', str(SOURCE), 'list', '--db', 'postgresql://invalid.example/synthetic']
    result = subprocess.run([sys.executable, '-B', *args], cwd=tmp_path,
                            env={'TMPDIR': os.environ['TMPDIR'], 'PYTHONDONTWRITEBYTECODE': '1'},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stderr
    assert result.stdout == ''
    assert 'Traceback' not in result.stderr
    assert not list(tmp_path.iterdir())
    assert_locked_guidance(result.stderr, database=missing == 'postgres')


def test_database_module_help_uses_locked_recovery():
    doc = ast.get_docstring(ast.parse((SOURCE / 'btc_db.py').read_text()))
    assert_locked_guidance(doc, database=True)
