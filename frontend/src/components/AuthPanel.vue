<script setup lang="ts">
import { ref } from 'vue'
import { Activity, ArrowRight, ShieldCheck, Gauge, CalendarClock, Send } from 'lucide-vue-next'
import { api, errorText, setCSRF } from '../api'
const props = defineProps<{ setup: boolean }>(); const emit = defineEmits<{ authenticated: [name: string] }>()
const username = ref('admin'), password = ref(''), setupToken = ref(''), error = ref(''), busy = ref(false)
async function submit() { error.value = ''; busy.value = true; try { if (props.setup) await api('/setup', 'POST', { username: username.value, password: password.value, setup_token: setupToken.value }); const data = await api('/login', 'POST', { username: username.value, password: password.value }); setCSRF(data.csrf); emit('authenticated', data.username) } catch (e) { error.value = errorText(e) } finally { busy.value = false } }
</script>

<template>
  <main class="auth-layout">
    <section class="auth-intro" aria-hidden="true">
      <div class="auth-brand"><span class="brand-mark"><Activity :size="20" /></span><strong>流量哨</strong><span>TRAFFIC SENTINEL</span></div>
      <div class="auth-intro-body">
        <h2>VPS 流量额度监控</h2>
        <p>统一管理多台服务器的流量额度、重置周期与告警通知。</p>
        <ul>
          <li><i><Gauge :size="17" /></i><div><strong>额度实时估算</strong><span>按计费方向统计，校准后持续扣减</span></div></li>
          <li><i><CalendarClock :size="17" /></i><div><strong>重置周期跟踪</strong><span>按商家时区计算下次重置时间</span></div></li>
          <li><i><Send :size="16" /></i><div><strong>Telegram 提醒</strong><span>每日报告与额度、离线即时告警</span></div></li>
        </ul>
      </div>
      <small>© Traffic Sentinel</small>
    </section>

    <section class="auth-main">
      <div class="auth-panel">
        <div class="auth-brand compact"><span class="brand-mark"><Activity :size="18" /></span><strong>流量哨</strong></div>
        <span class="eyebrow">{{ setup ? '第一次使用' : '欢迎回来' }}</span>
        <h1>{{ setup ? '创建管理员账户' : '登录你的工作空间' }}</h1>
        <p class="muted">{{ setup ? '连接服务器之前，先设置主控的登录账户。' : '查看服务器额度、重置周期与流量提醒。' }}</p>
        <form class="stack" @submit.prevent="submit">
          <label v-if="setup">初始化密钥<input v-model="setupToken" required autocomplete="off" placeholder="从 data/setup-token.txt 中复制" /><small>密钥位于主控的数据目录，仅首次初始化使用。</small></label>
          <label>用户名<input v-model="username" required maxlength="80" autocomplete="username" /></label>
          <label>密码<input v-model="password" required :minlength="setup ? 12 : 1" maxlength="256" type="password" :autocomplete="setup ? 'new-password' : 'current-password'" :placeholder="setup ? '至少 12 个字符' : '输入管理员密码'" /></label>
          <div v-if="error" class="alert error" role="alert">{{ error }}</div>
          <button class="primary auth-submit" :disabled="busy">{{ busy ? '正在处理…' : setup ? '创建账户并进入' : '登录' }}<ArrowRight :size="17" /></button>
        </form>
        <div class="auth-foot"><ShieldCheck :size="15" />所有余额为本地估算，请以商家结算为准。</div>
      </div>
    </section>
  </main>
</template>
