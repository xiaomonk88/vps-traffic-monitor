#!/usr/bin/env bash
set -euo pipefail
umask 077

SERVER=""; TOKEN=""; USE_PROXY=0; INTERFACE=""; UPGRADE=0
BASE=/opt/traffic-sentinel
STATE=/var/lib/traffic-sentinel
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server) SERVER="$2"; shift 2;;
    --token) TOKEN="$2"; shift 2;;
    --proxy) USE_PROXY=1; shift;;
    --interface) INTERFACE="$2"; shift 2;;
    --upgrade) UPGRADE=1; shift;;
    *) echo "未知参数：$1" >&2; exit 1;;
  esac
done
[[ $(id -u) -eq 0 ]] || { echo '请以 root 或 sudo 运行安装器'; exit 1; }
command -v python3 >/dev/null || { echo '需要 Python 3.11+。Debian 可先安装：apt-get update && apt-get install -y python3 ca-certificates curl'; exit 1; }
PYTHON=$(command -v python3)
python3 -c 'import sys; assert sys.version_info >= (3,11), "需要 Python 3.11+"'
command -v curl >/dev/null || { echo '请先安装 curl 和 ca-certificates'; exit 1; }
command -v systemctl >/dev/null || { echo '第一版安装器需要 systemd'; exit 1; }
command -v runuser >/dev/null || { echo '需要 runuser（Debian/Ubuntu 的 util-linux 软件包）'; exit 1; }
if [[ -f "$STATE/config.json" && "$UPGRADE" -ne 1 ]]; then
  echo '已经安装；升级请加 --upgrade。修改代理请使用本地 configure 命令。'; exit 1
fi
if [[ "$UPGRADE" -eq 1 && ! -f "$STATE/config.json" ]]; then
  echo '找不到原节点配置，不能升级'; exit 1
fi
[[ -n "$SERVER" ]] || { echo '缺少 --server'; exit 1; }
SERVER="${SERVER%/}"
python3 - "$SERVER" <<'PY'
import sys
from urllib.parse import urlparse
p=urlparse(sys.argv[1])
assert p.scheme=='https' or (p.scheme=='http' and p.hostname in ('localhost','127.0.0.1')), '远程主控必须使用 HTTPS'
assert p.hostname and not p.username and not p.password and not p.query and not p.fragment, '主控地址无效'
PY

TASK_DIR=$(mktemp -d /tmp/sentinel-install.XXXXXXXX)
cleanup() { case "$TASK_DIR" in /tmp/sentinel-install.*) rm -rf -- "$TASK_DIR";; esac; }
trap cleanup EXIT
CURL=(curl --fail --silent --show-error --connect-timeout 15 --max-time 120 --noproxy '')
if [[ "$USE_PROXY" -eq 1 ]]; then
  read -r -s -p 'SOCKS5 URL（例如 socks5h://user:password@host:1080）：' PROXY
  printf '\n'
  printf '%s' "$PROXY" > "$TASK_DIR/proxy-url"
  unset PROXY
elif [[ "$UPGRADE" -eq 1 ]]; then
  python3 - "$STATE/config.json" "$TASK_DIR/proxy-url" <<'PY'
import json, sys
from pathlib import Path
config=json.loads(Path(sys.argv[1]).read_text())
if config.get('proxy'): Path(sys.argv[2]).write_text(config['proxy'])
PY
fi
if [[ -s "$TASK_DIR/proxy-url" ]]; then
  python3 - "$TASK_DIR/proxy-url" "$TASK_DIR/curl.conf" <<'PY'
from pathlib import Path
from urllib.parse import urlparse
import sys
s=Path(sys.argv[1]).read_text().strip(); p=urlparse(s)
assert p.scheme in ('socks5','socks5h') and p.hostname and p.port, 'SOCKS5 URL 格式无效'
assert '\n' not in s and '\r' not in s
if s.startswith('socks5://'): s='socks5h://'+s[len('socks5://'):]
Path(sys.argv[2]).write_text('proxy = "'+s.replace('\\','\\\\').replace('"','\\"')+'"\n')
PY
  CURL+=(--config "$TASK_DIR/curl.conf")
else
  # Direct mode ignores ambient proxy variables just like the Agent.
  CURL+=(--proxy '')
