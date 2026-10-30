"""Subprocess-only signal fixture. Never creates random wallet material."""
import importlib.util
import io
import os
from pathlib import Path
import signal
import sys

source, output, layout, checkpoint, ready_fd, wait_fd = sys.argv[1:]
ready_fd, wait_fd = int(ready_fd), int(wait_fd)
spec = importlib.util.spec_from_file_location('signal_generator', source)
gen = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gen
spec.loader.exec_module(gen)

def forbidden(*args, **kwargs):
    raise AssertionError('random generation/network forbidden')
gen.Bip39MnemonicGenerator.FromWordsNumber = forbidden
gen.new_mnemonic = forbidden
gen.socket.create_connection = forbidden
gen.load_config = lambda _: dict(gen.DEFAULTS, layout=layout, _logo=None)
gen.register_fonts = lambda _: None
gen.self_test = lambda: None
gen.now_local = lambda _: gen.dt.datetime(2026, 10, 30, 12, 0, 0)
gen.make_wallets = lambda cfg, total, stem: [gen.Wallet(stem + gen.to_b36(i, gen.serial_width(total)), gen.TEST_ADDRESS, gen.TEST_MNEMONIC) for i in range(total)]

def pause():
    os.write(ready_fd, b'R')
    os.read(wait_fd, 1)  # Parent sends SIGINT only AFTER receiving ready.
    raise AssertionError('checkpoint released without SIGINT')

def render(cfg, plan, wallets, targets, preview):
    for path in targets.values():
        if not isinstance(path, io.BytesIO):
            Path(path).write_bytes(b'SYNTHETIC PARTIAL PDF; NOT CRYPTO EVIDENCE')
            if checkpoint == 'write':
                pause()
gen.render_sheets = render
mkdir = Path.mkdir
if checkpoint == 'existing':
    def before_mkdir(path, *args, **kwargs):
        if path.name.startswith('batch_'):
            assert path.is_dir()
            pause()
        return mkdir(path, *args, **kwargs)
    Path.mkdir = before_mkdir
signal.signal(signal.SIGINT, signal.default_int_handler)
sys.argv = ['generator', '--config', '/nonexistent-synthetic.toml', '--out', output, '--count', '1', '--allow-online', '--acknowledge-offline']
previous = os.umask(0o022)
try:
    gen.main()
except KeyboardInterrupt:
    raise SystemExit(130)
finally:
    current = os.umask(previous)
    print('UMASK_RESTORED' if current == 0o022 else 'UMASK_BAD', flush=True)
