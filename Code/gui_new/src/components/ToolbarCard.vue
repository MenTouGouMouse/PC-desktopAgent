<script setup lang="ts">
import DraggableCard from './DraggableCard.vue'
import { useLayoutStore } from '@/stores/layoutStore'
import { usePyWebView } from '@/composables/usePyWebView'

const store = useLayoutStore()
const api = usePyWebView()

function minimize(): void {
  try { api.minimizeToBall() }
  catch (e) { console.warn('[ToolbarCard] minimize error:', e) }
}
</script>

<template>
  <DraggableCard card-id="toolbar">
    <template #handle>
      <span class="drag-grip">⠿</span>
      <button class="btn btn-ghost sm" @mousedown.stop @click="store.resetToDefault()">⊞ 默认布局</button>
      <button class="btn btn-ghost sm" @mousedown.stop @click="minimize">⬇ 最小化</button>
    </template>
  </DraggableCard>
</template>

<style scoped>
.drag-grip {
  font-size: 14px;
  color: var(--text-muted);
  opacity: 0.5;
  cursor: grab;
  flex-shrink: 0;
}
</style>
