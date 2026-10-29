from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ADDRESS = 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'


def main():
    with tempfile.TemporaryDirectory(prefix='bitcoin4fun-publication-test-') as directory:
        temp = Path(directory)
        subprocess.run(['git', 'init', '-q', temp], check=True)
        subprocess.run(['git', '-C', temp, 'config', 'user.email', 'test@example.invalid'], check=True)
        subprocess.run(['git', '-C', temp, 'config', 'user.name', 'test'], check=True)
        script = ROOT / 'scripts/check_publication.py'
        # Execute the guard from an isolated copy with the same project layout.
        (temp / 'scripts').mkdir()
        (temp / 'scripts/check_publication.py').write_bytes(script.read_bytes())
        (temp / 'wallets.db').write_text('SYNTHETIC')
        subprocess.run(['git', '-C', temp, 'add', 'wallets.db'], check=True)
        result = subprocess.run(['python3', str(temp / 'scripts/check_publication.py')], capture_output=True, text=True)
        assert result.returncode == 1 and 'forbidden publication path' in result.stdout
        subprocess.run(['git', '-C', temp, 'rm', '--cached', '-q', 'wallets.db'], check=True)
        (temp / 'safe.txt').write_text('public documentation')
        subprocess.run(['git', '-C', temp, 'add', 'safe.txt'], check=True)
        result = subprocess.run(['python3', str(temp / 'scripts/check_publication.py')], capture_output=True, text=True)
        assert result.returncode == 0
    print('Publication guard negative and positive controls passed')


if __name__ == '__main__':
    main()
