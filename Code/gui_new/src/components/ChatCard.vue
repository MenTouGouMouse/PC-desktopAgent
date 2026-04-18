<script setup lang="ts">
// Feature: draggable-card-layout
// ChatCard — wraps ChatInterface (+ optional LogViewer tab) inside a resizable DraggableCard.

import { ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import DraggableCard from './DraggableCard.vue'
import ChatInterface from './ChatInterface.vue'
import LogViewer from './LogViewer.vue'
import { useLayoutStore } from '@/stores/layoutStore'

const store = useLayoutStore()
const { logDetached } = storeToRefs(store)

const activeTab = ref<'log' | 'chat'>('log')

// When logDetached becomes true, switch to chat tab automatically
watch(logDetached, (val) => {
  if (val) activeTab.value = 'chat'
})
</script>

<template>
  <DraggableCard card-id="chat" :resizable="true" :min-width="280" :min-height="200">
    <template #handle>
      <span class="drag-title">💬 AI 对话</span>
      <button
        class="btn btn-ghost sm detach-btn"
        @mousedown.stop
        @click="store.toggleLogDetached()"
      >
        {{ logDetached ? '⬆ 合并' : '⬇ 独立' }}
      </button>
    </template>

    <div class="chat-content">
      <!-- Tab bar — only shown when log is merged (logDetached=false) -->
      <div v-if="!logDetached" class="panel-header">
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'log' }"
          @click="activeTab = 'log'"
        >
          📋 执行日志
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'chat' }"
          @click="activeTab = 'chat'"
        >
          💬 AI 对话
        </button>
      </div>

      <div class="panel-body">
        <LogViewer v-show="!logDetached && activeTab === 'log'" />
        <ChatInterface v-show="logDetached || activeTab === 'chat'" />
      </div>
    </div>
  </DraggableCard>
</template>

<style scoped>
.drag-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  flex: 1;
}

.detach-btn {
  font-size: 10px;
  padding: 3px 8px;
  opacity: 0.7;
  flex-shrink: 0;
}

.detach-btn:hover {
  opacity: 1;
}

.chat-content {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  align-items: stretch;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  background: rgba(255, 255, 255, 0.05);
  padding: 0 4px;
}

html.dark .panel-header {
  background: rgba(255, 255, 255, 0.03);
}

.tab-btn {
  flex: 1;
  padding: 8px 6px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font);
  cursor: pointer;
  transition: color 0.18s, border-color 0.18s;
}

.tab-btn:hover {
  color: var(--text);
}

.tab-btn.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.panel-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>
