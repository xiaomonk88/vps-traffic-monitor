# 本地验证记录

日期：2026-11-03。环境：Windows、Python 3.14、Node.js 24.22.1。Windows 本机 Docker 不可用；已通过 GitHub Linux 运行器完成 amd64 镜像与容器验证。

## 已通过

| 检查 | 结果与范围 |
| --- | --- |
| `python -m pytest` | 31 passed；覆盖重启累计、计数倒退、去重、缺序与事务回滚、周期边界、校准检查点冻结、鉴权、CSRF、撤销、通知、归档 |
| `python -m pip check` | 无依赖冲突 |
| `npm run build` | Vue TypeScript 检查及 Vite 生产构建通过，含最终界面代码修改 |
| `scripts/build_agent.py` | 生成约 564 KB 的 Agent ZIP 与 SHA-256 清单 |
| `scripts/check_agent_bundle.py` | 校验散列、解压，在 Python `-S` 下验证内置依赖可导入及 CLI；不等同 Linux 实机运行 |
| Git Bash `bash -n` | 安装、卸载脚本语法通过；不等同 systemd 安装验证 |
| 本地正式入口 8080 | 已用最新后端启动；健康、初始化状态、前端 HTML、安装脚本、Agent ZIP 均返回 200；下载包 SHA-256 与本地清单一致 |
| 源码发布 ZIP | 检查源码包文件白名单，不包含运行数据、主密钥、虚拟环境或 node_modules |
| 第一轮真实浏览器流程 | Edge/Playwright 完成初始化登录、创建节点、Windows Agent 实际采集、检查点、计费设置、余额校准、失败保留输入、刷新读回、手机无横向溢出；无控制台错误 |
| SOCKS5 实际套接字测试 | 本地认证代理收到目标域名和含特殊字符的密码；不可本机解析的测试域名交给代理；不需要公网 SOCKS 服务 |

关键计账场景：校准余额 563 GB，计费 10 GB，重启后再计 2 GB，得到 551 GB。月底 31 日规则在短月取末日，之后月份恢复 31 日。迟到数据分配到原周期，未校准节点不会凭空获得完整余额。

测试使用一个 Starlette 关于 TestClient/httpx 的弃用提示，当前不影响结果。HTTPX 到 Telegram 的 429、重试、消息拆分为受控测试，没有向真实 Telegram 发送消息。

## 界面评审与边界

采用白色内容区、深色侧栏和青绿色操作按钮，额度账目按服务器排成行，便于同时扫视多台节点。做过三个方向比较、一次独立 UX 走查和一次独立视觉评审。稳定旧版视觉评分为 7/10。

评审后调整：详情每 15 秒刷新并保留未保存输入；小流量显示 B/KB/MB；离线与异常行增加色彩提示；消除页签纵向溢出；图表提供可点击日期与下拉读数；删去重复标题、面包屑和手机端冗余说明。交互采用短淡入、按钮反馈和等待旋转图标，遵循减少动画偏好。

**修正后的浏览器重跑执行请求被拒绝，因此最终版只完成类型检查与构建，尚未重新验收实际画面、点击路径和 200% 缩放。** 第一轮截图部分处于动画或加载阶段，独立评审使用稳定旧版截图；旧脚本 CSS zoom 不能算有效 200% 验收，已经调整脚本但未重跑。未把这些证据说成最终视觉通过。

开发过程证据位于本机 `.oil-ui/traffic-monitor/shots/implemented` 和 `.oil-ui/traffic-monitor/logs`（包括 `ux-review-report.md`、`visual-review.md`）；不纳入正式发布 ZIP。`scripts/browser_smoke.py` 会重建专用 8081 测试库的测试节点并启动本机 Agent，不能指向正式环境使用。

## GitHub 发布新增验证

新增主控一键安装器的参数校验测试，覆盖缺失参数、无效域名、换行注入和非法版本；Windows 本地合计 31 项测试通过。安装器及 Agent 脚本通过 bash 语法检查。GitHub Actions 配置 Python 3.11/3.13 Linux 测试、Docker 镜像构建、非 root 数据卷写入、重启持久化与下载包检查；远程执行全部通过：GitHub Actions 运行 41502822643（代码提交 3be7459）。验证了 Debian 13 安装器只读预检、Compose 配置、Caddy 配置、完整 Docker 构建、非 root 容器启动、Agent 下载包散列及重启后数据卷密钥保持一致。首轮容器测试因重启后临时端口改变而失败，修正测试脚本后通过。

验证记录：https://github.com/xiaomonk88/vps-traffic-monitor/actions/runs/41502822643

## 仍需验证

1. 最终版浏览器功能与视觉复验。
2. 用户 Debian 13 VPS 上的完整一键安装、真实域名 TLS 与公网连通；amd64 容器和数据卷持久化已由 CI 验证，arm64 尚未验证。
3. Linux Python/systemd 安装、升级、真实机器重启。
4. 外部真实 SOCKS5 服务、受限 VPS 网络路径。
5. 用户自己的 Telegram Bot 测试和定时实际投递。
6. 主控迁移、Docker 环境备份恢复和跨平台依赖安装。

没有真实商家 API，因此无法验证商家的实际计费口径；这里只能保证本地规则下的估算逻辑。

## 复现命令

在项目根目录，开发依赖安装一次后执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/build_agent.py
.\.venv\Scripts\python.exe scripts/check_agent_bundle.py
```

在 `frontend` 目录执行 `npm.cmd run build`。完整浏览器复验应在获得重新运行授权后，先启动隔离的 8081 测试主控，再运行 `scripts/browser_smoke.py`；该测试不发送 Telegram。

## v0.1.1 Agent 权限回归

用户实际 Linux 节点在 v0.1.0 注册后因程序父目录为 700 而启动失败，日志确认 `Permission denied`。调整两级程序目录为 755 并重启服务后，用户确认主控已显示在线。配置和采集数据没有删除或重新注册。

修复版在注册前以服务账号验证程序可运行，新建和升级都明确设置程序父目录权限。GitHub Actions 41505132383（代码提交 33783ec）全部通过。新增隔离 Linux 容器验证直接执行实际安装器，使用真实服务账号完成注册后的采集与上报，检查配置仍为私有权限，并重建旧版 700 父目录后验证升级自动修复。该容器测试替换了 systemctl，不能等同完整 systemd 生命周期验收；用户真实节点恢复在线补充了现场证据。

CI：https://github.com/xiaomonk88/vps-traffic-monitor/actions/runs/41505132383
