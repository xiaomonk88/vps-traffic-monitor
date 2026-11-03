# Debian 13 部署与维护

Windows 本机未安装 Docker。GitHub Actions 已通过 Linux Python 3.11/3.13 测试、amd64 镜像构建及容器重启持久化检查；记录见仓库 Actions 和 TESTING.md。没有执行用户 VPS 的远程部署。

## 推荐：一键安装

以 root 在 Debian 12 / 13 执行：

```bash
curl -fsSL https://raw.githubusercontent.com/xiaomonk88/vps-traffic-monitor/main/install.sh | bash
```

无需填写域名，即可准备 Docker、构建并启动主控，面板监听 `0.0.0.0:18080`（`--port` / `--bind` 可修改）。使用 `/opt/traffic-sentinel-server/current` 管理服务，`/opt/traffic-sentinel-server/.env` 保存入口参数。程序按版本放入 releases 子目录，数据库使用固定名称的 Compose 数据卷。升级加 `--upgrade`，不删除数据卷。

安装器当前支持 amd64/arm64；GitHub CI 默认仅验证 amd64 容器。系统安装、反向代理和 arm64 仍需目标机实测。若已有容器环境但缺少 Compose，安装器会提示补齐，不擅自卸载冲突组件。

以下是可选的手动部署和维护方法。

## 1. 准备主控

目标机需要 Docker Engine 和 Compose v2。容器把面板发布在 `.env` 中的 `SENTINEL_BIND:SENTINEL_PORT`（默认 `0.0.0.0:18080`），不占用 80/443。HTTPS 与域名由自己的反向代理（1Panel、Nginx 等）提供，代理地址填 `http://127.0.0.1:端口`。远程 Agent 只能通过 HTTPS 连接主控。

官方参考：

- Docker Debian 安装：`https://docs.docker.com/engine/install/debian/`
- HTTPX SOCKS：`https://www.python-httpx.org/advanced/proxies/`

将 `dist/traffic-sentinel-0.1.5-source.zip` 上传并解压到目标目录，例如 `/opt/traffic-sentinel-server`。在解压后的项目根目录执行：

```bash
cp .env.example .env
chmod 600 .env
nano .env
# 按需修改监听地址与端口
docker compose config --quiet
docker compose build --pull
docker compose up -d
docker compose ps
docker compose logs --tail=50 app
```

读取初始化密钥，在网页创建管理员：

```bash
docker compose exec app cat /data/setup-token.txt
```

初始化成功后此文件自动删除。在“系统设置”将公开地址设为实际的 `https://主控域名`，再生成远程 Agent 安装命令。主控用单个进程运行，内含调度器；不要额外添加多 worker 或多副本。

Docker 构建包含 Vue 前端和 Linux Agent 发布包。Python 运行依赖在 `requirements-lock.txt` 固定，前端使用 `package-lock.json`；基础镜像目前固定版本系列（Python 3.13、Node 24），未锁定不可变 digest。amd64 镜像已在 GitHub Linux 运行器完成构建与启动验证；arm64 和目标 VPS 的网络环境仍需实测。

## 2. Linux Agent

第一版安装器面向 systemd 主机，需要已安装 **Python 3.11+、curl、CA 证书**。Debian 13 可准备：

```bash
apt-get update
apt-get install -y python3 curl ca-certificates
```

在面板添加节点，选择 Linux 和连接方式，复制生成的命令，以 root 或 sudo 运行。安装器检查环境、下载并校验包、创建专用账号与 systemd 服务。Linux 发布包内置纯 Python HTTP/SOCKS 依赖，不需要在被监控 VPS 上运行 pip；系统仍需 Python、标准库、系统 CA 和时区数据。

代理安装时，在“系统设置 → Agent 连接代理”保存默认 SOCKS5（或添加服务器时单独填写），连接方式选择“SOCKS5 代理”。生成的命令已包含代理：下载脚本、下载 Agent 包、注册和后续运行都经过该代理，代理通过管道传入（`--proxy-stdin`），不出现在进程参数中。`socks5://` 会自动按 `socks5h` 处理，让代理解析目标域名。含凭据的命令不要提交到代码仓库或公开分享。

```bash
systemctl status sentinel-agent
journalctl -u sentinel-agent -n 50
sudo -u sentinel-agent python3 /opt/traffic-sentinel/current/run-agent.py diagnose --data /var/lib/traffic-sentinel
```

安装后在面板确认网卡，再填写计费规则与校准余额。Linux Agent 使用网卡计数；默认会尝试选出默认路由接口，有隧道、多出口时需要人工确认。

修改代理或网卡须在节点本地执行，修改后重启服务：

```bash
sudo -u sentinel-agent python3 /opt/traffic-sentinel/current/run-agent.py configure --data /var/lib/traffic-sentinel --proxy
# 或 --direct；更换网卡使用 --interface eth0
systemctl restart sentinel-agent
```

若 Agent 断开，不依赖主控远程推送代理修复配置。直接通过已有 SSH 连接操作。

## 3. 升级与卸载

