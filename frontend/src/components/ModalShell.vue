<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { X } from 'lucide-vue-next'
defineProps<{ title: string; wide?: boolean; drawer?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const box = ref<HTMLElement>(); const titleId = useId(); let previous: Element | null; let oldOverflow = ''
function key(event: KeyboardEvent) { if (event.key === 'Escape') { event.stopPropagation(); emit('close') }; if (event.key === 'Tab' && box.value) { const items = [...box.value.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href],[tabindex="0"]')].filter(el => el.offsetParent !== null); const first = items[0], last = items.at(-1); if (!first) { event.preventDefault(); return }; if (event.shiftKey && (document.activeElement === first || document.activeElement === box.value)) { event.preventDefault(); last?.focus() } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() } } }
onMounted(async () => { previous = document.activeElement; oldOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; document.addEventListener('keydown', key); await nextTick(); box.value?.focus() })
onBeforeUnmount(() => { document.removeEventListener('keydown', key); document.body.style.overflow = oldOverflow; if (previous instanceof HTMLElement) previous.focus() })
</script>
<template><Teleport to="body"><div class="modal-layer" :class="{ drawer }" @mousedown.self="emit('close')"><section ref="box" tabindex="-1" role="dialog" aria-modal="true" :aria-labelledby="titleId" class="modal" :class="{ wide, drawer }"><header class="modal-header"><h2 :id="titleId">{{ title }}</h2><button class="icon-button" aria-label="关闭对话框" @click="emit('close')"><X :size="20" /></button></header><div class="modal-body"><slot /></div></section></div></Teleport></template>
