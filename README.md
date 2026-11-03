# 流量哨 · VPS 流量监控

Python 主控 + Python Agent + Vue 中文面板。先在 Windows 本机试用，再将主控部署到 Debian 13 的 Docker。

根据商家余额人工校准，之后用网卡新增流量估算余额，并按配置的月度重置规则进入新周期。**它不会读取商家后台，也不能自动确认商家实际何时重置。** 商家改套餐、计费方式或重置时间后，需要修改配置并重新校准。

## 一键安装到 Debian VPS

主控支持 Debian 12 / 13（amd64 / arm64），以 Docker 单容器运行，通过 `http://服务器IP:端口`（默认 18080）访问，不占用 80/443。HTTPS 与域名请用自己的反向代理（如 1Panel）。以 root 执行：

```bash
curl -fsSL https://raw.githubusercontent.com/xiaomonk88/vps-traffic-monitor/main/install.sh | bash
```

安装器会准备 Docker、下载指定发布版本、构建镜像、启动主控，并显示访问地址和管理员初始化密钥。已有 Docker 时复用，不自动移除已有容器组件。首次构建需要访问 GitHub、Docker 镜像仓库以及 Python/npm 软件源。

指定端口或只允许本机反代访问：

```bash
curl -fsSL https://raw.githubusercontent.com/xiaomonk88/vps-traffic-monitor/main/install.sh -o install-sentinel-server.sh
bash install-sentinel-server.sh --port 18080              # 自定义端口
bash install-sentinel-server.sh --port 18080 --bind 127.0.0.1   # 仅本机反代可访问
```

程序目录为 `/opt/traffic-sentinel-server/current`；数据库保存在 Docker 命名卷，升级时保留。访问面板创建管理员，然后“添加服务器”，复制每台 VPS 专属的 Agent 一键安装命令。受限节点可在面板选择 SOCKS5。

```bash
# 查看主控状态
cd /opt/traffic-sentinel-server/current && docker compose ps
# 升级主控（沿用端口设置和数据卷）
curl -fsSL https://raw.githubusercontent.com/xiaomonk88/vps-traffic-monitor/main/install.sh | bash -s -- --upgrade
```

### 使用 1Panel 反代（HTTPS）

1. 网站 → 创建网站 → 反向代理，填写域名，代理地址填 `http://127.0.0.1:18080`。
2. 为该网站申请并启用 HTTPS 证书。
3. 登录面板 → 系统设置 → 主控访问地址，填写 `https://你的域名`。

远程 VPS 的 Agent 必须通过 HTTPS 连接主控；只用 `IP:端口` 访问时可以正常查看和管理面板，但生成远程 Agent 安装命令需要先配置 HTTPS 地址。反代请指向 `127.0.0.1` 而非公网 IP，主控只信任本机 / 内网来源的 `X-Forwarded-*` 头。

从带 Caddy 的旧版本（≤ v0.1.3）升级时，安装器会自动移除旧的 Caddy 容器并释放 80/443。安装器不会修改云商家防火墙，直接用 IP 访问时请自行放行端口。更多迁移、备份和手动部署步骤见 [DEPLOY.md](DEPLOY.md)。

## Windows 本地启动

本目录已经安装依赖并构建前端。双击 **`启动本地测试.cmd`**，保持启动窗口开启，然后访问 **http://127.0.0.1:8080**。

1. 第一次启动后，在 `data/setup-token.txt` 中复制初始化密钥。
2. 在网页创建管理员，设置至少 12 位密码，然后登录。没有预置通用密码。
3. 点击“添加服务器”，创建一个本机测试节点，选择“Windows 本地测试”。
4. 在本项目根目录另外打开 PowerShell，执行网页生成的注册命令，再执行采集命令。两个窗口都保持开启。
5. 等待约 1 分钟，节点会上报。默认每 10 秒采集、每 60 秒上报，网页每 15 秒刷新。

若从源代码包在另一台 Windows 安装，需要 Python 3.11+、Node.js 22.12+（本机用 24）和可用的 pip/npm 网络。首次运行脚本会安装依赖；失败会停止并显示错误。安装器不会修改系统全局代理。

常用本地命令，在项目根目录执行：

```powershell
# 不重复构建，启动现有版本
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-local.ps1 -SkipBuild

# 查询网卡名称，Windows 可以是“以太网”等中文名称
.\.venv\Scripts\python.exe -m sentinel.agent interfaces

# 若想快速观察变化，替换网页采集命令里的参数
.\.venv\Scripts\python.exe -m sentinel.agent run --data "agent-data/网页生成的节点ID" --sample-seconds 2 --report-seconds 5
```

