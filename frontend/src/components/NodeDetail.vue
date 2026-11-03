<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { RefreshCw, Settings2, SlidersHorizontal, Clock3, Trash2, ShieldOff, Server, ArrowDown, ArrowUp, Network, Terminal, Copy, Check } from 'lucide-vue-next'
import ModalShell from './ModalShell.vue'
import TrafficChart from './TrafficChart.vue'
import { api, bytes, trafficBytes, dateTime, directions, errorText, statusLabels, units, type Node } from '../api'
const props = defineProps<{ id: string }>(); const emit = defineEmits<{ close: []; changed: []; install: [node: { id: string; name: string }] }>()
const node = ref<Node | null>(null), tab = ref('overview'), error = ref(''), success = ref(''), busy = ref(false), loading = ref(true)
const profile = reactive({ quota: '' as string | number, unit: 'GB', direction: '', timezone: 'Asia/Shanghai', next_reset: '', reset_day: 1, reset_time: '00:00' })
const edit = reactive({ name: '', group_name: '', note: '' })
const remaining = ref<string | number>(''), calibrationNote = ref(''), checkpointId = ref(''), waiting = ref(false), checkpointAt = ref(0), confirmAction = ref(''), confirmation = ref('')
let poll: ReturnType<typeof setTimeout> | undefined; let refreshTimer: ReturnType<typeof setInterval> | undefined; let active = true; let refreshing = false; const deadline = ref(0)
const unit = computed(() => node.value?.profile?.unit || 'GB')
async function load(fill = false) { if (refreshing || !active) return; refreshing = true; try { const result = await api<Node>(`/nodes/${props.id}`); if (!active) return; node.value = result; if (fill) { Object.assign(edit, { name: result.name, group_name: result.group_name, note: result.note }); if (result.profile) Object.assign(profile, result.profile, { quota: result.profile.quota_bytes / units[result.profile.unit], next_reset: result.profile.next_reset.slice(0,16) }) } } catch (e) { error.value = errorText(e) } finally { loading.value = false; refreshing = false } }
async function action(work: () => Promise<void>, message = '') { busy.value = true; error.value = ''; success.value = ''; try { await work(); success.value = message; await load(); emit('changed') } catch (e) { error.value = errorText(e) } finally { busy.value = false } }
function resetFields() { if (profile.next_reset) { profile.reset_day = Number(profile.next_reset.slice(8,10)); profile.reset_time = profile.next_reset.slice(11,16) } }
async function saveProfile() { await action(async () => { await api(`/nodes/${props.id}/billing`, 'PUT', { quota_bytes: Math.round(Number(profile.quota) * units[profile.unit]), unit: profile.unit, direction: profile.direction, timezone: profile.timezone, next_reset: profile.next_reset, reset_day: Number(profile.reset_day), reset_time: profile.reset_time }); checkpointId.value = ''; checkpointAt.value = 0 }, '计费规则已保存。请在“余额校准”中校准当前余额。') }
async function getCheckpoint() { waiting.value = true; error.value = ''; success.value = ''; checkpointAt.value = 0; try { const response = await api(`/nodes/${props.id}/checkpoint`, 'POST'); checkpointId.value = response.id; deadline.value = Date.now() + 120000; await checkPoint() } catch (e) { error.value = errorText(e); waiting.value = false } }
async function checkPoint() { if (!active) return; try { const data = await api<Node>(`/nodes/${props.id}`); node.value = data; if (data.checkpoint?.id === checkpointId.value) { checkpointAt.value = data.checkpoint.at; waiting.value = false; return }; if (Date.now() >= deadline.value) { waiting.value = false; error.value = '等待采集检查点超时。请确认 Agent 正在运行，再重试。'; return }; poll = setTimeout(checkPoint, 2000) } catch (e) { waiting.value = false; error.value = errorText(e) } }
async function calibrate() { await action(async () => { await api(`/nodes/${props.id}/calibrate`, 'POST', { checkpoint_id: checkpointId.value, remaining_bytes: Math.round(Number(remaining.value) * units[unit.value]), note: calibrationNote.value }); checkpointId.value = ''; checkpointAt.value = 0; remaining.value = ''; calibrationNote.value = '' }, '余额已校准，之后只扣除检查点以后的新增流量。') }
async function danger() { await action(async () => { if (confirmAction.value === 'delete') { await api(`/nodes/${props.id}`, 'DELETE'); emit('close') } else { await api(`/nodes/${props.id}/revoke`, 'POST'); confirmAction.value = ''; confirmation.value = '' } }, '节点凭据已撤销。') }
onMounted(async () => { await load(true); if (active) refreshTimer = setInterval(() => { if (!busy.value && !waiting.value) load() }, 15000) }); onBeforeUnmount(() => { active = false; if (poll) clearTimeout(poll); if (refreshTimer) clearInterval(refreshTimer) })

