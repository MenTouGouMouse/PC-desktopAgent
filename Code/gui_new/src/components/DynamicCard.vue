<template>
  <div v-ripple class="dynamic-card" :data-card-id="cardId">
    <div class="card-header drag-handle">
      <span class="card-title">{{ title }}</span>
    </div>
    <div class="card-body" :class="{ 'no-pad': noPadding }">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  cardId: string
  noPadding?: boolean
}>()
</script>

<style scoped>
.dynamic-card {
  display: flex;
  flex-direction: column;
  height: 100%;
  border-radius: var(--r-card);
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  box-shadow:
    0 4px 16px rgba(0, 0, 0, 0.08),
    0 1px 4px rgba(0, 0, 0, 0.04);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  overflow: hidden;
}

.dynamic-card:hover {
  transform: translateY(-2px) scale(1.01);
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.12),
    0 2px 8px rgba(0, 0, 0, 0.06);
}

html.dark .dynamic-card {
  background: rgba(30, 30, 40, 0.7);
  border-color: rgba(255, 255, 255, 0.08);
  box-shadow:
    0 4px 16px rgba(0, 0, 0, 0.3),
    0 1px 4px rgba(0, 0, 0, 0.2);
}

html.dark .dynamic-card:hover {
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.4),
    0 2px 8px rgba(0, 0, 0, 0.25);
}

.card-header {
  display: flex;
  align-items: center;
  padding: 8px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.08);
  cursor: grab;
  flex-shrink: 0;
  user-select: none;
}

.card-header:active {
  cursor: grabbing;
}

html.dark .card-header {
  border-bottom-color: rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.04);
}

.card-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

.card-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
}

.card-body.no-pad {
  padding: 0;
}
</style>
