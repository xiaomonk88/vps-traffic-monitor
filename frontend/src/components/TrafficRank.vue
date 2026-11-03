<script setup lang="ts">
import { computed, ref } from 'vue'
import { Trophy } from 'lucide-vue-next'
import { bytes, trafficBytes, type Node } from '../api'
const props = defineProps<{ nodes: Node[]; scope: string }>()
const emit = defineEmits<{ open: [id: string] }>()
type Mode = 'today' | 'cycle' | 'percent'
const modes: { id: Mode; name: string }[] = [{ id: 'today', name: '今日流量' }, { id: 'cycle', name: '周期已用' }, { id: 'percent', name: '使用率' }]
const mode = ref<Mode>('today')
interface Row { node: Node; value: number; tx?: number; rx?: number; label: string; detail: string }
const rows = computed<Row[]>(() => {
  if (mode.value === 'today') {
    return props.nodes.filter(n => n.enrolled).map(n => ({ node: n, value: n.today.tx + n.today.rx, tx: n.today.tx, rx: n.today.rx,
      label: trafficBytes(n.today.tx + n.today.rx, n.profile?.unit), detail: `↑ ${trafficBytes(n.today.tx, n.profile?.unit)} · ↓ ${trafficBytes(n.today.rx, n.profile?.unit)}` })).sort((a, b) => b.value - a.value)
  }
  const billed = props.nodes.filter(n => n.profile && n.used != null && n.percent != null)
  if (mode.value === 'cycle') {
    return billed.map(n => ({ node: n, value: n.used!, label: bytes(n.used, n.profile!.unit), detail: `额度 ${bytes(n.profile!.quota_bytes, n.profile!.unit)}` })).sort((a, b) => b.value - a.value)
  }
  return billed.map(n => ({ node: n, value: n.percent!, label: `${n.percent!.toFixed(1)}%`, detail: `剩余 ${bytes(Math.max(0, n.remaining ?? 0), n.profile!.unit)}` })).sort((a, b) => b.value - a.value)
})
// Bars are relative to the top server, except usage rate which is an absolute percentage.
const scale = computed(() => mode.value === 'percent' ? 100 : Math.max(1, ...rows.value.map(r => r.value)))
const width = (value: number) => `${Math.max(value > 0 ? 1.5 : 0, Math.min(100, value / scale.value * 100))}%`
const empty = computed(() => mode.value === 'today' ? '暂无已安装 Agent 的服务器' : '暂无已校准额度的服务器')
</script>

<template>
  <section class="kpi rank-card">
    <div class="kpi-head"><span>流量排行 · {{ scope }}</span><i class="kpi-icon"><Trophy :size="17" /></i></div>
    <div class="rank-tabs" role="tablist" aria-label="排行依据">
      <button v-for="m in modes" :key="m.id" type="button" role="tab" :aria-selected="mode === m.id" :class="{ active: mode === m.id }" @click="mode = m.id">{{ m.name }}</button>
    </div>
    <p v-if="mode === 'today'" class="rank-legend"><span><i class="legend tx"></i>上传</span><span><i class="legend rx"></i>下载</span></p>
    <ol v-if="rows.length" class="rank-list">
      <li v-for="(row, index) in rows" :key="row.node.id">
        <button type="button" class="rank-row" :title="`${row.node.name}：${row.label}（${row.detail}）`" @click="emit('open', row.node.id)">
          <span class="rank-no" :class="`top${index + 1}`">{{ index + 1 }}</span>
          <span class="rank-main">
            <span class="rank-line"><strong>{{ row.node.name }}</strong><b>{{ row.label }}</b></span>
            <span class="rank-track">
              <template v-if="mode === 'today'">
                <i class="seg tx" :style="{ width: width(row.tx || 0) }"></i><i class="seg rx" :style="{ width: width(row.rx || 0) }"></i>
              </template>
              <i v-else class="seg" :class="mode === 'percent' && row.value >= 80 ? 'warn' : 'used'" :style="{ width: width(row.value) }"></i>
            </span>
            <span class="rank-detail">{{ row.detail }}</span>
          </span>
        </button>
      </li>
    </ol>
    <p v-else class="rank-empty">{{ empty }}</p>
  </section>
</template>