// Switching the proxy of an installed Agent. A dead proxy means the Agent cannot reach the
// panel, so the change is a command the user runs on the VPS (the installer tests it first).
const switchOptions = ref<{ id: string; label: string }[]>([]), switchTarget = ref(''), switchResult = ref<any>(null), switchCopied = ref(false), switchLoaded = ref(false)
const currentConnection = computed(() => { const meta = node.value?.meta || {}; return meta.connection === 'socks5' ? `SOCKS5 · ${node.value?.proxy_name || meta.proxy_endpoint || '未知代理（旧版 Agent 未上报代理地址）'}` : '直连主控' })
const switchCommand = computed(() => switchResult.value ? (node.value?.meta.os === 'Windows' ? switchResult.value.windows_command : switchResult.value.linux_command) : '')
async function loadSwitchOptions() { try { switchOptions.value = (await api('/agent-proxies')).proxies.map((p: any) => ({ id: p.id, label: `${p.note || '未命名代理'}（${p.endpoint}）` })); switchLoaded.value = true } catch (e) { error.value = errorText(e) } }
async function makeSwitch() { error.value = ''; switchResult.value = null; try { switchResult.value = await api(`/nodes/${props.id}/switch-proxy`, 'POST', { proxy_id: switchTarget.value }) } catch (e) { error.value = errorText(e) } }
async function copySwitch() { try { await navigator.clipboard.writeText(switchCommand.value); switchCopied.value = true; setTimeout(() => switchCopied.value = false, 1800) } catch { error.value = '浏览器不允许复制，请选中命令后手动复制。' } }
watch(tab, value => { if (value === 'manage' && !switchLoaded.value) loadSwitchOptions() })
watch(switchTarget, () => { switchResult.value = null })
</script>

