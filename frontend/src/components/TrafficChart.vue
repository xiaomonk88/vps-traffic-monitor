<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Usage } from '../api'
import { trafficBytes } from '../api'
const props = defineProps<{ data: (Usage & { date: string })[]; unit: string }>()
const max = computed(() => Math.max(1, ...props.data.flatMap(v => [v.rx, v.tx])))
const total = computed(() => props.data.reduce((v, d) => ({ rx: v.rx + d.rx, tx: v.tx + d.tx }), { rx: 0, tx: 0 }))
const selected = ref('')
const selectedDay = computed(() => props.data.find(d => d.date === selected.value) || props.data.at(-1))
</script>
<template>
  <div class="chart-summary"><span><i class="legend tx"></i>上传 {{ trafficBytes(total.tx, unit) }}</span><span><i class="legend rx"></i>下载 {{ trafficBytes(total.rx, unit) }}</span></div>
  <div class="traffic-chart" aria-label="最近十四天上传与下载流量柱状图">
    <button v-for="day in data" :key="day.date" type="button" class="chart-column" :class="{ 'chart-selected': selectedDay?.date === day.date }" :aria-pressed="selectedDay?.date === day.date" :aria-label="`${day.date} 上传 ${trafficBytes(day.tx,unit)}，下载 ${trafficBytes(day.rx,unit)}，覆盖 ${Math.round(day.coverage*100)}%`" @click="selected=day.date">
      <span class="chart-bars"><span class="chart-bar tx" :style="{ height: `${Math.max(day.tx ? 2 : 0, day.tx / max * 100)}%` }"></span><span class="chart-bar rx" :style="{ height: `${Math.max(day.rx ? 2 : 0, day.rx / max * 100)}%` }"></span></span><span class="chart-date">{{ day.date.slice(3) }}</span>
    </button>
  </div>
  <div v-if="selectedDay" class="chart-readout"><label>查看日期<select :value="selectedDay.date" @change="selected=($event.target as HTMLSelectElement).value"><option v-for="day in data" :key="day.date" :value="day.date">{{day.date}}</option></select></label><p aria-live="polite">上传 {{trafficBytes(selectedDay.tx,unit)}} · 下载 {{trafficBytes(selectedDay.rx,unit)}}<br><span class="hint">采集覆盖 {{Math.round(selectedDay.coverage*100)}}%</span></p></div>
  <p class="hint">最近 14 天 · 点击柱形或选择日期查看读数。未采集的日期不补造历史。</p>
</template>
