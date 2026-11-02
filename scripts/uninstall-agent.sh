#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo '请以 root 运行'; exit 1; }
systemctl disable --now sentinel-agent 2>/dev/null || true
if [[ -f /etc/systemd/system/sentinel-agent.service ]]; then
  rm -- /etc/systemd/system/sentinel-agent.service
fi
systemctl daemon-reload
echo '服务已卸载。程序 /opt/traffic-sentinel 和历史 /var/lib/traffic-sentinel 已保留。'
echo '请在 Web 撤销此节点凭据。需要删除历史时，请核对目录后另行处理。'
