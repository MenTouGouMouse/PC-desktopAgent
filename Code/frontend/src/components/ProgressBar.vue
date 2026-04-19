<template>
  <div class="progress-track">
    <div
      class="progress-fill"
      :class="{ 'btn-glow': isRunning, 'error-state': isError }"
      :style="{ width: percent + '%' }"
    ></div>
    <span class="progress-label" :class="{ 'error-label': isError }">
      {{ isError ? '⚠' : '' }} {{ percent }}%
    </span>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  percent: number
  isRunning: boolean
  statusText?: string
}>()

const isError = computed(() => !props.isRunning && (props.statusText?.includes('⚠') || props.statusText?.includes('出错') || props.statusText?.includes('异常')))

import { computed } from 'vue'
</script>

<style scoped>
.progress-track {
  position: relative;
  background: var(--bg-secondary);
  height: 8px;
  border-radius: 4px;
  overflow: visible;
}

.progress-fill {
  height: 100%;
  border-radius: 4px;
  background: var(--gradient-progress);
  transition: width 0.3s ease;
}

.progress-fill.btn-glow {
  animation: btn-glow 1.5s ease-in-out infinite;
}

.progress-fill.error-state {
  background: linear-gradient(90deg, #f59e0b, #ef4444);
  animation: none;
}

.error-label {
  color: #f59e0b;
}

.progress-label {
  position: absolute;
  right: 0;
  top: -20px;
  font-size: 12px;
  font-weight: bold;
  color: var(--text-muted);
}
</style>
