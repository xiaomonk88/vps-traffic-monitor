<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Activity, LayoutDashboard, Bell, ScrollText, Settings, LogOut, Plus, Search, RefreshCw, Server, ChevronRight, CircleAlert, Send, ArrowUpFromLine, TriangleAlert } from 'lucide-vue-next'
import AuthPanel from './components/AuthPanel.vue'
import AddNodeModal from './components/AddNodeModal.vue'
import NodeDetail from './components/NodeDetail.vue'
import SettingsView from './components/SettingsView.vue'
import EventsView from './components/EventsView.vue'
import { api, APIError, ago, bytes, trafficBytes, directions, errorText, metered, setCSRF, shortDate, statusLabels, type Node } from './api'
const ready=ref(false),initialized=ref(true),username=ref(''),version=ref(''),fatal=ref(''),error=ref(''),page=ref('overview'),nodes=ref<Node[]>([]),busy=ref(false),lastRefresh=ref(0),zone=ref('Asia/Shanghai'),search=ref(''),filter=ref('all'),adding=ref(false),installNode=ref<{id:string;name:string}|undefined>(),detailId=ref(''),telegram=ref({enabled:false,time:'09:00',zone:'Asia/Shanghai',channels:0})
let timer:ReturnType<typeof setInterval> | undefined
const pages=[{id:'overview',name:'流量总览',icon:LayoutDashboard,desc:'集中查看各服务器的剩余额度、计费用量、重置周期与运行状态。'},{id:'notifications',name:'通知设置',icon:Bell,desc:'配置 Telegram 连接、每日报告与即时告警规则。'},{id:'events',name:'事件记录',icon:ScrollText,desc:'追溯系统事件与通知发送结果。'},{id:'system',name:'系统设置',icon:Settings,desc:'管理主控访问地址、数据备份与管理员账户。'}]
const current=computed(()=>pages.find(v=>v.id===page.value) || pages[0])
const title=computed(()=>current.value.name)
const priority:Record<string,number>={error:0,warning:1,offline:2,syncing:3,uncalibrated:4,pending:5,disabled:6,online:7}
const filtered=computed(()=>nodes.value.filter(n=>(filter.value==='all' || (filter.value==='attention'?['warning','error','offline'].includes(n.status):n.status===filter.value)) && `${n.name} ${n.group_name} ${n.note}`.toLowerCase().includes(search.value.toLowerCase())).sort((a,b)=>(priority[a.status]??9)-(priority[b.status]??9)||a.name.localeCompare(b.name,'zh-CN')))
const online=computed(()=>nodes.value.filter(n=>n.online&&!n.disabled).length),attention=computed(()=>nodes.value.filter(n=>['warning','error','offline'].includes(n.status)).length),yesterday=computed(()=>nodes.value.reduce((sum,n)=>sum+n.yesterday.tx,0))
const yesterdayParts=computed(()=>trafficBytes(yesterday.value).split(' '))
const refreshedAt=computed(()=>lastRefresh.value?new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(lastRefresh.value*1000)):'—')
async function init(){fatal.value='';ready.value=false;try{const status=await api('/status');initialized.value=status.initialized;version.value=status.version;if(status.initialized){try{const me=await api('/me');setCSRF(me.csrf);username.value=me.username;await refresh();await loadTelegram()}catch(e){if(!(e instanceof APIError && e.status===401))throw e}}}catch(e){fatal.value=errorText(e)}finally{ready.value=true}}
async function refresh(){if(busy.value||!username.value)return;busy.value=true;try{const data=await api<{nodes:Node[];timezone:string}>('/nodes');nodes.value=data.nodes;zone.value=data.timezone;lastRefresh.value=Date.now()/1000;error.value=''}catch(e){error.value=errorText(e)}finally{busy.value=false}}
async function loadTelegram(){try{const data=await api('/settings');telegram.value={enabled:data.telegram_enabled,time:data.daily_time,zone:data.timezone,channels:data.channels.filter((c:{enabled:boolean})=>c.enabled).length}}catch{/* Settings page surfaces its own error. */}}
async function authenticated(name:string){username.value=name;initialized.value=true;await refresh();await loadTelegram()}
async function logout(){try{await api('/logout','POST');expired()}catch(e){error.value=errorText(e)}}
function expired(){username.value='';setCSRF('');nodes.value=[];detailId.value='';adding.value=false;installNode.value=undefined}
function add(){installNode.value=undefined;adding.value=true}
function showInstall(node:{id:string;name:string}){detailId.value='';installNode.value=node;adding.value=true}
onMounted(()=>{init();window.addEventListener('session-expired',expired);timer=setInterval(()=>{if(page.value==='overview')refresh()},15000)})
onBeforeUnmount(()=>{if(timer)clearInterval(timer);window.removeEventListener('session-expired',expired)})
</script>

