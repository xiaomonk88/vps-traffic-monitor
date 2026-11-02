<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Download, Eye, Send, ShieldCheck, Save, ExternalLink } from 'lucide-vue-next'
import { api, errorText } from '../api'
import ModalShell from './ModalShell.vue'
const props = defineProps<{ section: 'notifications' | 'system' }>(); const emit = defineEmits<{ passwordChanged: []; saved: [] }>()
const form = reactive<any>({ timezone:'Asia/Shanghai',daily_time:'09:00',daily_enabled:true,telegram_enabled:false,chat_id:'',thresholds:[80,90,95],offline_minutes:5,forecast_enabled:true,reset_notice:true,pre_reset_notice:true,public_url:'',bot_token:'',proxy_url:'',clear_proxy:false,clear_token:false,token_configured:false,proxy_configured:false })
const thresholds = ref('80, 90, 95'), error = ref(''), success = ref(''), busy = ref(false), loading = ref(true), preview = ref<string | null>(null)
const password = reactive({ old:'',new:'',confirm:'' })
async function load() { try { const cfg = await api('/settings'); Object.assign(form,cfg); thresholds.value = cfg.thresholds.join(', ') } catch(e) { error.value = errorText(e) } finally { loading.value = false } }
async function save() { busy.value = true; error.value='';success.value=''; try { const levels=thresholds.value.split(/[,，\s]+/).filter(Boolean).map(Number); if (!levels.length || levels.some(n=>!Number.isFinite(n)||n<1||n>100)) throw new Error('请输入 1～100 之间的告警百分比，以逗号分隔。'); await api('/settings','PUT',{...form,thresholds:levels}); form.bot_token='';form.proxy_url='';form.clear_token=false;form.clear_proxy=false;await load();success.value='设置已保存。';emit('saved') } catch(e) { error.value=errorText(e) } finally { busy.value=false } }
async function command(name: string) { error.value='';success.value='';busy.value=true;try { if(name==='preview') { preview.value=(await api('/telegram/preview')).text;return }; const result=await api(`/telegram/${name}`,'POST'); if(name==='test') { if(result.state==='sent') success.value='Telegram 已确认测试消息发送成功。'; else error.value=`测试消息尚未发送成功：${result.error || '已进入重试队列，请查看事件记录。'}` } else success.value='日报已加入发送队列，请在事件记录中查看发送结果。' } catch(e) { error.value=errorText(e) } finally { busy.value=false } }
async function changePassword() { error.value='';success.value='';if(password.new!==password.confirm) { error.value='两次输入的新密码不一致。';return };busy.value=true;try {await api('/password','POST',{old:password.old,new:password.new});emit('passwordChanged')} catch(e){error.value=errorText(e)}finally{busy.value=false} }
async function backup() { error.value='';busy.value=true;try{const response=await fetch('/api/backup',{credentials:'same-origin'});if(!response.ok)throw new Error('备份生成失败，请刷新登录状态后重试。');const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`sentinel-backup-${new Date().toISOString().slice(0,10)}.zip`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);success.value='备份已生成并开始下载。'}catch(e){error.value=errorText(e)}finally{busy.value=false} }
onMounted(load)
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
            <div><h2>Telegram 连接</h2><p class="muted">由主控统一发送日报和告警，各服务器无需单独配置。</p></div>
            <span class="tag" :class="{ positive: form.telegram_enabled }">{{ form.telegram_enabled ? '已启用' : '未启用' }}</span>
          </header>
          <div class="setting-body">
            <label class="check-label"><input v-model="form.telegram_enabled" type="checkbox" />启用 Telegram 通知</label>
            <div class="form-grid">
              <label>Bot Token<input v-model="form.bot_token" type="password" autocomplete="new-password" :placeholder="form.token_configured ? '已保存，留空保持原值' : '填写 BotFather 提供的 Token'" maxlength="200" /><small>已保存的 Token 不会回显。</small></label>
              <label>Chat ID<input v-model="form.chat_id" placeholder="个人或群组 Chat ID" maxlength="100" /><small>先与 Bot 开始对话，或将其加入目标群组。</small></label>
            </div>
            <details class="advanced">
              <summary>主控出站代理（可选）{{ form.proxy_configured ? ' · 已配置' : '' }}</summary>
              <div class="stack">
                <label>SOCKS5 代理地址<input v-model="form.proxy_url" type="password" autocomplete="new-password" placeholder="socks5h://用户名:密码@地址:端口" /><small>仅用于主控发送 Telegram。留空保持已保存的代理。</small></label>
                <label class="check-label"><input v-model="form.clear_proxy" type="checkbox" />清除已保存的通知代理</label>
              </div>
            </details>
            <p class="hint">先保存设置，再测试连接。测试结果以 Telegram 返回状态为准。</p>
          </div>
        </section>

        <section class="panel setting-section">
          <header class="setting-head">
            <div><h2>每日报告</h2><p class="muted">汇总昨天的用量，以及截至最近上报的预计余额和重置日期。</p></div>
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
            <div><h2>即时提醒</h2><p class="muted">额度、离线与重置相关的告警规则。</p></div>
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
          <button class="secondary" type="button" :disabled="busy" @click="command('test')"><Send :size="16" />测试通知</button>
          <button class="primary" :disabled="busy"><Save :size="16" />{{ busy ? '正在处理…' : '保存通知设置' }}</button>
        </div>
      </form>

      <div v-else class="settings-form">
        <form class="panel setting-section" @submit.prevent="save">
          <header class="setting-head">
            <div><h2>主控访问地址</h2><p class="muted">生成 Agent 安装命令时使用。部署到 VPS 后应填写目标机器能访问的完整地址。</p></div>
          </header>
          <div class="setting-body">
            <label>公开地址<input v-model="form.public_url" type="url" placeholder="留空使用当前访问地址" /><small>本地测试可使用 http://127.0.0.1:8080；远程部署建议使用 HTTPS。</small></label>
            <div class="form-actions"><button class="primary" :disabled="busy">保存主控地址</button></div>
          </div>
        </form>

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

    <ModalShell v-if="preview!==null" title="日报预览" wide @close="preview=null">
      <pre class="report-preview">{{ preview }}</pre>
      <p class="hint">预览不会发送消息。需要发送时返回点击“立即发送日报”。</p>
    </ModalShell>
  </div>
</template>
