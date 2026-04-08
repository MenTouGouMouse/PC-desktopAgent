<template>
  <div class="progress-track">
    <div
      class="progress-fill"
      :class="{ 'btn-glow': isRunning }"
      :style="{ width: percent + '%' }"
    ></div>
    <span class="progress-label">{{ percent }}%</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  percent: number
  isRunning: boolean
}>()
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

.progress-label {
  position: absolute;
  right: 0;
  top: -20px;
  font-size: 12px;
  font-weight: bold;
  color: var(--text-muted);
}
</style>
