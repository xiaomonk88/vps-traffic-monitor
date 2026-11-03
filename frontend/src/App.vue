<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Activity, LayoutDashboard, Bell, BellOff, ScrollText, Settings, LogOut, Plus, Search, RefreshCw, Server, ChevronRight, CircleAlert, Send, ArrowUp, ArrowDown, ArrowUpDown, TriangleAlert, Gauge, GripVertical } from 'lucide-vue-next'
import AuthPanel from './components/AuthPanel.vue'
import AddNodeModal from './components/AddNodeModal.vue'
import NodeDetail from './components/NodeDetail.vue'
import SettingsView from './components/SettingsView.vue'
import TrafficRank from './components/TrafficRank.vue'
import EventsView from './components/EventsView.vue'
import { api, APIError, ago, bytes, trafficBytes, directions, errorText, metered, setCSRF, shortDate, statusLabels, timeLeft, type Node } from './api'
const ready=ref(false),initialized=ref(true),username=ref(''),version=ref(''),fatal=ref(''),error=ref(''),page=ref('overview'),nodes=ref<Node[]>([]),busy=ref(false),lastRefresh=ref(0),zone=ref('Asia/Shanghai'),search=ref(''),filter=ref('all'),group=ref('all'),adding=ref(false),installNode=ref<{id:string;name:string}|undefined>(),detailId=ref(''),telegram=ref({enabled:false,time:'09:00',zone:'Asia/Shanghai',channels:0})
let timer:ReturnType<typeof setInterval> | undefined
const pages=[{id:'overview',name:'流量总览',icon:LayoutDashboard,desc:'集中查看各服务器的剩余额度、计费用量、重置周期与运行状态。'},{id:'notifications',name:'通知设置',icon:Bell,desc:'配置 Telegram 连接、每日报告与即时告警规则。'},{id:'events',name:'事件记录',icon:ScrollText,desc:'追溯系统事件与通知发送结果。'},{id:'system',name:'系统设置',icon:Settings,desc:'管理主控访问地址、数据备份与管理员账户。'}]
const current=computed(()=>pages.find(v=>v.id===page.value) || pages[0])
const title=computed(()=>current.value.name)
const priority:Record<string,number>={error:0,warning:1,offline:2,syncing:3,uncalibrated:4,pending:5,disabled:6,online:7}
const inGroup=(n:Node)=>group.value==='all' || (group.value==='__none__' ? !n.group_name : n.group_name===group.value)
// List order: custom (drag-and-drop, saved on the server), risk, name or creation time.
const sortModes:Record<string,string>={custom:'拖拽排序',risk:'风险优先',name:'名称排序',created:'添加时间'}
const sortMode=ref(sortModes[localStorage.getItem('sentinel-sort') || ''] ? localStorage.getItem('sentinel-sort')! : 'custom')
watch(sortMode,value=>localStorage.setItem('sentinel-sort',value))
const byName=(a:Node,b:Node)=>a.name.localeCompare(b.name,'zh-CN',{numeric:true})
const byCustom=(a:Node,b:Node)=>(a.position??1e9)-(b.position??1e9)||a.created-b.created
function compare(a:Node,b:Node){ if(sortMode.value==='risk') return (priority[a.status]??9)-(priority[b.status]??9)||byName(a,b); if(sortMode.value==='name') return byName(a,b); if(sortMode.value==='created') return a.created-b.created||byName(a,b); return byCustom(a,b) }
const filtered=computed(()=>nodes.value.filter(n=>inGroup(n) && (filter.value==='all' || (filter.value==='attention'?['warning','error','offline'].includes(n.status):n.status===filter.value)) && `${n.name} ${n.group_name} ${n.note}`.toLowerCase().includes(search.value.toLowerCase())).sort(compare))
const online=computed(()=>nodes.value.filter(n=>n.online&&!n.disabled).length),attention=computed(()=>nodes.value.filter(n=>['warning','error','offline'].includes(n.status)).length),yesterday=computed(()=>nodes.value.reduce((sum,n)=>sum+n.yesterday.tx,0))
const yesterdayRx=computed(()=>nodes.value.reduce((sum,n)=>sum+n.yesterday.rx,0))
const groups=computed(()=>[...new Set(nodes.value.map(n=>n.group_name).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN')))
const ungrouped=computed(()=>nodes.value.some(n=>!n.group_name))
// The totals cards describe exactly the servers the list currently shows (group, status, search).
const scopeLabel=computed(()=>{ const narrowed=filter.value!=='all'||!!search.value.trim(); const name=group.value==='all'?'':group.value==='__none__'?'未分组':`分组 ${group.value}`; return `${narrowed?'筛选结果':name||'全部服务器'} · ${filtered.value.length} 台` })
// Today's traffic (report timezone, both directions regardless of billing).
const todayTx=computed(()=>filtered.value.reduce((sum,n)=>sum+n.today.tx,0)),todayRx=computed(()=>filtered.value.reduce((sum,n)=>sum+n.today.rx,0))
// Quota totals over calibrated servers; uncalibrated ones are counted separately, not guessed.
const quota=computed(()=>{ let total=0,used=0,remaining=0,counted=0,pending=0; for(const n of filtered.value){ if(!n.profile) continue; if(n.remaining==null||n.used==null){ pending++; continue }; counted++; total+=n.profile.quota_bytes; used+=n.used; remaining+=Math.max(0,n.remaining) } return { total, used, remaining, counted, pending, unset: filtered.value.filter(n=>!n.profile).length, left: total ? Math.max(0,Math.min(100,remaining/total*100)) : 0 } })
const split=(value:number,unit?:string)=>trafficBytes(value,unit).split(' ')
const refreshedAt=computed(()=>lastRefresh.value?new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(lastRefresh.value*1000)):'—')
const drag=reactive({ id:'', over:'', after:false })
async function reorder(id:string,target:string,after:boolean){
  const order=[...nodes.value].sort(byCustom).map(n=>n.id).filter(v=>v!==id)
  order.splice(order.indexOf(target)+(after?1:0),0,id)
  order.forEach((v,i)=>{ const n=nodes.value.find(x=>x.id===v); if(n) n.position=i })
  try { await api('/nodes/order','PUT',{ ids:order }) } catch(e) { error.value=errorText(e); await refresh() }
}
function dragMove(e:PointerEvent){
  if(e.clientY<70) window.scrollBy(0,-14); else if(e.clientY>innerHeight-70) window.scrollBy(0,14)
  const row=document.elementFromPoint(e.clientX,e.clientY)?.closest<HTMLElement>('[data-node-id]')
  if(!row || row.dataset.nodeId===drag.id){ drag.over=''; return }
  const box=row.getBoundingClientRect(); drag.over=row.dataset.nodeId!; drag.after=e.clientY>box.top+box.height/2
}
async function dragEnd(){ window.removeEventListener('pointermove',dragMove); const { id, over, after }=drag; drag.id=''; drag.over=''; if(id && over) await reorder(id,over,after) }
function dragStart(e:PointerEvent,id:string){ if(e.button!==0) return; drag.id=id; drag.over=''; window.addEventListener('pointermove',dragMove); window.addEventListener('pointerup',dragEnd,{ once:true }); window.addEventListener('pointercancel',dragEnd,{ once:true }) }
// Keyboard alternative: ↑ / ↓ on the focused handle moves the server among the visible rows.
async function nudge(id:string,step:number,el:HTMLElement){ const list=filtered.value, i=list.findIndex(n=>n.id===id), target=list[i+step]; if(!target) return; await reorder(id,target.id,step>0); requestAnimationFrame(()=>el.focus()) }
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
          <section class="overview-top">
            <div class="overview-col">
              <div class="kpi">
                <div class="kpi-head"><span>总流量额度 · {{ scopeLabel }}</span><i class="kpi-icon"><Gauge :size="17" /></i></div>
                <div class="today-split">
                  <div><span>总额度</span><b>{{ split(quota.total)[0] }}<small>{{ split(quota.total)[1] }}</small></b></div>
                  <div><span>已使用</span><b>{{ split(quota.used)[0] }}<small>{{ split(quota.used)[1] }}</small></b></div>
                  <div class="today-total"><span>剩余</span><b :class="{ amber: quota.counted && quota.left<20 }">{{ split(quota.remaining)[0] }}<small>{{ split(quota.remaining)[1] }}</small></b></div>
                </div>
                <div class="bar quota-bar"><i :class="{ warn: quota.counted && quota.left<20 }" :style="{ width: `${quota.left}%` }"></i></div>
                <p>{{ quota.counted ? `剩余 ${quota.left.toFixed(1)}% · 计入 ${quota.counted} 台` : '暂无已校准的服务器' }}<template v-if="quota.pending || quota.unset"> · 未计入：{{ [quota.pending ? `${quota.pending} 台待校准` : '', quota.unset ? `${quota.unset} 台未设额度` : ''].filter(Boolean).join('、') }}</template></p>
              </div>
              <div class="kpi">
                <div class="kpi-head"><span>今日流量 · {{ scopeLabel }}</span><i class="kpi-icon"><ArrowUpDown :size="17" /></i></div>
                <div class="today-split">
                  <div><span><i class="legend tx"></i>上传</span><b>{{ split(todayTx)[0] }}<small>{{ split(todayTx)[1] }}</small></b></div>
                  <div><span><i class="legend rx"></i>下载</span><b>{{ split(todayRx)[0] }}<small>{{ split(todayRx)[1] }}</small></b></div>
                  <div class="today-total"><span>合计</span><b>{{ split(todayTx+todayRx)[0] }}<small>{{ split(todayTx+todayRx)[1] }}</small></b></div>
                </div>
                <p>{{ zone }} 今日 0 点起 · 昨日（全部服务器）上传 {{ trafficBytes(yesterday) }} / 下载 {{ trafficBytes(yesterdayRx) }}</p>
              </div>
            </div>
            <TrafficRank :nodes="filtered" :scope="scopeLabel" @open="detailId=$event" />
          </section>

          <section class="panel node-panel">
            <div class="panel-head">
              <h2>服务器列表<span class="count">{{ nodes.length }}</span></h2>
              <div class="list-controls">
                <label class="search-field"><Search :size="15" /><input v-model="search" aria-label="搜索服务器" placeholder="搜索名称或分组" /></label>
                <select v-if="groups.length" v-model="group" aria-label="筛选分组">
                  <option value="all">全部分组</option>
                  <option v-for="name in groups" :key="name" :value="name">{{ name }}</option>
                  <option v-if="ungrouped" value="__none__">未分组</option>
                </select>
                <select v-model="sortMode" aria-label="排序方式" title="排序方式">
                  <option v-for="(label,key) in sortModes" :key="key" :value="key">{{ label }}</option>
                </select>
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
              <button class="text-button" @click="search='';filter='all';group='all'">清除筛选</button>
            </div>

            <div v-else class="node-table" :class="{ sortable: sortMode==='custom', dragging: drag.id }">
              <div class="node-table-head"><span>服务器</span><span>预计剩余 / 总额度</span><span>今日流量</span><span>昨日计费量</span><span>下次重置</span><span>状态</span><span></span></div>
              <div v-for="node in filtered" :key="node.id" class="node-item" :data-node-id="node.id" :class="{ 'is-dragged': drag.id===node.id, 'drop-before': drag.over===node.id && !drag.after, 'drop-after': drag.over===node.id && drag.after }">
              <span v-if="sortMode==='custom'" class="drag-handle" role="button" tabindex="0" :aria-label="`拖动排序：${node.name}（可用上下方向键移动）`" title="拖动排序" @pointerdown.prevent="dragStart($event,node.id)" @keydown.up.prevent="nudge(node.id,-1,$event.currentTarget as HTMLElement)" @keydown.down.prevent="nudge(node.id,1,$event.currentTarget as HTMLElement)"><GripVertical :size="16" /></span>
              <button class="node-row" :class="{ risk: node.status==='warning', unavailable: ['offline','error'].includes(node.status) }" @click="detailId=node.id">
                <div class="node-identity">
                  <span class="node-symbol"><Server :size="18" :stroke-width="1.6" /></span>
                  <div>
                    <strong>{{ node.name }}<span v-if="telegram.enabled && !node.notify_channels?.length" class="mute-flag" title="未分配 Telegram 通知渠道，不会收到通知"><BellOff :size="13" /></span></strong>
                    <span class="node-sub">{{ node.group_name || (node.profile ? directions[node.profile.direction] : '计费待配置') }} · {{ node.meta.connection==='socks5' ? `SOCKS5${node.proxy_name ? ' · ' + node.proxy_name : ''}` : '直连' }}</span>
                  </div>
                </div>
                <div class="balance-cell">
                  <span v-if="node.remaining!=null" class="node-balance" :class="{ amber: node.status==='warning' }">{{ bytes(node.remaining,node.profile?.unit).split(' ')[0] }} <small>/ {{ node.profile ? bytes(node.profile.quota_bytes,node.profile.unit) : '—' }}</small></span>
                  <span v-else class="muted">{{ node.profile ? '等待校准余额' : '尚未设置额度' }}</span>
                  <div v-if="node.percent!=null" class="bar"><i :class="{ warn: node.percent>=80, stale: !node.fresh }" :style="{ width: `${Math.max(0,Math.min(100,100-node.percent))}%` }"></i></div>
                  <span class="node-sub" :class="{ amber: node.exhaustion_risk }">{{ node.exhaustion_risk ? '预计无法撑到重置日' : node.enrolled && !node.fresh ? '数据过期或补报中' : node.percent!=null ? `剩余 ${Math.max(0,100-node.percent).toFixed(1)}%` : '点击配置与校准' }}</span>
                </div>
                <div class="today-cell">
                  <span class="mobile-label">今日流量</span>
                  <template v-if="node.enrolled">
                    <strong>{{ trafficBytes(node.today.tx+node.today.rx, node.profile?.unit) }}</strong>
                    <span class="today-dir"><span><ArrowUp :size="12" class="up" />{{ trafficBytes(node.today.tx, node.profile?.unit) }}</span><span><ArrowDown :size="12" class="down" />{{ trafficBytes(node.today.rx, node.profile?.unit) }}</span></span>
                  </template>
                  <strong v-else>—</strong>
                </div>
                <div class="yesterday-cell">
                  <span class="mobile-label">昨日计费量</span>
                  <strong>{{ node.profile ? trafficBytes(metered(node,node.yesterday),node.profile.unit) : '—' }}</strong>
                  <span v-if="node.enrolled && node.yesterday.coverage<.95" class="node-sub">采集未覆盖全天</span>
                </div>
                <div class="reset-cell">
                  <span class="mobile-label">下次重置</span>
                  <strong><span class="nowrap">{{ shortDate(node.cycle_end,node.profile?.timezone) }}</span><span v-if="node.cycle_end" class="nowrap">（{{ timeLeft(node.cycle_end) }}）</span></strong>
                  <span v-if="node.profile" class="node-sub">每月 {{ node.profile.reset_day }} 日</span>
                </div>
                <div class="state-cell">
                  <span class="status" :class="node.status">{{ statusLabels[node.status] }}</span>
                  <span class="node-sub">{{ ago(node.heartbeat) }}</span>
                </div>
                <ChevronRight class="row-chevron" :size="16" />
              </button>
              </div>
            </div>

            <div class="panel-foot">
              <span>{{ sortMode==='custom' ? '拖拽排序 · 拖动左侧手柄调整顺序' : sortModes[sortMode] }} · 每 15 秒刷新</span>
              <span>最后刷新 {{ refreshedAt }}</span>
            </div>
          </section>
        </div>

        <SettingsView v-else-if="page==='notifications' || page==='system'" :key="page" :section="page" @saved="loadTelegram" @password-changed="expired" />
        <EventsView v-else-if="page==='events'" />

        <footer class="page-footer">预计余额用于提前提醒，商家实际结算可能存在差异。</footer>
      </div>
    </main>

    <AddNodeModal v-if="adding" :existing="installNode" @close="adding=false;refresh()" @created="refresh" @settings="adding=false;page='system'" />
    <NodeDetail v-if="detailId" :key="detailId" :id="detailId" @close="detailId=''" @changed="refresh" @install="showInstall" />
  </div>

  <datalist id="timezones">
    <option value="Asia/Shanghai" /><option value="UTC" /><option value="Asia/Hong_Kong" /><option value="Asia/Tokyo" /><option value="America/Los_Angeles" /><option value="America/New_York" /><option value="Europe/Berlin" />
  </datalist>
</template>
