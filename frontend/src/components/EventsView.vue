<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RefreshCw, ScrollText } from 'lucide-vue-next'
import { api, dateTime, errorText } from '../api'
const events=ref<any[]>([]), notifications=ref<any[]>([]), tab=ref('events'),busy=ref(false),error=ref('')
const stateNames:Record<string,string>={sent:'已发送',pending:'等待发送',sending:'正在发送',failed:'发送失败',expired:'已过期',retry:'等待重试',suppressed:'已取消'}
async function load(){busy.value=true;error.value='';try{const data=await api('/events');events.value=data.events;notifications.value=data.notifications}catch(e){error.value=errorText(e)}finally{busy.value=false}}
onMounted(load)
</script>

<template>
  <section class="panel events-panel">
    <div class="panel-head">
      <nav class="tabs" aria-label="记录类型">
        <button :class="{ active: tab==='events' }" @click="tab='events'">系统事件 <span>{{ events.length }}</span></button>
        <button :class="{ active: tab==='notifications' }" @click="tab='notifications'">通知发送 <span>{{ notifications.length }}</span></button>
      </nav>
      <button class="secondary small" :disabled="busy" @click="load"><RefreshCw :size="15" :class="{ spinning: busy }" />刷新</button>
    </div>
    <div v-if="error" class="alert error" role="alert">{{ error }}</div>
    <div v-if="busy && !events.length" class="loading">正在读取事件…</div>

    <template v-else-if="tab==='events'">
      <div v-if="!events.length" class="empty">
        <div class="empty-icon"><ScrollText :size="28" /></div>
        <h3>还没有系统事件</h3>
        <p>添加服务器、校准余额和异常状态会记录在这里。</p>
      </div>
      <div v-else class="event-list">
        <div v-for="event in events" :key="event.id" class="event-row">
          <span class="event-dot"></span>
          <div class="event-content"><strong>{{ event.node_name || '主控' }}</strong><p>{{ event.message }}</p></div>
          <time>{{ dateTime(event.at) }}</time>
        </div>
      </div>
    </template>

    <template v-else>
      <div v-if="!notifications.length" class="empty">
        <div class="empty-icon"><ScrollText :size="28" /></div>
        <h3>还没有发送记录</h3>
        <p>配置 Telegram 后，可发送一条测试通知。</p>
      </div>
      <details v-for="notice in notifications" :key="notice.id" class="notice-row">
        <summary>
          <span class="tag" :class="notice.state==='sent' ? 'positive' : notice.error ? 'negative' : ''">{{ stateNames[notice.state] || notice.state }}</span>
          <strong>{{ notice.text.split('\n')[0] }}</strong>
          <time>{{ dateTime(notice.created) }}</time>
        </summary>
        <pre class="report-preview">{{ notice.text }}</pre>
        <p class="hint">尝试 {{ notice.attempts }} 次<span v-if="notice.delivered"> · 发送时间 {{ dateTime(notice.delivered) }}</span></p>
        <div v-if="notice.error" class="alert error">{{ notice.error }}</div>
      </details>
    </template>
  </section>
</template>
