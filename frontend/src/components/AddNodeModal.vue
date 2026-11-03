<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, Copy, Terminal, ArrowRight, ShieldAlert } from 'lucide-vue-next'
import ModalShell from './ModalShell.vue'
import { api, errorText } from '../api'
const props = defineProps<{ existing?: { id: string; name: string } }>()
const emit = defineEmits<{ close: []; created: [id: string] }>()
const name = ref(props.existing?.name || ''), group = ref(''), note = ref(''), busy = ref(false), error = ref(''), createdId = ref(props.existing?.id || '')
const install = ref<any>(null), platform = ref('linux'), proxy = ref(false), copied = ref(false), selectedInterface = ref(''), proxyUrl = ref('')
const localOnly = computed(() => { try { const host=new URL(install.value?.server || '').hostname; return host==='localhost'||host==='[::1]'||host==='0.0.0.0'||/^127\./.test(host) } catch { return false } })
// Same rule as the server's validate_agent_proxy: the URL goes into a shell command and a curl config line.
const proxyPattern = /^socks5h?:\/\/[^\s"\\/]+:\d{1,5}\/?$/i
const shellQuote = (value: string) => `'${value.replaceAll("'", `'\\''`)}'`
const linuxProxy = computed(() => (proxyUrl.value.trim() || install.value?.agent_proxy || '').replace(/^socks5:\/\//i, 'socks5h://'))
const proxyInvalid = computed(() => !!proxyUrl.value.trim() && !proxyPattern.test(proxyUrl.value.trim()))
const proxyMissing = computed(() => platform.value === 'linux' && proxy.value && (!linuxProxy.value || proxyInvalid.value))
const command = computed(() => {
  if (!install.value) return ''
  if (platform.value === 'windows') return install.value.windows_command + (selectedInterface.value.trim() ? ` --interface '${selectedInterface.value.trim().replaceAll("'", "''")}'` : '') + (proxy.value ? ' --proxy' : '')
  if (!proxy.value) return install.value.linux_command
  if (proxyMissing.value) return ''
  // The proxy is piped through printf (a shell builtin), so it never appears in a process argument list.
  const { server, token } = install.value
  return `P=${shellQuote(linuxProxy.value)}; printf 'proxy = "%s"\\n' "$P" | curl -K - --noproxy '' -fsS ${shellQuote(server + '/install.sh')} -o install-sentinel.sh && printf '%s\\n' "$P" | sudo bash install-sentinel.sh --server ${shellQuote(server)} --token ${shellQuote(token)} --proxy-stdin; unset P`
})
const run = computed(() => `.\\.venv\\Scripts\\python.exe -m sentinel.agent run --data "agent-data/${createdId.value}"`)
async function generate() { error.value = ''; busy.value = true; try { if (!createdId.value) { const result = await api('/nodes', 'POST', { name: name.value.trim(), group_name: group.value, note: note.value }); createdId.value = result.id; emit('created', result.id) }; install.value = await api(`/nodes/${createdId.value}/install`, 'POST'); if(localOnly.value) platform.value='windows'; else if(install.value.agent_proxy) proxy.value=true } catch (e) { error.value = errorText(e) } finally { busy.value = false } }
async function copy(value: string) { try { await navigator.clipboard.writeText(value); copied.value = true; setTimeout(() => copied.value = false, 1800) } catch { error.value = '浏览器不允许复制，请选中命令后手动复制。' } }
</script>

