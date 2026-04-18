<script setup lang="ts">
// Feature: draggable-card-layout
// TaskCard — wraps ActionsCard + GlassProgressBar, optionally LogViewer when logDetached.

import { storeToRefs } from 'pinia'
import DraggableCard from './DraggableCard.vue'
import ActionsCard from './ActionsCard.vue'
import GlassProgressBar from './GlassProgressBar.vue'
import LogViewer from './LogViewer.vue'
import { useLayoutStore } from '@/stores/layoutStore'

defineProps<{
  percent: number
  isRunning: boolean
  statusText: string
}>()

const store = useLayoutStore()
const { logDetached } = storeToRefs(store)
</script>

<template>
  <DraggableCard card-id="task" title="⚡ 任务控制">
    <div class="task-content">
      <div class="ctrl-section">
        <ActionsCard :is-running="isRunning" />
      </div>
      <div class="prog-section">
        <GlassProgressBar :percent="percent" :is-running="isRunning" :status-text="statusText" />
      </div>
      <div v-if="logDetached" class="detached-log">
        <LogViewer />
      </div>
    </div>
  </DraggableCard>
</template>

<style scoped>
.task-content {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.ctrl-section {
  padding: 10px 14px 8px;
  flex-shrink: 0;
}

.prog-section {
  padding: 0 14px 10px;
  flex-shrink: 0;
}

.detached-log {
  border-top: 1px solid var(--border);
  flex: 1;
  min-height: 150px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
</style>