停止采集使用 Ctrl+C；再次执行相同的 `run --data ...` 即可继续。不要反复注册，也不要删除 Agent 数据目录，否则会丢失本地补报记录。关闭主控后，Agent 会继续本地采集，连接恢复后补报。

自动化测试曾使用单独的 `8081` 端口和 `.runtime/e2e-data`。日常使用请走 `8080` 和 `data`；不要把测试库作为正式数据迁移。

## 配置计费与首次校准

进入节点详情 → “计费设置”，按商家实际情况填写：

| 字段 | 说明 |
| --- | --- |
| 总额度 | 套餐每周期额度，不能只凭剩余量推测 |
| 单位 | GB/TB 为十进制；GiB/TiB 为二进制 |
| 计费方向 | 上传 TX、下载 RX 或双向之和。“单向”仍须确认具体方向 |
| 下次重置 | 商家给出的下一次日期和时刻 |
| 每月几号、时刻 | 后续周期规则；31 日遇短月取月末，之后恢复 31 日 |
| 时区 | 商家的计费时区，例如 Asia/Shanghai 或 UTC |

保存规则后，进入“余额校准”：获取最新采集检查点，等待 Agent 完成往返同步，再刷新商家后台并输入当前剩余量，在 2 分钟内提交。允许以后随时校准，历史采集记录仍保留。

例如：商家当前剩余 563 GB，校准后新增计费流量 10 GB，机器重启后又使用 2 GB，估算余额为 551 GB。跨重启依靠本地数据库和新增区间，不能只把当前网卡总计数当作账单流量。未采集到的关机前尾段、网卡计数口径和商家延迟会造成小幅偏差。

用户提供的那台 VPS 下次重置是 **2026-11-17**，不能直接当作每月 1 日重置。总额度是否 600 GB、单向指哪个方向、准确重置时间和时区仍需要按商家面板核实。为测试填写的套餐参数不会变成商家事实。

## Telegram

在“通知设置”添加一个或多个**通知渠道**（每个渠道包含名称、Bot Token 和 Chat ID），再设置日报时区和发送时间。先向自己的 Bot 发起会话，群组需已加入 Bot 并允许发言。

- 每个渠道可单独启用/停用，并分别选择接收“日报”和“告警”；多个渠道可共用同一个 Bot。
- **服务器分配到渠道**：每个渠道选择通知哪些服务器（或“全部服务器”，含以后新增的）。服务器的告警只发给分配了它的渠道，日报也只包含该渠道的服务器；**未分配任何渠道的服务器不发送通知**，列表中以 🔕 标记。可在渠道编辑框勾选服务器，或在服务器详情 → 管理 → Telegram 通知中勾选渠道。新建渠道默认不分配服务器；从 v0.1.6 及更早版本升级时，已有渠道自动设为“全部服务器”，保持原有通知不变。
- 每个渠道独立排队与重试，一个渠道失败不影响其他渠道。
- 可以预览日报、对单个渠道或全部渠道发测试消息、手动发送日报。
- 从旧版本升级时，原来的 Bot Token 与 Chat ID 会自动迁移为名为“默认”的渠道。
- 日报汇总当天 0 点至发送时刻的流量：开头是该渠道所属服务器的今日上传 / 下载 / 总计，然后逐台列出今日上传 / 下载 / 合计、当前预计余额，以及下次重置时间和剩余天数（如“2026-11-20 13:35（还剩 16 天 22 小时）”，按计费时区显示）。
- 默认在已使用 80%、90%、95% 时提醒，支持调整阈值。
- 支持离线/恢复、重置前 24 小时、进入新周期、预计提前耗尽提醒。
- 主控访问 Telegram 的 SOCKS5 代理独立配置；不会套用某台 Agent 的代理。
- Bot Token 和主控 Telegram 代理凭据在数据库中加密，依赖 `data/master.key` 解密。

消息由主控发送，因此 Windows 试用时主控必须保持运行。主控完全停机时无法自行发通知。当前没有实际 Bot 凭据，尚未向 Telegram 投递测试消息。

## SOCKS5 连接

各 Agent 独立选择直连或 SOCKS5。代理故障会留存本地记录并重试，**不会自动回退直连**。支持代理端解析目标域名，以及用户名/密码认证。