主控升级前导出备份，然后用新版本源代码构建并启动。保留 Compose 项目名和命名数据卷，避免误接空数据目录：

```bash
docker compose build --pull app
docker compose up -d app
docker compose ps
```

Agent 为手动升级：从主控获取新安装脚本（下载路径仍需使用现有代理），执行：

```bash
sudo bash install-sentinel.sh --server https://你的主控域名 --upgrade
```

升级下载自动复用 `/var/lib/traffic-sentinel/config.json` 的代理；无需再次注册。`--proxy` 可覆盖本次下载通道，已有 Agent 运行配置不会随这个参数改变；更换长期代理请先执行 `configure`。升级保留状态库，切换版本目录；服务启动失败会尝试回退旧程序。此检查只确认进程启动，仍需到网页确认心跳和流量上报。

卸载：上传交付包内的 `scripts/uninstall-agent.sh` 并用 root 执行。只停止并移除服务，默认保留程序、配置和数据，便于恢复。若已确定不再监控，可在面板撤销或删除对应节点。

## 4. 备份与恢复

每日数据库备份在应用数据卷的 `/data/backups`，保留 7 份；加密主密钥独立存放在 `/data/master.key`。在网页导出的完整备份 ZIP 同时含数据库和主密钥。务必再保存一份到其他机器。

Windows 迁移到 Docker，或 Docker 灾后恢复：

1. 在旧主控“系统设置”导出备份 ZIP。
2. 新主控先完成构建，停止应用，保留数据卷。
3. 在目标机用 `umask 077` 的受限目录解压备份，确认仅恢复 `sentinel.db` 和 `master.key`，不要把其他来源不明文件覆盖进程序目录。
4. 将目标卷原内容完整保存到旁边的归档目录，再以 UID/GID 10001 写入这两个文件；恢复时不能留下旧的 `sentinel.db-wal` / `sentinel.db-shm`。以下命令使用已停止的 app 卷，避免直接操作未知 Docker 内部目录。
5. 启动应用，登录后检查节点、计费、Telegram 设置和采集数据。

```bash
docker compose stop app
mkdir -p restore
chmod 700 restore
# 将自己导出的 sentinel.db 和 master.key 放进 ./restore
chmod 600 restore/sentinel.db restore/master.key
docker compose run --rm --no-deps --user 0 -v "$PWD/restore:/restore:ro" app python -c 'import datetime,pathlib,shutil,os,sqlite3; d=pathlib.Path("/data"); s=pathlib.Path("/restore"); c=sqlite3.connect("file:/restore/sentinel.db?mode=ro",uri=True); assert c.execute("pragma integrity_check").fetchone()[0]=="ok"; c.close(); b=d/("before-restore-"+datetime.datetime.now().strftime("%Y%m%d%H%M%S")); b.mkdir(mode=0o700); names=("sentinel.db","sentinel.db-wal","sentinel.db-shm","master.key","setup-token.txt"); [(d/n).rename(b/n) for n in names if (d/n).exists()]; [(shutil.copyfile(s/n,d/n),os.chmod(d/n,0o600),os.chown(d/n,10001,10001)) for n in ("sentinel.db","master.key")]'
docker compose up -d app
```

以上恢复流程提供操作说明，尚未在 Docker 实机执行。恢复期间不应另开其他 app 进程。数据导出接口和数据库备份完整性已有本地测试，跨环境恢复仍需核验。

注意：从 Windows 迁移后修改主控公开地址。已有 Windows 测试 Agent 仍指向原本机地址；正式 VPS 请在新主控生成并安装自己的节点。恢复旧备份时 Agent 会尝试重放保留的 7 天记录，更久缺口会标记异常并需要人工校准。

## 5. 上线验收

- HTTPS 访问、管理员登录、重启容器后状态保留。
- 接入一台 Linux Agent，确认默认网卡及约一分钟内上报。
- 首次校准，跑一小段流量，核对下降方向和量级。
- 重启 Agent 和 VPS，累计值继续递增，不重复计数。
- 暂时中断上报，恢复后补报；有代理的节点验证代理失效不会直连。
- 用自己的 Bot 完成测试消息、日报、离线恢复提醒。
- 导出备份，在独立数据卷验证恢复，避免直接覆盖唯一正式数据。

尚未提供目标机连接信息，以上实机验收均未执行。

## v0.1.0 Agent 启动失败修复

若注册成功，但日志出现 `run-agent.py: [Errno 13] Permission denied`，是早期安装器把程序父目录创建为 root 私有目录。以 root 修复：

```bash
chmod 755 /opt/traffic-sentinel /opt/traffic-sentinel/releases
systemctl restart sentinel-agent
systemctl status sentinel-agent --no-pager -l
```

保留 `/var/lib/traffic-sentinel` 的 700 权限，不需要重新注册或删除配置。约一分钟后检查 Web 心跳。v0.1.1 安装器明确设置程序目录 755，并在注册前以服务账号校验程序能否运行；升级也修复已有父目录权限。

主控升级到 v0.1.1 后，Web 生成的安装命令会使用修正版脚本。已通过上面命令修复的节点无需重装。