<template>
  <div v-if="!ready" class="app-loading">
    <span class="loading-mark"><Activity :size="26" /></span>
    <span>正在连接流量哨…</span>
  </div>

  <div v-else-if="fatal" class="app-loading">
    <span class="loading-mark danger"><CircleAlert :size="26" /></span>
    <h1>暂时无法连接主控</h1>
    <p>{{ fatal }}</p>
    <button class="primary" @click="init">重新连接</button>
  </div>

  <AuthPanel v-else-if="!username" :setup="!initialized" @authenticated="authenticated" />

  <div v-else class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="#" @click.prevent="page='overview'">
        <span class="brand-mark"><Activity :size="20" /></span>
        <span class="brand-text"><strong>流量哨</strong><small>TRAFFIC SENTINEL</small></span>
      </a>
      <nav class="main-nav" aria-label="主导航">
        <span class="nav-caption">控制台</span>
        <button v-for="item in pages" :key="item.id" :class="{ selected: page===item.id }" :aria-current="page===item.id ? 'page' : undefined" @click="page=item.id">
          <component :is="item.icon" :size="18" />
          <span>{{ item.name }}</span>
          <span v-if="item.id==='overview' && attention" class="nav-count">{{ attention }}</span>
        </button>
      </nav>
      <div class="sidebar-bottom">
        <div class="sidebar-status"><i></i>主控已连接</div>
        <p>本地估算 · 提前提醒</p>
        <span>版本 v{{ version }}</span>
      </div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <div class="breadcrumb"><span>控制台</span><ChevronRight :size="14" /><strong>{{ title }}</strong></div>
        <div class="account">
          <span class="avatar" aria-hidden="true">{{ username.slice(0,1).toUpperCase() }}</span>
          <span class="account-name">{{ username }}</span>
          <span class="account-divider"></span>
          <button class="icon-button" title="退出登录" aria-label="退出登录" @click="logout"><LogOut :size="17" /></button>
        </div>
      </header>

      <div class="content">
        <div class="page-heading">
          <div>
            <h1>{{ title }}</h1>
            <p>{{ current.desc }}</p>
          </div>
          <button v-if="page==='overview'" class="primary" @click="add"><Plus :size="17" />添加服务器</button>
        </div>

        <div v-if="error" class="alert error" role="alert">{{ error }}</div>

        <div v-if="page==='overview'" class="overview">
          <section class="kpi-grid">
            <div class="kpi">
              <div class="kpi-head"><span>服务器</span><i class="kpi-icon"><Server :size="17" /></i></div>
              <div class="kpi-value">{{ nodes.length }}<small>台</small></div>
              <p><b class="dot positive"></b>{{ online }} 台在线<span class="sep">/</span>{{ nodes.length-online }} 台未在线</p>
            </div>
            <div class="kpi">
              <div class="kpi-head"><span>昨日上传总量</span><i class="kpi-icon"><ArrowUpFromLine :size="17" /></i></div>
              <div class="kpi-value">{{ yesterdayParts[0] }}<small>{{ yesterdayParts[1] }}</small></div>
              <p>{{ zone }} · 按实际采集统计</p>
            </div>
            <div class="kpi" :class="{ alerting: attention }">
              <div class="kpi-head"><span>需要关注</span><i class="kpi-icon"><TriangleAlert :size="17" /></i></div>
              <div class="kpi-value" :class="{ amber: attention }">{{ attention }}<small>台</small></div>
              <p>{{ attention ? '额度偏低、离线或采集异常' : '当前没有额度或离线告警' }}</p>
            </div>
            <button class="kpi kpi-link" @click="page='notifications'">
              <div class="kpi-head"><span>Telegram 日报与告警</span><i class="kpi-icon"><Send :size="16" /></i></div>
              <div class="kpi-value kpi-state"><span class="tag" :class="{ positive: telegram.enabled }">{{ telegram.enabled ? '已启用' : '未启用' }}</span></div>
              <p>{{ telegram.enabled ? `${telegram.channels} 个渠道 · 每天 ${telegram.time} · ${telegram.zone}` : '尚未启用，配置后接收流量与重置提醒。' }}</p>
              <span class="kpi-action">{{ telegram.enabled ? '查看配置' : '配置通知' }}<ChevronRight :size="15" /></span>
            </button>
          </section>

          <section class="panel node-panel">
            <div class="panel-head">
              <h2>服务器列表<span class="count">{{ nodes.length }}</span></h2>
              <div class="list-controls">
                <label class="search-field"><Search :size="15" /><input v-model="search" aria-label="搜索服务器" placeholder="搜索名称或分组" /></label>
                <select v-model="filter" aria-label="筛选服务器状态">
                  <option value="all">全部状态</option>
                  <option value="attention">需要关注</option>
                  <option value="online">在线</option>
                  <option value="pending">待安装</option>
                  <option value="uncalibrated">待校准</option>
                  <option value="offline">离线</option>
                </select>
                <button class="icon-button bordered" aria-label="刷新服务器列表" title="刷新" :disabled="busy" @click="refresh"><RefreshCw :size="16" :class="{ spinning: busy }" /></button>
              </div>
            </div>

            <div v-if="!nodes.length" class="empty node-empty">
              <div class="empty-icon"><Server :size="30" :stroke-width="1.5" /></div>
              <h3>接入第一台服务器</h3>
              <p>运行专属安装命令，再填入商家余额和重置日期。<br>之后自动统计流量，并通过 Telegram 提前提醒。</p>
              <button class="primary" @click="add"><Plus :size="16" />添加服务器</button>
              <span class="hint">支持 Linux VPS，也可在 Windows 上先测试。</span>
            </div>

            <div v-else-if="!filtered.length" class="empty">
              <div class="empty-icon"><Search :size="26" /></div>
              <h3>没有匹配的服务器</h3>
              <button class="text-button" @click="search='';filter='all'">清除筛选</button>
            </div>

            <div v-else class="node-table">
              <div class="node-table-head"><span>服务器</span><span>预计剩余 / 总额度</span><span>昨日计费量</span><span>下次重置</span><span>状态</span><span></span></div>
              <button v-for="node in filtered" :key="node.id" class="node-row" :class="{ risk: node.status==='warning', unavailable: ['offline','error'].includes(node.status) }" @click="detailId=node.id">
                <div class="node-identity">
                  <span class="node-symbol"><Server :size="18" :stroke-width="1.6" /></span>
                  <div>
                    <strong>{{ node.name }}</strong>
                    <span class="node-sub">{{ node.group_name || (node.profile ? directions[node.profile.direction] : '计费待配置') }} · {{ node.meta.connection==='socks5' ? 'SOCKS5' : '直连' }}</span>
                  </div>
                </div>
                <div class="balance-cell">
                  <span v-if="node.remaining!=null" class="node-balance" :class="{ amber: node.status==='warning' }">{{ bytes(node.remaining,node.profile?.unit).split(' ')[0] }} <small>/ {{ node.profile ? bytes(node.profile.quota_bytes,node.profile.unit) : '—' }}</small></span>
                  <span v-else class="muted">{{ node.profile ? '等待校准余额' : '尚未设置额度' }}</span>
                  <div v-if="node.percent!=null" class="bar"><i :class="{ warn: node.percent>=80, stale: !node.fresh }" :style="{ width: `${Math.max(0,Math.min(100,100-node.percent))}%` }"></i></div>
                  <span class="node-sub" :class="{ amber: node.exhaustion_risk }">{{ node.exhaustion_risk ? '预计无法撑到重置日' : node.enrolled && !node.fresh ? '数据过期或补报中' : node.percent!=null ? `剩余 ${Math.max(0,100-node.percent).toFixed(1)}%` : '点击配置与校准' }}</span>
                </div>
                <div class="yesterday-cell">
                  <span class="mobile-label">昨日计费量</span>
                  <strong>{{ node.profile ? trafficBytes(metered(node,node.yesterday),node.profile.unit) : '—' }}</strong>
                  <span v-if="node.enrolled && node.yesterday.coverage<.95" class="node-sub">采集未覆盖全天</span>
                </div>
                <div class="reset-cell">
                  <span class="mobile-label">下次重置</span>
                  <strong>{{ shortDate(node.cycle_end,node.profile?.timezone) }}</strong>
                  <span v-if="node.profile" class="node-sub">每月 {{ node.profile.reset_day }} 日</span>
                </div>
                <div class="state-cell">
                  <span class="status" :class="node.status">{{ statusLabels[node.status] }}</span>
                  <span class="node-sub">{{ ago(node.heartbeat) }}</span>
                </div>
                <ChevronRight class="row-chevron" :size="16" />
              </button>
            </div>

            <div class="panel-foot">
              <span>风险优先排序 · 每 15 秒刷新</span>
              <span>最后刷新 {{ refreshedAt }}</span>
            </div>
          </section>
        </div>

        <SettingsView v-else-if="page==='notifications' || page==='system'" :key="page" :section="page" @saved="loadTelegram" @password-changed="expired" />
        <EventsView v-else-if="page==='events'" />

        <footer class="page-footer">预计余额用于提前提醒，商家实际结算可能存在差异。</footer>
      </div>
    </main>

    <AddNodeModal v-if="adding" :existing="installNode" @close="adding=false;refresh()" @created="refresh" />
    <NodeDetail v-if="detailId" :key="detailId" :id="detailId" @close="detailId=''" @changed="refresh" @install="showInstall" />
  </div>

  <datalist id="timezones">
    <option value="Asia/Shanghai" /><option value="UTC" /><option value="Asia/Hong_Kong" /><option value="Asia/Tokyo" /><option value="America/Los_Angeles" /><option value="America/New_York" /><option value="Europe/Berlin" />
  </datalist>
</template>