fi
"${CURL[@]}" "$SERVER/downloads/sentinel-agent.zip" -o "$TASK_DIR/agent.zip"
"${CURL[@]}" "$SERVER/downloads/SHA256SUMS" -o "$TASK_DIR/SHA256SUMS"
python3 - "$TASK_DIR" <<'PY'
import hashlib, sys, zipfile
from pathlib import Path
p=Path(sys.argv[1]); expected=(p/'SHA256SUMS').read_text().split()[0]
actual=hashlib.sha256((p/'agent.zip').read_bytes()).hexdigest()
assert actual==expected, '安装包校验失败'
target=(p/'package').resolve()
with zipfile.ZipFile(p/'agent.zip') as z:
    for item in z.infolist():
        path=(target/item.filename).resolve()
        assert path.is_relative_to(target), '安装包路径无效'
    z.extractall(target)
PY

RELEASE="$BASE/releases/$(date +%Y%m%d%H%M%S)-$$"
id sentinel-agent >/dev/null 2>&1 || useradd --system --home-dir "$STATE" --shell /usr/sbin/nologin sentinel-agent
# Program ancestors must be traversable by the unprivileged service account.
# Set existing paths too, so upgrading repairs installations made with umask 077.
install -d -m 0755 "$BASE" "$BASE/releases"
mkdir -p "$STATE"
chown sentinel-agent:sentinel-agent "$STATE"
chmod 700 "$STATE"
mkdir -p "$RELEASE"
cp -a "$TASK_DIR/package/." "$RELEASE/"
chmod -R u=rwX,go=rX "$RELEASE"
if ! runuser -u sentinel-agent -- "$PYTHON" "$RELEASE/run-agent.py" --help >/dev/null; then
  echo '服务账号无法运行 Agent，请检查程序父目录或 Python 路径权限。未执行新注册，原有配置已保留。' >&2
  exit 1
fi
PREVIOUS=$(readlink "$BASE/current" 2>/dev/null || true)
if [[ ! -f "$STATE/config.json" ]]; then
  [[ -n "$TOKEN" ]] || read -r -s -p '一次性注册凭据：' TOKEN
  ARGS=(enroll --server "$SERVER" --data "$STATE")
  [[ -z "$INTERFACE" ]] || ARGS+=(--interface "$INTERFACE")
  [[ "$USE_PROXY" -eq 0 ]] || ARGS+=(--proxy-file "$TASK_DIR/proxy-url")
  # Enrollment token is short-lived; prompt via stdin instead of a process argument.
  SENTINEL_ENROLL_TOKEN="$TOKEN" python3 "$RELEASE/run-agent.py" "${ARGS[@]}"
  unset TOKEN
  chown -R sentinel-agent:sentinel-agent "$STATE"
fi
systemctl stop sentinel-agent 2>/dev/null || true
ln -s "$RELEASE" "$BASE/current.new"
mv -Tf "$BASE/current.new" "$BASE/current"
cat > /etc/systemd/system/sentinel-agent.service <<UNIT
[Unit]
Description=Traffic Sentinel Agent
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=sentinel-agent
Group=sentinel-agent
ExecStart="$PYTHON" /opt/traffic-sentinel/current/run-agent.py run --data /var/lib/traffic-sentinel
Restart=on-failure
RestartSec=10
TimeoutStopSec=45
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/var/lib/traffic-sentinel
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
chmod 0644 /etc/systemd/system/sentinel-agent.service
systemctl daemon-reload
START_FAILED=0
systemctl enable --now sentinel-agent || START_FAILED=1
sleep 2
if [[ "$START_FAILED" == 1 ]] || ! systemctl is-active --quiet sentinel-agent; then
  if [[ -n "$PREVIOUS" && -d "$PREVIOUS" ]]; then
    ln -s "$PREVIOUS" "$BASE/rollback.new"
    mv -Tf "$BASE/rollback.new" "$BASE/current"
    systemctl restart sentinel-agent || true
    echo '新版本启动失败，已尝试恢复旧程序。' >&2
  else
    echo '服务启动失败；没有旧版本可回退，注册配置与数据已保留。' >&2
  fi
  journalctl -u sentinel-agent -n 20 --no-pager >&2 || true
  exit 1
fi
printf '安装完成。查看状态：systemctl status sentinel-agent\n查看日志：journalctl -u sentinel-agent -n 50\n修改代理：sudo -u sentinel-agent python3 /opt/traffic-sentinel/current/run-agent.py configure --proxy --data /var/lib/traffic-sentinel\n修改后：systemctl restart sentinel-agent\n'
