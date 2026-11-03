<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Download, Eye, Send, ShieldCheck, Save, Plus, Pencil, Trash2, MessageCircle, Network, Activity } from 'lucide-vue-next'
import { api, errorText } from '../api'
import ModalShell from './ModalShell.vue'
interface Channel { id: string; name: string; chat_id: string; enabled: boolean; daily: boolean; alerts: boolean; token_configured: boolean }
interface AgentProxy { id: string; host: string; port: number; username: string; has_password: boolean; note: string; endpoint: string; nodes: string[] }
const props = defineProps<{ section: 'notifications' | 'system' }>(); const emit = defineEmits<{ passwordChanged: []; saved: [] }>()
const form = reactive<any>({ timezone:'Asia/Shanghai',daily_time:'09:00',daily_enabled:true,telegram_enabled:false,channels:[] as Channel[],thresholds:[80,90,95],offline_minutes:5,forecast_enabled:true,reset_notice:true,pre_reset_notice:true,public_url:'',proxy_url:'',clear_proxy:false,proxy_configured:false })
const thresholds = ref('80, 90, 95'), error = ref(''), success = ref(''), busy = ref(false), loading = ref(true), preview = ref<string | null>(null)
const password = reactive({ old:'',new:'',confirm:'' })
const blankChannel = () => ({ id:'', name:'', chat_id:'', bot_token:'', enabled:true, daily:true, alerts:true, token_configured:false })
const channel = reactive(blankChannel()), channelOpen = ref(false), channelError = ref(''), removing = ref<Channel | null>(null), acting = ref('')
async function load() { try { const cfg = await api('/settings'); Object.assign(form,cfg); thresholds.value = cfg.thresholds.join(', ') } catch(e) { error.value = errorText(e) } finally { loading.value = false } }
async function save() { busy.value = true; error.value='';success.value=''; try { const levels=thresholds.value.split(/[,，\s]+/).filter(Boolean).map(Number); if (!levels.length || levels.some(n=>!Number.isFinite(n)||n<1||n>100)) throw new Error('请输入 1～100 之间的告警百分比，以逗号分隔。'); await api('/settings','PUT',{...form,thresholds:levels}); form.proxy_url='';form.clear_proxy=false;await load();success.value='设置已保存。';emit('saved') } catch(e) { error.value=errorText(e) } finally { busy.value=false } }
async function command(name: string) { error.value='';success.value='';busy.value=true;try { if(name==='preview') { preview.value=(await api('/telegram/preview')).text;return }; const result=await api(`/telegram/${name}`,'POST'); if(name==='test') { if(result.state==='sent') success.value=`Telegram 已确认 ${result.results.length} 个渠道的测试消息发送成功。`; else error.value=`部分测试消息未发送成功：${result.error}` } else success.value='日报已加入发送队列，请在事件记录中查看发送结果。' } catch(e) { error.value=errorText(e) } finally { busy.value=false } }
async function changePassword() { error.value='';success.value='';if(password.new!==password.confirm) { error.value='两次输入的新密码不一致。';return };busy.value=true;try {await api('/password','POST',{old:password.old,new:password.new});emit('passwordChanged')} catch(e){error.value=errorText(e)}finally{busy.value=false} }
async function backup() { error.value='';busy.value=true;try{const response=await fetch('/api/backup',{credentials:'same-origin'});if(!response.ok)throw new Error('备份生成失败，请刷新登录状态后重试。');const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`sentinel-backup-${new Date().toISOString().slice(0,10)}.zip`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);success.value='备份已生成并开始下载。'}catch(e){error.value=errorText(e)}finally{busy.value=false} }

