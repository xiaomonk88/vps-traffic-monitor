"""Run only in a disposable Linux container as root: real installer and service UID.

systemctl is substituted (no systemd in the test container); it runs an actual
Agent collection/report as the service account. Enrollment and downloads use a
local fixture server. Checks new installation, private state, upgrade repair and proxy switching.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

assert os.getuid() == 0 and Path('/.dockerenv').exists(), 'Use a disposable root Docker container only'
base = Path('/opt/traffic-sentinel')
state = Path('/var/lib/traffic-sentinel')
assert not base.exists() and not state.exists(), 'Refusing to touch an existing installation'
Path('/etc/systemd/system').mkdir(parents=True, exist_ok=True)
reports = []
enrollments = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def answer(self, value):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(value).encode())

    def do_GET(self):
        if self.path == '/healthz':
            self.answer({'ok': True})
            return
        name = self.path.removeprefix('/downloads/')
        if name not in ('sentinel-agent.zip', 'SHA256SUMS'):
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write((Path('/app/dist') / name).read_bytes())

    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path.endswith('/enroll'):
            if value.get('token') == 'expired-token':
                self.send_error(400)
                return
            enrollments.append(value)
            self.answer({'node_id': f'fixture-node-{len(enrollments)}', 'credential': f'fixture-credential-{len(enrollments)}'})
        elif self.path.endswith('/report'):
            reports.append(value)
            self.answer({'ack': max((s['seq'] for s in value['samples']), default=0)})
        else:
            self.send_error(404)


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix='sentinel-install-test-') as directory:
        shim = Path(directory)
        (shim / 'curl').write_text(f'''#!{sys.executable}
import sys,urllib.request
from pathlib import Path
url=next(a for a in sys.argv if a.startswith('http://127.0.0.1:'))
target=sys.argv[sys.argv.index('-o')+1]
Path(target).write_bytes(urllib.request.urlopen(url,timeout=10).read())
''')
        (shim / 'systemctl').write_text(f'''#!/bin/sh
if [ "$1" = enable ]; then
  exec runuser -u sentinel-agent -- {sys.executable} /opt/traffic-sentinel/current/run-agent.py once --data /var/lib/traffic-sentinel
fi
exit 0
''')
        for file in shim.iterdir():
            file.chmod(0o755)
        environment = dict(os.environ, PATH=f'{shim}:'+os.environ['PATH'])
        command = ['bash', '/app/scripts/install-agent.sh', '--server', f'http://127.0.0.1:{server.server_port}']
        subprocess.run([*command, '--token', 'fixture-token'], env=environment, check=True, timeout=45)
        assert reports and reports[0]['meta']['interface']
        original = (state/'config.json').read_bytes()
        assert state.stat().st_mode & 0o777 == 0o700
        assert (state/'config.json').stat().st_mode & 0o777 == 0o600
        assert subprocess.run(['runuser','-u','nobody','--','test','-r',str(state/'config.json')]).returncode != 0
        # Reproduce old private ancestors, then verify the actual upgrade repairs them.
        base.chmod(0o700)
        (base/'releases').chmod(0o700)
        subprocess.run([*command, '--upgrade'], env=environment, check=True, timeout=45)
        assert base.stat().st_mode & 0o777 == 0o755
        assert (base/'releases').stat().st_mode & 0o777 == 0o755
        assert (state/'config.json').read_bytes() == original
        assert len(reports) >= 2
        # The proxy an Agent uses has died: a switch to another dead proxy is refused and
        # leaves the config alone; switching to direct succeeds and the Agent reports again.
        config = json.loads((state/'config.json').read_text())
        config['proxy'] = 'socks5h://127.0.0.1:1'
        (state/'config.json').write_text(json.dumps(config))
        dead = (state/'config.json').read_bytes()
        refused = subprocess.run([*command, '--upgrade', '--proxy-stdin'], input='socks5h://127.0.0.1:2\n', env=environment, text=True, capture_output=True, timeout=60)
        assert refused.returncode != 0 and '原配置' in refused.stderr, refused.stderr
        assert (state/'config.json').read_bytes() == dead
        before = len(reports)
        subprocess.run([*command, '--upgrade', '--direct'], env=environment, check=True, timeout=60)
        switched = json.loads((state/'config.json').read_text())
        assert switched['proxy'] == '' and switched['credential'] == config['credential']
        assert (state/'config.json').stat().st_uid == int(subprocess.check_output(['id', '-u', 'sentinel-agent']))
        assert len(reports) > before and reports[-1]['meta']['connection'] == 'direct'
        # Re-register an installed machine with a new token (server deleted and re-added).
        before = json.loads((state/'config.json').read_text())
        result = subprocess.run([*command, '--token', 'second-token'], env=environment, text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        after = json.loads((state/'config.json').read_text())
        assert after['credential'] != before['credential'] and after['interface'] == before['interface']
        backups = sorted(Path('/var/lib').glob('traffic-sentinel.bak-*'))
        assert backups and json.loads((backups[-1]/'config.json').read_text())['credential'] == before['credential']
        assert (state/'config.json').stat().st_uid == int(subprocess.check_output(['id', '-u', 'sentinel-agent']))
        # A bad token must restore the previous registration instead of leaving no Agent.
        current = (state/'config.json').read_bytes()
        failed = subprocess.run([*command, '--token', 'expired-token'], env=environment, text=True, capture_output=True, timeout=60)
        assert failed.returncode != 0 and '已恢复原注册' in failed.stderr, failed.stdout + failed.stderr
        assert (state/'config.json').read_bytes() == current
        # Without a token an installed machine is still refused.
        refused = subprocess.run(command, env=environment, text=True, capture_output=True, timeout=60)
        assert refused.returncode != 0 and '已安装 Agent' in refused.stdout
        print('Fresh install, unprivileged collection/report, private credentials, upgrade permission repair, proxy switching and re-registration passed')
finally:
    server.shutdown()
    server.server_close()