<template>
  <ModalShell :title="node?.name || '服务器详情'" drawer @close="emit('close')">
    <div v-if="loading" class="loading">正在读取服务器…</div>
    <template v-if="node">
      <div class="detail-top">
        <span class="status" :class="node.status">{{ statusLabels[node.status] }}</span>
        <span class="detail-meta"><Server :size="14" />{{ node.meta.interface || '尚无网卡信息' }} · {{ node.meta.connection === 'socks5' ? 'SOCKS5' : '直连' }}</span>
        <button class="icon-button bordered" aria-label="刷新服务器详情" title="刷新" @click="load()"><RefreshCw :size="16" /></button>
      </div>

      <nav class="tabs" aria-label="服务器详情分区">
        <button :class="{ active: tab==='overview' }" @click="tab='overview'">流量概况</button>
        <button :class="{ active: tab==='billing' }" @click="tab='billing'">计费设置</button>
        <button :class="{ active: tab==='calibrate' }" @click="tab='calibrate'">余额校准</button>
        <button :class="{ active: tab==='manage' }" @click="tab='manage'">管理</button>
      </nav>

      <div v-if="error" class="alert error" role="alert">{{ error }}</div>
      <div v-if="success" class="alert success" role="status">{{ success }}</div>

      <div v-if="tab==='overview'" class="stack">
        <div class="balance-hero">
          <div class="balance-main">
            <span class="eyebrow">预计剩余流量</span>
            <div class="balance-number">{{ bytes(node.remaining,unit) }}</div>
            <div v-if="node.profile" class="muted">总额度 {{ bytes(node.profile.quota_bytes,unit) }} · {{ directions[node.profile.direction] }}</div>
            <div v-else class="muted">先配置计费规则，再校准商家余额。</div>
          </div>
          <div v-if="node.percent!=null" class="balance-ratio">
            <strong>{{ Math.max(0,100-node.percent).toFixed(1) }}%</strong>
            <span>剩余比例</span>
          </div>
          <div v-if="node.percent!=null" class="bar"><i :style="{ width: `${Math.max(0,Math.min(100,100-node.percent))}%` }" :class="{ warn: node.percent>=80 }"></i></div>
        </div>

        <div v-if="!node.fresh && node.enrolled" class="alert warn">数据尚未更新或补报未完成，预计余额可能偏高。最后采集：{{ dateTime(node.last_data) }}</div>
        <div v-if="node.meta.error" class="alert error">{{ node.meta.error }}</div>

        <div class="detail-stats">
          <div><span><ArrowUp :size="14" />今日上传</span><strong>{{ trafficBytes(node.today.tx,unit) }}</strong></div>
          <div><span><ArrowDown :size="14" />今日下载</span><strong>{{ trafficBytes(node.today.rx,unit) }}</strong></div>
          <div><span><Clock3 :size="14" />下次重置</span><strong class="date-value">{{ dateTime(node.cycle_end,node.profile?.timezone) }}</strong></div>
        </div>

        <section class="card-section">
          <div class="section-heading"><h3>流量趋势</h3><span class="muted">上传 / 下载</span></div>
          <TrafficChart :data="node.history || []" :unit="unit" />
        </section>

        <div v-if="node.forecast_days!=null" class="alert" :class="node.exhaustion_risk ? 'warn' : 'info'">按近期流量预计还能使用 {{ node.forecast_days }} 天{{ node.exhaustion_risk ? '，可能在重置前耗尽。' : '。' }}</div>

        <section class="card-section">
          <div class="section-heading"><h3>节点信息</h3></div>
          <dl class="metadata">
            <div><dt>最后上报</dt><dd>{{ dateTime(node.heartbeat) }}</dd></div>
            <div><dt>主机名</dt><dd>{{ node.meta.hostname || '—' }}</dd></div>
            <div><dt>系统 / Agent</dt><dd>{{ node.meta.os || '—' }} / {{ node.meta.version || '—' }}</dd></div>
            <div><dt>待补报记录</dt><dd>{{ node.meta.queue || 0 }}</dd></div>
            <div class="full"><dt>备注</dt><dd>{{ node.note || '—' }}</dd></div>
          </dl>
        </section>

        <button v-if="!node.enrolled || node.disabled" class="primary" @click="emit('install',{ id:node.id,name:node.name })">生成安装命令</button>
      </div>

      <form v-if="tab==='billing'" class="stack" @submit.prevent="saveProfile">
        <p class="muted">按商家套餐填写。修改规则后，请重新校准当前剩余额度。</p>
        <div class="form-grid">
          <label>每周期总额度<input v-model="profile.quota" required type="number" min="0.001" step="any" placeholder="填写套餐额度" /></label>
          <label>流量单位<select v-model="profile.unit"><option v-for="(_,key) in units" :key="key">{{ key }}</option></select></label>
        </div>
        <label>计费方向<select v-model="profile.direction" required><option disabled value="">请选择商家实际计费方向</option><option value="tx">上传（出站 TX）</option><option value="rx">下载（入站 RX）</option><option value="sum">上传 + 下载</option></select><small>商家写“单向”时，需确认具体方向。</small></label>
        <label>下次重置日期与时间<input v-model="profile.next_reset" required type="datetime-local" @change="resetFields" /></label>
        <div class="form-grid">
          <label>之后每月几号<input v-model="profile.reset_day" required type="number" min="1" max="31" /></label>
          <label>重置时刻<input v-model="profile.reset_time" required type="time" /></label>
        </div>
        <label>商家计费时区<input v-model="profile.timezone" required list="timezones" placeholder="Asia/Shanghai" /><small>重置时间属于此时区。月底不存在的日期按当月最后一天处理。</small></label>
        <div class="form-actions"><button class="primary" :disabled="busy"><Settings2 :size="16" />{{ busy ? '正在保存…' : '保存计费规则' }}</button></div>
      </form>

      <div v-if="tab==='calibrate'" class="stack">
        <div v-if="!node.profile" class="empty compact">
          <div class="empty-icon"><SlidersHorizontal :size="26" /></div>
          <h3>先设置计费规则</h3>
          <p>总额度和计费方向用于换算商家余额。</p>
          <button class="primary" @click="tab='billing'">前往计费设置</button>
        </div>
        <template v-else>
          <p class="muted">刷新商家后台后输入剩余流量。每次校准只调整余额，历史采集记录保持不变。</p>
          <div class="checkpoint-box">
            <div><strong>1. 获取最新采集检查点</strong><p class="hint">Agent 默认每 60 秒上报，最长等待 120 秒。</p></div>
            <button class="secondary" :disabled="waiting || busy" @click="getCheckpoint"><RefreshCw :size="15" :class="{ spinning: waiting }" />{{ waiting ? '等待 Agent 上报…' : checkpointAt ? '重新获取' : '获取检查点' }}</button>
          </div>
          <div v-if="checkpointAt" class="alert success">检查点就绪：{{ dateTime(checkpointAt) }}。请在 2 分钟内提交余额。</div>
          <form class="stack" @submit.prevent="calibrate">
            <label>2. 商家当前剩余流量（{{ unit }}）<input v-model="remaining" required type="number" min="0" step="any" placeholder="输入商家后台显示的余额" /></label>
            <label>校准备注（可选）<input v-model="calibrationNote" maxlength="300" placeholder="例如：首次接入" /></label>
            <div class="form-actions"><button class="primary" :disabled="busy || waiting || !checkpointAt">{{ busy ? '正在校准…' : '保存校准余额' }}</button></div>
          </form>
          <section class="calibration-history">
            <h3>校准历史</h3>
            <p v-if="!node.calibrations?.length" class="muted">还没有校准记录。</p>
            <div v-for="record in node.calibrations" :key="record.id" class="history-item">
              <div><strong>{{ bytes(record.remaining,unit) }}</strong><span class="muted">{{ dateTime(record.created) }}</span></div>
              <p class="hint">{{ record.note || '人工校准' }}<template v-if="record.previous!=null"> · 原预计余额 {{ bytes(record.previous,unit) }}</template></p>
            </div>
          </section>
        </template>
      </div>

      <div v-if="tab==='manage'" class="stack">
        <form class="stack" @submit.prevent="action(async()=>{ await api(`/nodes/${id}`,'PUT',edit) },'服务器信息已保存。')">
          <label>名称<input v-model="edit.name" required maxlength="80" /></label>
          <div class="form-grid">
            <label>分组<input v-model="edit.group_name" maxlength="80" /></label>
            <label>备注<input v-model="edit.note" maxlength="500" /></label>
          </div>
          <div class="form-actions"><button class="secondary" :disabled="busy">保存服务器信息</button></div>
        </form>
        <section v-if="node.enrolled && !node.disabled" class="card-section switch-proxy">
          <div class="section-heading"><h3><Network :size="16" />更换 Agent 代理</h3><span class="muted">当前：{{ currentConnection }}</span></div>
          <p class="hint">代理失效时 Agent 无法连上主控，面板无法远程下发新设置，需要 SSH 登录这台 VPS 执行下方命令。命令会经新线路下载最新 Agent，<strong>先测试能否连上主控，失败则保持原配置不变</strong>，成功后切换并重启服务；统计数据和注册身份保留。</p>
          <div class="switch-row">
            <label>新的连接方式
              <select v-model="switchTarget">
                <option value="">直连主控</option>
                <option v-for="item in switchOptions" :key="item.id" :value="item.id">SOCKS5 · {{ item.label }}</option>
              </select>
            </label>
            <button type="button" class="secondary" @click="makeSwitch">生成更换命令</button>
          </div>
          <p v-if="switchLoaded && !switchOptions.length" class="hint">还没有保存代理，可在“系统设置 → Agent 连接代理”添加。</p>
          <template v-if="switchResult">
            <div class="code-block">
              <div class="code-title"><span><Terminal :size="15" />在这台 VPS 上以 root 执行 · 切换为 {{ switchResult.target }}</span><button class="text-button" @click="copySwitch"><component :is="switchCopied ? Check : Copy" :size="15" />{{ switchCopied ? '已复制' : '复制命令' }}</button></div>
              <pre tabindex="0">{{ switchCommand }}</pre>
            </div>
            <p class="hint"><template v-if="node.meta.os === 'Windows'">在项目根目录的 PowerShell 执行，然后关闭并重新运行采集命令。</template>执行后约 1 分钟，此处“当前”会显示新的连接方式。<template v-if="switchTarget">命令包含代理账号密码，请勿公开分享。</template></p>
          </template>
        </section>

        <section class="danger-zone">
          <h3>节点凭据与数据</h3>
          <p class="muted">撤销凭据会阻止旧 Agent 上报，历史记录保留。删除服务器会同时删除其统计与校准记录。</p>
          <div class="actions">
            <button v-if="node.enrolled && !node.disabled" class="secondary danger" @click="confirmAction='revoke'; confirmation=''"><ShieldOff :size="16" />撤销凭据</button>
            <button v-else class="secondary" @click="emit('install',{id:node.id,name:node.name})">生成安装命令</button>
            <button class="secondary danger" @click="confirmAction='delete'; confirmation=''"><Trash2 :size="16" />删除服务器</button>
          </div>
          <form v-if="confirmAction" class="stack confirmation" @submit.prevent="danger">
            <label>输入服务器名称“{{ node.name }}”以确认{{ confirmAction==='delete' ? '删除' : '撤销' }}<input v-model="confirmation" autocomplete="off" /></label>
            <div class="actions"><button type="button" class="secondary" @click="confirmAction=''">取消</button><button class="danger-solid" :disabled="confirmation!==node.name || busy">确认{{ confirmAction==='delete' ? '删除' : '撤销' }}</button></div>
          </form>
        </section>
      </div>
    </template>
  </ModalShell>
</template>