<template>
  <ModalShell :title="install ? `安装 Agent · ${name}` : existing ? `重新注册 · ${name}` : '添加服务器'" wide @close="emit('close')">
    <ol class="steps" aria-hidden="true">
      <li :class="install ? 'done' : 'current'"><span>1</span>创建服务器身份</li>
      <li :class="{ current: install }"><span>2</span>在目标机器安装 Agent</li>
      <li><span>3</span>配置计费并校准余额</li>
    </ol>

    <form v-if="!install" class="stack" @submit.prevent="generate">
      <p class="muted">为服务器创建身份，然后在目标机器上运行专属安装命令。</p>
      <label>服务器名称<input v-model="name" required maxlength="80" placeholder="例如：香港 01" :disabled="!!createdId" /></label>
      <div v-if="!existing" class="form-grid">
        <label>分组（可选）<input v-model="group" maxlength="80" placeholder="例如：生产环境" :disabled="!!createdId" /></label>
        <label>备注（可选）<input v-model="note" maxlength="500" placeholder="商家或用途" :disabled="!!createdId" /></label>
      </div>
      <div v-if="error" class="alert error" role="alert">{{ error }}</div>
      <div class="actions modal-actions"><button class="primary" :disabled="busy || !name.trim()">{{ busy ? '正在生成…' : createdId ? '重新生成安装命令' : '创建并生成安装命令' }}<ArrowRight :size="16" /></button></div>
    </form>

    <div v-else class="stack">
      <div class="alert success"><Check :size="17" /><span>注册凭据已生成，30 分钟内有效，仅能使用一次。</span></div>
      <div class="form-grid">
        <label>目标系统<select v-model="platform"><option value="linux">Linux VPS</option><option value="windows">Windows 本地测试</option></select></label>
        <label>连接方式<select v-model="proxy"><option :value="false">直连主控</option><option :value="true">SOCKS5 代理</option></select></label>
      </div>

      <template v-if="platform==='linux' && proxy">
        <label>Agent 连接代理
          <input v-model="proxyUrl" type="password" autocomplete="new-password" :placeholder="install.agent_proxy ? '留空使用系统设置中保存的 Agent 默认代理' : 'socks5h://用户名:密码@代理地址:端口'" />
          <small>VPS 上的 Agent 通过此代理连接主控。地址会直接写入安装命令，无需在 VPS 上额外操作。<template v-if="!install.agent_proxy">可在“系统设置 → Agent 连接代理”保存默认值。</template></small>
        </label>
        <div v-if="proxyInvalid" class="alert error">代理格式应为 socks5h://用户名:密码@地址:端口；用户名或密码中的特殊字符请使用百分号编码。</div>
        <div v-else-if="proxyMissing" class="alert warn">请填写 SOCKS5 代理地址，或先在“系统设置”保存 Agent 默认代理。</div>
        <div v-else class="alert info"><ShieldAlert :size="16" /><span>命令中包含代理凭据，请勿公开分享。代理地址通过管道传给安装器，不会出现在进程列表中。</span></div>
      </template>

      <div v-if="platform==='windows'" class="alert info">在本项目根目录打开 PowerShell。先运行注册命令，再运行下方采集命令；保持采集窗口开启。<template v-if="proxy">注册时会提示输入 SOCKS5 代理地址。</template></div>
      <label v-if="platform==='windows'">统计网卡（可选）<input v-model="selectedInterface" placeholder="例如：以太网，留空自动选择" /><small>可先运行 <code>.\.venv\Scripts\python.exe -m sentinel.agent interfaces</code> 查看名称，支持中文网卡名。</small></label>
      <div v-if="platform==='linux' && localOnly" class="alert warn">当前主控地址仅能从本机访问，不能用于远程 VPS。请先在“系统设置”填写目标机器可达的主控地址，再重新生成安装命令。本地验证请选择“Windows 本地测试”。</div>

      <div v-if="command && (platform==='windows' || !localOnly)" class="code-block">
        <div class="code-title"><span><Terminal :size="15" />{{ platform === 'linux' ? '在目标 VPS 执行' : '1. 注册本地 Agent' }}</span><button class="text-button" @click="copy(command)"><component :is="copied ? Check : Copy" :size="15" />{{ copied ? '已复制' : '复制命令' }}</button></div>
        <pre tabindex="0">{{ command }}</pre>
      </div>
      <div v-if="platform==='windows'" class="code-block">
        <div class="code-title"><span>2. 开始持续采集</span><button class="text-button" @click="copy(run)"><Copy :size="15" />复制命令</button></div>
        <pre tabindex="0">{{ run }}</pre>
      </div>

      <p class="hint">节点上线后，在详情中配置计费规则并校准商家剩余额度。其他机器必须能访问主控地址 <strong>{{ install.server }}</strong>；如需修改，请先到“系统设置”更新公开地址。</p>
      <div v-if="error" class="alert error" role="alert">{{ error }}</div>
      <div class="actions modal-actions"><button class="secondary" :disabled="busy" @click="generate">重新生成凭据</button><button class="primary" @click="emit('close')">返回服务器列表</button></div>
    </div>
  </ModalShell>
</template>
