<template>
  <div class="tsw" ref="root">
    <!-- Theme menu — opens upward, above the button -->
    <div v-if="open" class="tsw-menu">
      <div
        v-for="t in themes"
        :key="t.value"
        class="tsw-item"
        :class="{ 'tsw-item--active': t.value === activeTheme }"
        @mousedown.prevent="pick(t.value)"
      >
        <span class="tsw-dot" :style="{ background: t.color }"></span>
        {{ t.label }}
        <span v-if="t.value === activeTheme" class="tsw-check">✓</span>
      </div>
    </div>

    <!-- Trigger button -->
    <button
      class="btn btn-ghost sm tsw-btn"
      :class="{ 'tsw-btn--open': open }"
      @click.stop="toggle"
    >
      🎨 主题
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useThemeStore } from '../stores/themeStore'
import type { ThemeName } from '../stores/themeStore'

const store = useThemeStore()
const { activeTheme } = storeToRefs(store)

const themes: { value: ThemeName; label: string; color: string }[] = [
  { value: 'Dark',        label: 'Dark',        color: '#7b8cde' },
  { value: 'Light',       label: 'Light',       color: '#4a5bc4' },
  { value: 'Canva-Color', label: 'Canva-Color', color: '#00d4ff' },
]

const open = ref(false)
const root = ref<HTMLElement | null>(null)

function toggle() { open.value = !open.value }
function pick(t: ThemeName) { store.setTheme(t); open.value = false }

function outside(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) open.value = false
}
onMounted(() => document.addEventListener('mousedown', outside))
onUnmounted(() => document.removeEventListener('mousedown', outside))
</script>

<style scoped>
.tsw {
  position: relative;
  display: inline-block;
  flex-shrink: 0;
  width: 100%;
}

.tsw-btn {
  font-size: 12px;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  width: 100%;
  justify-content: center;
}

.tsw-btn--open {
  background: var(--accent-dim) !important;
  color: var(--text) !important;
  border-color: var(--accent) !important;
}

/* Menu opens ABOVE the button, anchored to right edge */
.tsw-menu {
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  min-width: 160px;
  padding: 6px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--glass);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  box-shadow: 0 -4px 24px rgba(0,0,0,.5), 0 2px 8px rgba(0,0,0,.3);
  z-index: 9999;
}

.tsw-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  user-select: none;
}

.tsw-item:hover {
  background: var(--accent-dim);
  color: var(--text);
}

.tsw-item--active {
  color: var(--accent);
  background: var(--accent-dim);
}

.tsw-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.tsw-check {
  margin-left: auto;
  color: var(--accent);
  font-weight: 800;
  font-size: 12px;
}
</style>