// Channels are saved immediately through their own API; the rest of the form keeps its unsaved edits.
async function reloadChannels() { form.channels = (await api('/settings')).channels; emit('saved') }
function openChannel(item?: Channel) { Object.assign(channel, blankChannel(), item || {}, { bot_token: '' }); channelError.value = ''; channelOpen.value = true }
async function saveChannel() { channelError.value=''; busy.value=true; try { const body={ name:channel.name, chat_id:channel.chat_id, bot_token:channel.bot_token, enabled:channel.enabled, daily:channel.daily, alerts:channel.alerts }; if(channel.id) await api(`/telegram/channels/${channel.id}`,'PUT',body); else await api('/telegram/channels','POST',body); channelOpen.value=false; await reloadChannels(); error.value=''; success.value=`通知渠道“${body.name}”已保存。` } catch(e) { channelError.value=errorText(e) } finally { busy.value=false } }
async function channelAction(item: Channel, work: () => Promise<void>) { acting.value=item.id; error.value=''; success.value=''; try { await work() } catch(e) { error.value=errorText(e) } finally { acting.value='' } }
const toggleChannel = (item: Channel) => channelAction(item, async () => { await api(`/telegram/channels/${item.id}`,'PUT',{ enabled:!item.enabled }); await reloadChannels() })
const testChannel = (item: Channel) => channelAction(item, async () => { const result=await api('/telegram/test','POST',{ channel:item.id }); if(result.state==='sent') success.value=`测试消息已发送到“${item.name}”。`; else error.value=`“${item.name}”测试失败：${result.results[0]?.error || '已进入重试队列'}` })
async function removeChannel() { const item=removing.value; if(!item) return; await channelAction(item, async () => { const result=await api(`/telegram/channels/${item.id}`,'DELETE'); if(!result.telegram_enabled) form.telegram_enabled=false; removing.value=null; await reloadChannels(); success.value=`已删除通知渠道“${item.name}”。` }) }

// Agent proxies: a list of SOCKS5 endpoints chosen when generating install / switch commands.
const blankProxy = () => ({ id:'', host:'', port:1080 as number | string, username:'', password:'', note:'', has_password:false, clear_password:false })
const agentProxies = ref<AgentProxy[]>([]), proxy = reactive(blankProxy()), proxyOpen = ref(false), proxyError = ref(''), proxyRemoving = ref<AgentProxy | null>(null)
const proxyTests = reactive<Record<string, { ok: boolean; text: string }>>({})
async function loadProxies() { try { agentProxies.value = (await api('/agent-proxies')).proxies } catch(e) { error.value = errorText(e) } }
function openProxy(item?: AgentProxy) { Object.assign(proxy, blankProxy(), item || {}, { password:'', clear_password:false }); proxyError.value=''; proxyOpen.value=true }
async function saveProxy() { proxyError.value=''; busy.value=true; try { const body={ host:proxy.host, port:Number(proxy.port), username:proxy.username, password:proxy.password, note:proxy.note, clear_password:proxy.clear_password }; if(proxy.id) await api(`/agent-proxies/${proxy.id}`,'PUT',body); else await api('/agent-proxies','POST',body); proxyOpen.value=false; delete proxyTests[proxy.id]; await loadProxies(); error.value=''; success.value=`代理“${body.note || body.host}”已保存。${proxy.id ? '已安装的 Agent 需在服务器详情中执行更换命令后才会使用新设置。' : ''}` } catch(e) { proxyError.value=errorText(e) } finally { busy.value=false } }
async function testProxy(item: AgentProxy) { acting.value=item.id; proxyTests[item.id]={ ok:false, text:'检测中…' }; try { const r=await api(`/agent-proxies/${item.id}/test`,'POST'); proxyTests[item.id] = r.ok ? { ok:true, text:`可用 · ${r.ms} ms` } : { ok:false, text:r.error } } catch(e) { proxyTests[item.id]={ ok:false, text:errorText(e) } } finally { acting.value='' } }
async function removeProxy() { const item=proxyRemoving.value; if(!item) return; acting.value=item.id; try { await api(`/agent-proxies/${item.id}`,'DELETE'); proxyRemoving.value=null; await loadProxies(); success.value=`已删除代理“${item.note || item.endpoint}”。` } catch(e) { error.value=errorText(e) } finally { acting.value='' } }
onMounted(() => { load(); if (props.section === 'system') loadProxies() })
</script>