**添加代理**：系统设置 → Agent 连接代理 → 添加代理，分别填写地址（IP 或域名）、端口、用户名、密码（可选）和备注，可保存多条并逐条显示。“检测”按钮由主控经该代理访问自己的公开地址，用于验证代理在线和账号密码。用户名、密码可含任意字符，会自动编码；密码加密保存，不回显。

**安装时选择代理**：添加服务器时在“连接方式”中选择一条代理，生成的一键命令已包含代理，直接在 VPS 上执行，无需额外准备文件。代理经管道传给 curl 和安装器，不会出现在进程参数中；命令本身含代理凭据，请勿公开分享。

**更换已安装 Agent 的代理**（例如原代理失效）：代理失效后 Agent 连不上主控，面板无法远程下发新设置，需要在 VPS 上执行一条命令。打开服务器详情 → 管理 → 更换 Agent 代理，选择新代理或“直连主控”，生成命令后 SSH 登录该 VPS 以 root 执行。命令会经新线路下载最新 Agent，**先测试能否连上主控，失败则原配置和运行中的 Agent 都不变**，成功后切换并重启服务；注册身份和统计数据保留。Agent 会上报所用代理的地址（不含账号密码），面板据此在列表中显示代理名称。

也可以在 VPS 上手动修改：

```bash
printf '%s\n' 'socks5h://用户名:密码@代理主机:1080' | sudo python3 /opt/traffic-sentinel/current/run-agent.py configure --data /var/lib/traffic-sentinel --proxy-stdin
# 改回直连：把 --proxy-stdin 换成 --direct（不需要前面的 printf）
sudo chown -R sentinel-agent:sentinel-agent /var/lib/traffic-sentinel && sudo systemctl restart sentinel-agent
```

Windows：在安装窗口选择 SOCKS5，注册命令会交互询问代理 URL。现有节点可以本地修改：

```powershell
.\.venv\Scripts\python.exe -m sentinel.agent configure --data "agent-data/节点ID" --proxy
# 改回直连
.\.venv\Scripts\python.exe -m sentinel.agent configure --data "agent-data/节点ID" --direct
# 修改后停止原采集进程，再执行网页中的 run 命令
```

代理格式：`socks5h://用户名:密码@代理主机:1080`；密码中的 `@`、`/`、`#` 等应百分号编码。不要把含凭据的命令发到聊天中。“通知设置”中的主控出站代理只用于主控访问 Telegram，与 Agent 代理互不影响。代理配置只用于 Agent 的管理连接，不代理整台 VPS 的业务流量。

远程 VPS 不能连接 Windows 主控的 `127.0.0.1`。第一阶段先用本机 Agent 验证；远程部署时设置实际可达的 HTTPS 主控地址。禁止入站 80/443 不影响 Agent 主动上报；若出站受限，代理地址和端口仍须可达。

## 数据与备份

| 位置 | 内容 |
| --- | --- |
| `data/sentinel.db` | 主控 SQLite 数据库 |
| `data/master.key` | Telegram 配置加密主密钥，必须随数据库备份 |
| `data/backups/` | 每日数据库快照，保留最近 7 份；此目录不单独包含主密钥 |
| `agent-data/<节点ID>/` | Windows Agent 配置、凭据、持久化计数和补报队列 |
| `/var/lib/traffic-sentinel/` | Linux Agent 状态目录 |

“系统设置 → 导出备份”下载包含数据库及主密钥的 ZIP，视为敏感文件妥善保存。不要仅复制运行中的 `.db` 主文件，WAL 中可能还有未合并的数据。迁移优先使用导出备份；详细恢复步骤见 `DEPLOY.md`。

原始采样至少保留 30 天，并保护当前计费周期和有效校准锚点；旧数据按小时聚合保留 730 天。已确认 Agent 记录保留 7 天，超过此时间的主控恢复缺口可能需要人工校准。

## 项目与验证

- `sentinel/`：FastAPI、SQLite、计账、Agent、Telegram 调度。
- `frontend/`：Vue 3 / TypeScript 界面。
- `scripts/`：本地启动、Agent 打包、Linux 安装、源码发布打包。
- `tests/`：计账、协议、代理、通知、归档测试。
- `DEPLOY.md`：Debian Docker 部署、Agent 升级、备份恢复。
- `TESTING.md`：已通过的测试与仍需实机验证的项目。

本版提供监控与提醒；自动限速、关机、执行远程命令、商家后台抓取、多管理员和自动 Agent 更新尚未实现。最新界面调整已通过类型检查及构建，因浏览器重跑未获批准，最终界面尚未重新做完整浏览器验收。
