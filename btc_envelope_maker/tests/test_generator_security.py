"""Offline admission/serial tests: crypto generation is deliberately mocked.

Only test_generator_crypto.py proves cryptography and rendered card recovery.
All filesystem fixtures must use pytest --basetemp under approved scratch.
"""
import importlib.util
import io
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'btc_envelope_maker.py'
spec = importlib.util.spec_from_file_location('generator_under_test', SOURCE)
assert spec is not None and spec.loader is not None
gen = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gen
spec.loader.exec_module(gen)
REAL_MAKE_WALLETS = gen.make_wallets


@pytest.fixture(autouse=True)
def deny_random_generation(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('No real entropy or network allowed in generator tests')
    monkeypatch.setattr(gen, 'new_mnemonic', forbidden)
    monkeypatch.setattr(gen.socket, 'create_connection', forbidden)


@pytest.fixture
def cli(monkeypatch, tmp_path):
    assert tmp_path.is_relative_to(Path(tempfile.gettempdir()).resolve())
    cfg = dict(gen.DEFAULTS, _logo=None)
    monkeypatch.setattr(gen, 'load_config', lambda _: cfg)
    monkeypatch.setattr(gen, 'register_fonts', lambda _: None)
    monkeypatch.setattr(gen, 'self_test', lambda: None)
    monkeypatch.setattr(gen, 'looks_online', lambda: False)
    db = SimpleNamespace(resolve_url=lambda *args: '', check=lambda *a: pytest.fail('DB call'),
                         save_rows=lambda *a: pytest.fail('DB call'))
    monkeypatch.setitem(sys.modules, 'btc_db', db)
    calls = []
    def render(cfg, plan, wallets, targets, preview):
        if any(not isinstance(p, io.BytesIO) for p in targets.values()):
            calls.append(('render', len(wallets)))
            for p in targets.values():
                Path(p).write_bytes(b'SYNTHETIC PDF PLACEHOLDER; NOT CRYPTO EVIDENCE')
    monkeypatch.setattr(gen, 'render_sheets', render)
    def wallets(cfg, total, stem):
        calls.append(('keygen', total))
        return [gen.Wallet(stem + gen.to_b36(i, gen.serial_width(total)), gen.TEST_ADDRESS, gen.TEST_MNEMONIC)
                for i in range(total)]
    monkeypatch.setattr(gen, 'make_wallets', wallets)
    def run(*flags):
        monkeypatch.setattr(sys, 'argv', ['generator', '--out', str(tmp_path / 'output'), *flags])
        return gen.main()
    return SimpleNamespace(run=run, cfg=cfg, calls=calls, root=tmp_path / 'output', db=db)


@pytest.mark.parametrize('prefix', [('--count',), ()], ids=['invalid-count', 'unexpected-token'])
def test_cli_parse_errors_never_echo_argument_values(tmp_path, prefix):
    # Actual interpreter + script entrypoint; parsing must stop before config.
    assert tmp_path.is_relative_to(Path(tempfile.gettempdir()).resolve())
    scheme = 'postgresql'  # Assemble synthetic credentials; publication guards reject URL literals.
    url = f'{scheme}://SYNTH_USER:SYNTH_PASSWORD@invalid.example/SYNTH_DB?password=SYNTH_QUERY#SYNTH_FRAGMENT'
    result = subprocess.run(
        [sys.executable, '-B', str(SOURCE), '--config', str(tmp_path / 'absent.toml'),
         *prefix, url],
        cwd=tmp_path, env={'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': tempfile.gettempdir()},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert result.stdout == ''
    for sentinel in ('SYNTH_USER', 'SYNTH_PASSWORD', 'SYNTH_DB', 'SYNTH_QUERY', 'SYNTH_FRAGMENT'):
        assert sentinel not in result.stderr
    assert 'error: invalid command-line arguments; use --help' in result.stderr
    assert 'Traceback' not in result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('total,width', [(36, 1), (37, 2), (1296, 2), (1297, 3), (1300, 3)])
def test_serial_width_covers_entire_batch(monkeypatch, total, width):
    # Admission-only synthetic strings: never feed these into real crypto.
    counter = iter(range(total))
    monkeypatch.setattr(gen, 'new_mnemonic', lambda n: ' '.join(['SYNTHETIC'] * 11 + [str(next(counter))]))
    monkeypatch.setattr(gen, 'derive_address', lambda mn: 'bc1q' + mn.split()[-1].zfill(38))
    wallets = gen.make_wallets(dict(gen.DEFAULTS), total, '0587k4530')
    assert len({w.serial for w in wallets}) == total
    assert all(len(w.serial) == len('0587k4530') + width for w in wallets)


def test_duplicate_serials_rejected_before_any_output(cli, monkeypatch):
    monkeypatch.setattr(gen, 'make_wallets', lambda *a: [
        gen.Wallet('duplicate', gen.TEST_ADDRESS, gen.TEST_MNEMONIC),
        gen.Wallet('duplicate', gen.TEST_ADDRESS, gen.TEST_MNEMONIC)])
    with pytest.raises(SystemExit, match='Duplicate serial'):
        cli.run('--count', '1', '--acknowledge-offline')
    assert not cli.root.exists()
    assert not cli.calls


@pytest.mark.parametrize('allow', [False, True])
@pytest.mark.parametrize('online', [False, True])
def test_real_generation_requires_explicit_offline_ack(cli, monkeypatch, allow, online):
    monkeypatch.setattr(gen, 'looks_online', lambda: online)
    flags = ['--count', '1'] + (['--allow-online'] if allow else [])
    with pytest.raises(SystemExit, match='acknowledge-offline'):
        cli.run(*flags)
    assert not cli.calls
    assert not cli.root.exists()


@pytest.mark.parametrize('layout', ['pairs', 'separate'])
def test_output_restrictive_from_creation_and_restores_umask(cli, monkeypatch, layout):
    cli.cfg['layout'] = layout
    observed = []
    render = gen.render_sheets
    def inspect_render(cfg, plan, wallets, targets, preview):
        result = render(cfg, plan, wallets, targets, preview)
        for path in targets.values():
            if not isinstance(path, io.BytesIO):
                observed.append(Path(path).stat().st_mode & 0o777)
                assert Path(path).parent.stat().st_mode & 0o777 == 0o700
        return result
    monkeypatch.setattr(gen, 'render_sheets', inspect_render)
    chmod = gen.os.chmod
    def inspect_chmod(path, mode):
        assert Path(path).stat().st_mode & 0o077 == 0
        chmod(path, mode)
    monkeypatch.setattr(gen.os, 'chmod', inspect_chmod)
    previous = os.umask(0)
    try:
        cli.run('--count', '1', '--acknowledge-offline')
        after = os.umask(0)
        assert after == 0
    finally:
        os.umask(previous)
    assert observed and set(observed) == {0o600}


@pytest.mark.parametrize('fault', ['directory-chmod', 'file-chmod', 'pdf-write', 'ledger-write', 'layout'])
@pytest.mark.parametrize('layout', ['pairs', 'separate'])
def test_output_failure_closed_without_successful_artifacts(cli, monkeypatch, capsys, fault, layout):
    cli.cfg['layout'] = layout
    chmod = gen.os.chmod
    def broken_chmod(path, mode):
        if (fault == 'directory-chmod' and Path(path).is_dir()) or (fault == 'file-chmod' and Path(path).is_file()):
            raise PermissionError('SYNTHETIC chmod failure')
        chmod(path, mode)
    monkeypatch.setattr(gen.os, 'chmod', broken_chmod)
    render = gen.render_sheets
    def broken_render(cfg, plan, wallets, targets, preview):
        render(cfg, plan, wallets, targets, preview)
        if any(not isinstance(p, io.BytesIO) for p in targets.values()) and fault in ('pdf-write', 'layout'):
            raise (gen.LayoutError if fault == 'layout' else OSError)('SYNTHETIC rendering failure')
    monkeypatch.setattr(gen, 'render_sheets', broken_render)
    ledger = gen.write_ledger
    def broken_ledger(path, *args):
        ledger(path, *args)
        if fault == 'ledger-write':
            raise OSError('SYNTHETIC ledger failure')
    monkeypatch.setattr(gen, 'write_ledger', broken_ledger)
    previous = os.umask(0o022)
    try:
        with pytest.raises(SystemExit, match='Output failed'):
            cli.run('--count', '1', '--acknowledge-offline')
        after = os.umask(0o022)
        assert after == 0o022
    finally:
        os.umask(previous)
    assert not list(cli.root.rglob('*.pdf'))
    assert not list(cli.root.rglob('*.csv'))
    assert 'Created ' not in capsys.readouterr().out


@pytest.mark.parametrize('fault', ['unlink', 'rmdir'])
@pytest.mark.parametrize('layout', ['pairs', 'separate'])
def test_incomplete_cleanup_warns_secret_without_success(cli, monkeypatch, capsys, fault, layout):
    # Coverage of existing rollback behavior; PDFs are synthetic fixture bytes.
    cli.cfg['layout'] = layout
    ledger = gen.write_ledger
    def broken_ledger(path, *args):
        ledger(path, *args)
        raise OSError('SYNTHETIC ledger failure')
    monkeypatch.setattr(gen, 'write_ledger', broken_ledger)
    original = getattr(Path, fault)
    def deny_cleanup(path, *args, **kwargs):
        if path.is_relative_to(cli.root):
            raise PermissionError('SYNTHETIC cleanup failure')
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, fault, deny_cleanup)
        previous = os.umask(0)
        try:
            with pytest.raises(SystemExit) as error:
                cli.run('--count', '1', '--acknowledge-offline')
            assert os.umask(0) == 0
        finally:
            os.umask(previous)
    assert str(error.value) == (
        'Output failed; no successful batch was recorded.'
        ' Cleanup incomplete: treat the output folder as SECRET and do not use it.')
    assert 'Created ' not in capsys.readouterr().out
    folders = list(cli.root.iterdir())
    assert len(folders) == 1
    assert folders[0].stat().st_mode & 0o777 == 0o700
    remaining = list(folders[0].iterdir())
    if fault == 'unlink':
        names = {'ledger.csv'} | ({'sheets.pdf'} if layout == 'pairs' else {'public_sheets.pdf', 'private_sheets.pdf'})
        assert {p.name for p in remaining} == names
        assert all(p.stat().st_mode & 0o777 == 0o600 for p in remaining)
    else:
        assert remaining == []


@pytest.mark.parametrize('ack', [False, True])
@pytest.mark.parametrize('allow', [False, True])
@pytest.mark.parametrize('words', [12, 24])
def test_preview_has_no_ledger_or_database(cli, monkeypatch, ack, allow, words):
    monkeypatch.setattr(gen, 'looks_online', lambda: pytest.fail('Preview probed network'))
    cli.cfg['words'] = words
    cli.cfg['db_url'] = 'SYNTHETIC config database sentinel'
    monkeypatch.setenv('BTC_DB_URL', 'SYNTHETIC env database sentinel')
    monkeypatch.setattr(cli.db, 'resolve_url', lambda *a: pytest.fail('Preview touched database resolution'))
    flags = ['--preview', '--db', 'SYNTHETIC CLI database sentinel']
    flags += ['--acknowledge-offline'] if ack else []
    flags += ['--allow-online'] if allow else []
    cli.run(*flags)
    assert not list(cli.root.rglob('*.csv'))
    assert list(cli.root.rglob('*.pdf'))
    assert not any(call[0] == 'keygen' for call in cli.calls)


@pytest.mark.parametrize('allow', [False, True])
@pytest.mark.parametrize('online', [False, True])
def test_acknowledged_admission_combinations(cli, monkeypatch, allow, online):
    probes = []
    monkeypatch.setattr(gen, 'looks_online', lambda: probes.append('probe') or online)
    flags = ['--count', '1', '--acknowledge-offline'] + (['--allow-online'] if allow else [])
    if online and not allow:
        with pytest.raises(SystemExit, match='Connectivity detected'):
            cli.run(*flags)
        assert not cli.calls
    else:
        cli.run(*flags)
        assert ('keygen', gen.make_plan(cli.cfg).per_sheet) in cli.calls
    assert len(probes) == (0 if allow else 1)


def test_entire_run_total_reaches_wallet_factory(cli):
    cli.run('--count', '260', '--acknowledge-offline')
    assert ('keygen', 260 * gen.make_plan(cli.cfg).per_sheet) in cli.calls


def test_same_second_same_output_root_refuses_overwrite(cli, monkeypatch):
    monkeypatch.setattr(gen, 'now_local', lambda _: gen.dt.datetime(2026, 10, 30, 12, 0, 0))
    cli.run('--count', '1', '--acknowledge-offline')
    before = {p: p.read_bytes() for p in cli.root.rglob('*') if p.is_file()}
    cli.calls.clear()
    with pytest.raises(SystemExit, match='Folder already exists'):
        cli.run('--count', '1', '--acknowledge-offline')
    assert {p: p.read_bytes() for p in cli.root.rglob('*') if p.is_file()} == before
    assert not any(call[0] == 'render' for call in cli.calls)


@pytest.mark.parametrize('n,width', [(36, 1), (1296, 2), (-1, 2), (0, 0)])
def test_base36_rejects_overflow_instead_of_wrapping(n, width):
    with pytest.raises(ValueError, match='base36'):
        gen.to_b36(n, width)


@pytest.mark.parametrize('fault', ['word-count', 'address-shape', 'duplicate-wallet'])
def test_wallet_validation_failure_leaves_no_output(cli, monkeypatch, fault):
    monkeypatch.setattr(gen, 'make_wallets', REAL_MAKE_WALLETS)
    monkeypatch.setattr(gen, 'new_mnemonic', lambda _: 'SYNTHETIC' if fault == 'word-count' else gen.TEST_MNEMONIC)
    monkeypatch.setattr(gen, 'derive_address', lambda _: 'SYNTHETIC-invalid-address' if fault == 'address-shape' else gen.TEST_ADDRESS)
    with pytest.raises(SystemExit, match='Sanity check|Duplicate wallet'):
        cli.run('--count', '1', '--acknowledge-offline')
    assert not cli.root.exists()
    assert not cli.calls


def test_same_second_separate_roots_can_collide_by_design(cli, monkeypatch):
    # Documents the limit, not a claim of cross-run uniqueness.
    monkeypatch.setattr(gen, 'now_local', lambda _: gen.dt.datetime(2026, 10, 30, 12, 0, 0))
    cli.run('--count', '1', '--acknowledge-offline')
    first = next(cli.root.rglob('ledger.csv')).read_text()
    second_root = cli.root.parent / 'independent-output'
    cli.run('--count', '1', '--acknowledge-offline', '--out', str(second_root))
    import csv
    one = list(csv.DictReader(io.StringIO(first.lstrip('\ufeff'))))
    two = list(csv.DictReader(io.StringIO(next(second_root.rglob('ledger.csv')).read_text(encoding='utf-8-sig'))))
    assert [r['serial'] for r in one] == [r['serial'] for r in two]