<template>
  <div class="settings-layout">
    <div v-if="loading" class="loading">正在加载设置…</div>
    <template v-else>
      <div v-if="error" class="alert error" role="alert">{{ error }}</div>
      <div v-if="success" class="alert success" role="status">{{ success }}</div>

      <form v-if="section==='notifications'" class="settings-form" @submit.prevent="save">
        <section class="panel setting-section">
          <header class="setting-head">
            <div><h2>Telegram 通知渠道</h2><p class="muted">可添加多个 Bot / 会话，并分别选择接收日报或告警。由主控统一发送，各服务器无需配置。</p></div>
            <span class="tag" :class="{ positive: form.telegram_enabled }">{{ form.telegram_enabled ? '已启用' : '未启用' }}</span>
          </header>
          <div class="setting-body">
            <label class="check-label"><input v-model="form.telegram_enabled" type="checkbox" />启用 Telegram 通知</label>

            <div class="channel-list">
              <div class="channel-list-head">
                <span>通知渠道 <b>{{ form.channels.length }}</b></span>
                <button type="button" class="secondary small" @click="openChannel()"><Plus :size="15" />添加通知渠道</button>
              </div>
              <div v-if="!form.channels.length" class="channel-empty">
                <MessageCircle :size="22" />
                <p>还没有通知渠道。添加 Bot Token 与 Chat ID 后即可接收日报和告警。</p>
              </div>
              <div v-for="item in form.channels" :key="item.id" class="channel-row" :class="{ off: !item.enabled }">
                <label class="switch" :title="item.enabled ? '已启用' : '已停用'">
                  <input type="checkbox" :checked="item.enabled" :disabled="acting===item.id" :aria-label="`启用渠道 ${item.name}`" @change="toggleChannel(item)" /><span></span>
                </label>
                <div class="channel-main">
                  <strong>{{ item.name }}</strong>
                  <span>Chat ID {{ item.chat_id }}<template v-if="!item.token_configured"> · <em>缺少 Token</em></template></span>
                </div>
                <div class="channel-kinds">
                  <span class="kind" :class="{ on: item.daily }">日报</span>
                  <span class="kind" :class="{ on: item.alerts }">告警</span>
                </div>
                <div class="channel-actions">
                  <button type="button" class="text-button" :disabled="acting===item.id" @click="testChannel(item)"><Send :size="14" />测试</button>
                  <button type="button" class="icon-button" :aria-label="`编辑渠道 ${item.name}`" title="编辑" @click="openChannel(item)"><Pencil :size="15" /></button>
                  <button type="button" class="icon-button danger" :aria-label="`删除渠道 ${item.name}`" title="删除" @click="removing=item"><Trash2 :size="15" /></button>
                </div>
              </div>
            </div>

            <details class="advanced">
              <summary>主控出站代理（可选）{{ form.proxy_configured ? ' · 已配置' : '' }}</summary>
              <div class="stack">
                <p class="hint">仅用于<strong>主控服务器</strong>访问 Telegram API，与 VPS 上 Agent 连接主控使用的代理无关。</p>
                <label>SOCKS5 代理地址<input v-model="form.proxy_url" type="password" autocomplete="new-password" placeholder="socks5h://用户名:密码@地址:端口" /><small>留空保持已保存的代理。</small></label>
                <label class="check-label"><input v-model="form.clear_proxy" type="checkbox" />清除已保存的通知代理</label>
              </div>
            </details>
          </div>
        </section>

        <section class="panel setting-section">
          <header class="setting-head">
            <div><h2>每日报告</h2><p class="muted">汇总昨天的用量，以及截至最近上报的预计余额和重置日期。仅发送到勾选“日报”的渠道。</p></div>
          </header>
          <div class="setting-body">
            <label class="check-label"><input v-model="form.daily_enabled" type="checkbox" />每天定时发送汇总</label>
            <div class="form-grid">
              <label>发送时间<input v-model="form.daily_time" required type="time" /></label>
              <label>报告时区<input v-model="form.timezone" required list="timezones" /></label>
            </div>
          </div>
        </section>

        <section class="panel setting-section">
          <header class="setting-head">
            <div><h2>即时提醒</h2><p class="muted">额度、离线与重置相关的告警规则。仅发送到勾选“告警”的渠道。</p></div>
          </header>
          <div class="setting-body">
            <div class="form-grid">
              <label>已用额度阈值（%）<input v-model="thresholds" required placeholder="80, 90, 95" /><small>同一周期、同一等级去重提醒。</small></label>
              <label>离线判定（分钟）<input v-model="form.offline_minutes" required type="number" min="1" max="1440" /></label>
            </div>
            <div class="check-group">
              <label class="check-label"><input v-model="form.forecast_enabled" type="checkbox" />预计无法撑到重置日时提醒</label>
              <label class="check-label"><input v-model="form.pre_reset_notice" type="checkbox" />距离重置不足 24 小时提醒</label>
              <label class="check-label"><input v-model="form.reset_notice" type="checkbox" />按配置进入新周期时提醒</label>
            </div>
          </div>
        </section>

        <div class="settings-actions">
          <button class="text-button" type="button" :disabled="busy" @click="command('daily')">立即发送日报</button>
          <span class="spacer"></span>
          <button class="secondary" type="button" :disabled="busy" @click="command('preview')"><Eye :size="16" />预览日报</button>
          <button class="secondary" type="button" :disabled="busy" @click="command('test')"><Send :size="16" />测试全部渠道</button>
          <button class="primary" :disabled="busy"><Save :size="16" />{{ busy ? '正在处理…' : '保存通知设置' }}</button>
        </div>
      </form>

      <div v-else class="settings-form">
        <form class="panel setting-section" @submit.prevent="save">
          <header class="setting-head">
            <div><h2>主控访问地址</h2><p class="muted">生成 Agent 安装命令时使用。部署到 VPS 后应填写目标机器能访问的完整地址。</p></div>
          </header>
          <div class="setting-body">
            <label>公开地址<input v-model="form.public_url" type="url" placeholder="留空使用当前访问地址" /><small>填写反向代理后的 HTTPS 域名，例如 https://traffic.example.com（可使用 Cloudflare 代理）。远程 Agent 只能通过 HTTPS 连接，不能填 http://IP:端口；仅本机测试可用 http://127.0.0.1。</small></label>
            <div class="form-actions"><button class="primary" :disabled="busy">保存主控地址</button></div>
          </div>
        </form>

        <section class="panel setting-section">
          <header class="setting-head">
            <div><h2>Agent 连接代理</h2><p class="muted">VPS 无法直连主控时，Agent 通过 SOCKS5 代理上报。添加服务器或更换代理时，可从这里选择一条写入命令。</p></div>
            <span class="tag" :class="{ positive: agentProxies.length }">{{ agentProxies.length ? `${agentProxies.length} 条` : '未添加' }}</span>
          </header>
          <div class="setting-body">
            <div class="channel-list">
              <div class="channel-list-head">
                <span>SOCKS5 代理 <b>{{ agentProxies.length }}</b></span>
                <button type="button" class="secondary small" @click="openProxy()"><Plus :size="15" />添加代理</button>
              </div>
              <div v-if="!agentProxies.length" class="channel-empty">
                <Network :size="22" />
                <p>还没有代理。添加后，生成 Agent 安装命令时可选择使用哪条代理。</p>
              </div>
              <div v-for="item in agentProxies" :key="item.id" class="proxy-row">
                <span class="proxy-icon"><Network :size="16" /></span>
                <div class="channel-main">
                  <strong>{{ item.note || '未命名代理' }}</strong>
                  <span>{{ item.endpoint }} · {{ item.username ? `用户 ${item.username}${item.has_password ? ' · 已设密码' : ''}` : '无认证' }}</span>
                  <span class="proxy-usage">{{ item.nodes.length ? `使用中：${item.nodes.join('、')}` : '暂无服务器使用' }}</span>
                </div>
                <span v-if="proxyTests[item.id]" class="proxy-test" :class="{ ok: proxyTests[item.id].ok, bad: !proxyTests[item.id].ok && proxyTests[item.id].text !== '检测中…' }">{{ proxyTests[item.id].text }}</span>
                <div class="channel-actions">
                  <button type="button" class="text-button" :disabled="acting===item.id" title="从主控经此代理访问公开地址" @click="testProxy(item)"><Activity :size="14" />检测</button>
                  <button type="button" class="icon-button" :aria-label="`编辑代理 ${item.note || item.endpoint}`" title="编辑" @click="openProxy(item)"><Pencil :size="15" /></button>
                  <button type="button" class="icon-button danger" :aria-label="`删除代理 ${item.note || item.endpoint}`" title="删除" @click="proxyRemoving=item"><Trash2 :size="15" /></button>
                </div>
              </div>
            </div>
            <p class="hint">“检测”由主控经该代理访问自己的公开地址，可验证代理在线与账号密码；VPS 到代理的线路仍以实际安装为准。修改代理不会自动影响已安装的 Agent，需在服务器详情“管理 → 更换 Agent 代理”中生成命令执行。</p>
          </div>
        </section>

        <section class="panel setting-section">
          <header class="setting-head">
            <div><h2>数据备份</h2><p class="muted">导出一致性数据库快照与应用加密密钥。备份包含敏感配置，请妥善保存。</p></div>
          </header>
          <div class="setting-body">
            <div class="form-actions"><button class="secondary" :disabled="busy" @click="backup"><Download :size="16" />下载完整备份</button></div>
          </div>
        </section>

        <form class="panel setting-section" @submit.prevent="changePassword">
          <header class="setting-head">
            <div><h2>修改管理员密码</h2><p class="muted">保存后全部登录会话失效，请使用新密码重新登录。</p></div>
          </header>
          <div class="setting-body">
            <div class="form-grid">
              <label>当前密码<input v-model="password.old" type="password" required autocomplete="current-password" /></label>
              <div></div>
              <label>新密码<input v-model="password.new" type="password" required minlength="12" maxlength="256" autocomplete="new-password" placeholder="至少 12 个字符" /></label>
              <label>确认新密码<input v-model="password.confirm" type="password" required minlength="12" maxlength="256" autocomplete="new-password" /></label>
            </div>
            <div class="form-actions"><button class="secondary" :disabled="busy"><ShieldCheck :size="16" />更新密码</button></div>
          </div>
        </form>
      </div>
    </template>

    <ModalShell v-if="channelOpen" :title="channel.id ? `编辑通知渠道 · ${channel.name}` : '添加通知渠道'" @close="channelOpen=false">
      <form class="stack" @submit.prevent="saveChannel">
        <label>渠道名称<input v-model="channel.name" required maxlength="40" placeholder="例如：个人、运维群" /></label>
        <label>Bot Token<input v-model="channel.bot_token" type="password" autocomplete="new-password" maxlength="200" :required="!channel.token_configured" :placeholder="channel.token_configured ? '已保存，留空保持原值' : '填写 BotFather 提供的 Token'" /><small>已保存的 Token 不会回显。多个渠道可以共用同一个 Bot。</small></label>
        <label>Chat ID<input v-model="channel.chat_id" required maxlength="100" placeholder="个人或群组 Chat ID" /><small>先与 Bot 开始对话，或将其加入目标群组。</small></label>
        <div class="check-group">
          <label class="check-label"><input v-model="channel.daily" type="checkbox" />接收每日报告</label>
          <label class="check-label"><input v-model="channel.alerts" type="checkbox" />接收即时告警（额度、离线、重置）</label>
          <label class="check-label"><input v-model="channel.enabled" type="checkbox" />启用此渠道</label>
        </div>
        <div v-if="channelError" class="alert error" role="alert">{{ channelError }}</div>
        <div class="actions modal-actions"><button type="button" class="secondary" @click="channelOpen=false">取消</button><button class="primary" :disabled="busy">{{ busy ? '正在保存…' : '保存渠道' }}</button></div>
      </form>
    </ModalShell>

    <ModalShell v-if="proxyOpen" :title="proxy.id ? `编辑代理 · ${proxy.note || proxy.host}` : '添加 SOCKS5 代理'" @close="proxyOpen=false">
      <form class="stack" @submit.prevent="saveProxy">
        <label>备注<input v-model="proxy.note" maxlength="60" placeholder="例如：香港中转、家宽出口" /></label>
        <div class="proxy-grid">
          <label>代理地址<input v-model="proxy.host" required maxlength="253" placeholder="IP 或域名，如 203.0.113.8" /></label>
          <label>端口<input v-model="proxy.port" required type="number" min="1" max="65535" placeholder="1080" /></label>
        </div>
        <div class="form-grid">
          <label>用户名（可选）<input v-model="proxy.username" maxlength="255" autocomplete="off" placeholder="无认证留空" /></label>
          <label>密码（可选）<input v-model="proxy.password" type="password" maxlength="255" autocomplete="new-password" :disabled="proxy.clear_password" :placeholder="proxy.has_password ? '已保存，留空保持原值' : '无认证留空'" /></label>
        </div>
        <label v-if="proxy.has_password" class="check-label"><input v-model="proxy.clear_password" type="checkbox" />清除已保存的密码</label>
        <p class="hint">按 SOCKS5（socks5h，由代理解析域名）连接。用户名和密码可包含任意字符，会自动编码。密码保存后不会回显。</p>
        <div v-if="proxyError" class="alert error" role="alert">{{ proxyError }}</div>
        <div class="actions modal-actions"><button type="button" class="secondary" @click="proxyOpen=false">取消</button><button class="primary" :disabled="busy">{{ busy ? '正在保存…' : '保存代理' }}</button></div>
      </form>
    </ModalShell>

    <ModalShell v-if="proxyRemoving" title="删除代理" @close="proxyRemoving=null">
      <div class="stack">
        <p>确定删除代理“<strong>{{ proxyRemoving.note || proxyRemoving.endpoint }}</strong>”（{{ proxyRemoving.endpoint }}）？</p>
        <div v-if="proxyRemoving.nodes.length" class="alert warn">仍有服务器在使用：{{ proxyRemoving.nodes.join('、') }}。删除只影响面板中的记录，这些 Agent 会继续使用原代理；如需更换，请在服务器详情中执行更换命令。</div>
        <div class="actions"><button type="button" class="secondary" @click="proxyRemoving=null">取消</button><button type="button" class="danger-solid" :disabled="acting===proxyRemoving.id" @click="removeProxy">确认删除</button></div>
      </div>
    </ModalShell>

    <ModalShell v-if="removing" title="删除通知渠道" @close="removing=null">
      <div class="stack">
        <p>确定删除通知渠道“<strong>{{ removing.name }}</strong>”？其 Bot Token 会一并删除，尚未发送的消息将不再发送。</p>
        <div class="actions"><button type="button" class="secondary" @click="removing=null">取消</button><button type="button" class="danger-solid" :disabled="acting===removing.id" @click="removeChannel">确认删除</button></div>
      </div>
    </ModalShell>

    <ModalShell v-if="preview!==null" title="日报预览" wide @close="preview=null">
      <pre class="report-preview">{{ preview }}</pre>
      <p class="hint">预览不会发送消息。需要发送时返回点击“立即发送日报”。</p>
    </ModalShell>
  </div>
</template>
