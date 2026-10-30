"""Only public source is copied; real generation stops BEFORE entropy."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('include_db', [False, True])
def test_generator_only_without_database_reaches_entropy_guard(tmp_path, include_db):
    standalone = tmp_path / 'standalone'
    standalone.mkdir()
    # No site or original configuration is copied; optionally retain btc_db.
    shutil.copyfile(SOURCE / 'btc_envelope_maker.py', standalone / 'btc_envelope_maker.py')
    if include_db:
        shutil.copyfile(SOURCE / 'btc_db.py', standalone / 'btc_db.py')
    config = tmp_path / 'synthetic.toml'
    config.write_text('timezone = "UTC"\n')
    worker = tmp_path / 'worker.py'
    worker.write_text('''import sys
sys.path.insert(0, sys.argv.pop(1))
import btc_envelope_maker as gen
def stop(*args, **kwargs):
    print("ENTROPY_GUARD_REACHED")
    raise SystemExit(73)
gen.Bip39MnemonicGenerator.FromWordsNumber = stop
gen.main()
''')
    result = subprocess.run([sys.executable, '-B', str(worker), str(standalone),
                             '--config', str(config), '--count', '1', '--allow-online',
                             '--acknowledge-offline', '--out', str(tmp_path / 'out')],
                            cwd=tmp_path, env={'TMPDIR': os.environ['TMPDIR'],
                                              'PYTHONDONTWRITEBYTECODE': '1'},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 73, result.stderr
    assert 'ENTROPY_GUARD_REACHED' in result.stdout
    assert not (tmp_path / 'out').exists()


def test_database_helper_imports_without_site_or_third_party_packages(tmp_path):
    for name in ('btc_db.py', 'address_validation.py'):
        source = SOURCE / name
        if source.exists():
            shutil.copyfile(source, tmp_path / name)
    result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c',
                             'import sys; sys.path.insert(0, sys.argv[1]); import btc_db; '
                             'assert not any(n.startswith(("bitcoin4funsite", "bech32")) for n in sys.modules)',
                             str(tmp_path)], cwd=tmp_path, env={},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    # Exercise SQLite import using only stdlib, no site or installed packages.
    ledger = tmp_path / 'synthetic.csv'
    ledger.write_text('serial,address\nSYNTHETIC,bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4\n')
    database = tmp_path / 'synthetic.sqlite3'
    result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c',
                             'import sys; sys.path.insert(0, sys.argv.pop(1)); import btc_db; '
                             'raise SystemExit(btc_db.main(sys.argv[1:]))', str(tmp_path),
                             'import', str(ledger), '--db', str(database)], cwd=tmp_path, env={},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute('SELECT serial,address FROM wallets').fetchall() == [
            ('SYNTHETIC', 'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4')]


@pytest.mark.parametrize('mode', ['--help', '--preview'])
def test_standalone_help_and_preview_without_database(tmp_path, mode):
    script = tmp_path / 'btc_envelope_maker.py'
    shutil.copyfile(SOURCE / script.name, script)
    config = tmp_path / 'synthetic.toml'
    config.write_text('timezone = "UTC"\n')
    result = subprocess.run([sys.executable, '-B', str(script), mode, '--config', str(config),
                             '--out', str(tmp_path / 'output')], cwd=tmp_path,
                            env={'TMPDIR': os.environ['TMPDIR'], 'PYTHONDONTWRITEBYTECODE': '1'},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    if mode == '--preview':
        assert list((tmp_path / 'output').rglob('*.pdf'))
        assert not list((tmp_path / 'output').rglob('*.csv'))
    else:
        assert not (tmp_path / 'output').exists()
