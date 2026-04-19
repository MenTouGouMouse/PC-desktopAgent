<template>
  <div class="card-grid-container">

    <!-- 上方：任务控制 + 进度条 合并卡片 -->
    <div v-ripple class="top-card island-card">
      <div class="ctrl-section">
        <ActionsCard :is-running="isRunning" />
      </div>
      <div class="prog-section">
        <GlassProgressBar :percent="percent" :is-running="isRunning" :status-text="statusText" />
      </div>
      <!-- 独立日志面板 -->
      <div v-if="logDetached" class="detached-log">
        <LogViewer />
      </div>
    </div>

    <!-- 下方：执行日志 / AI 对话 -->
    <div v-ripple class="panel-card island-card">
      <div class="panel-header">
        <button v-if="!logDetached" class="tab-btn" :class="{ active: activeTab === 'log' }" @click="activeTab = 'log'">
          📋 执行日志
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'chat' }" @click="activeTab = 'chat'">
          💬 AI 对话
        </button>
        <button class="tab-btn switch-btn" :class="{ active: logDetached }" @click="toggleDetach" title="切换日志显示位置">
          {{ logDetached ? '⬆ 合并' : '⬇ 独立' }}
        </button>
      </div>
      <div class="panel-body">
        <template v-if="!logDetached">
          <LogViewer v-show="activeTab === 'log'" />
        </template>
        <ChatInterface v-show="activeTab === 'chat'" />
      </div>
    </div>

    <!-- Footer -->
    <div class="grid-footer">
      <button class="btn btn-ghost reset-btn" title="恢复默认布局" @click="resetLayout">⊞ 默认</button>
      <button class="btn btn-ghost min-btn" @click="minimize">⬇ 悬浮球</button>
      <div class="tsw-wrap" ref="tswRoot">
        <div v-if="tswOpen" class="tsw-menu">
          <div
            v-for="t in themes" :key="t.value"
            class="tsw-item"
            :class="{ 'tsw-item--active': t.value === currentTheme }"
            @mousedown.prevent="pickTheme(t.value)"
          >
            <span class="tsw-dot" :style="{ background: t.color }"></span>
            {{ t.label }}
            <span v-if="t.value === currentTheme" class="tsw-check">✓</span>
          </div>
        </div>
        <button
          class="btn btn-ghost theme-btn"
          :class="{ 'theme-btn--open': tswOpen }"
          @click.stop="tswOpen = !tswOpen"
        >🎨 主题</button>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { usePyWebView } from '../composables/usePyWebView'
import { useThemeStore } from '../stores/themeStore'
import { useLayoutStore } from '../stores/layoutStore'
import type { ThemeName } from '../stores/themeStore'
import ActionsCard from './ActionsCard.vue'
import GlassProgressBar from './GlassProgressBar.vue'
import LogViewer from './LogViewer.vue'
import ChatInterface from './ChatInterface.vue'

defineProps<{
  percent: number
  isRunning: boolean
  statusText: string
}>()

const api = usePyWebView()
const activeTab = ref<'log' | 'chat'>('log')
const logDetached = ref(false)

function toggleDetach() {
  logDetached.value = !logDetached.value
  if (logDetached.value) activeTab.value = 'chat'
}

function minimize() {
  try { api.minimizeToBall() }
  catch (e) { console.warn('[CardGrid] minimize error:', e) }
}

function resetLayout() {
  try { useLayoutStore().resetToDefault() } catch { /* ignore */ }
}

// ── Theme switcher ────────────────────────────────────────
const themeStore = useThemeStore()
const { activeTheme: currentTheme } = storeToRefs(themeStore)
const tswOpen = ref(false)
const tswRoot = ref<HTMLElement | null>(null)
const themes: { value: ThemeName; label: string; color: string }[] = [
  { value: 'Dark',        label: 'Dark',        color: '#7b8cde' },
  { value: 'Light',       label: 'Light',       color: '#4a5bc4' },
  { value: 'Canva-Color', label: 'Canva-Color', color: '#00d4ff' },
]
function pickTheme(t: ThemeName) { themeStore.setTheme(t); tswOpen.value = false }
function onOutside(e: MouseEvent) {
  if (tswRoot.value && !tswRoot.value.contains(e.target as Node)) tswOpen.value = false
}
onMounted(() => document.addEventListener('mousedown', onOutside))
onUnmounted(() => document.removeEventListener('mousedown', onOutside))
</script>

<style scoped>
.card-grid-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
  /* Do NOT set overflow:hidden here — it clips the ThemeSwitcher dropdown */
  overflow: visible;
  contain: layout;
}

.island-card {
  position: relative;
  border-radius: var(--r-card);
  border: 1px solid var(--border);
  background: var(--glass);
  backdrop-filter: blur(var(--blur));
  -webkit-backdrop-filter: blur(var(--blur));
  box-shadow: var(--shadow);
  overflow: hidden;
  transition: transform 0.22s cubic-bezier(.34,1.56,.64,1), box-shadow 0.22s ease;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

.island-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-h), 0 0 0 1px var(--accent-dim);
}

.island-card > * { position: relative; z-index: 1; }

.top-card {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  max-height: 60%;
}

.ctrl-section { padding: 10px 14px 8px; }
.prog-section  { padding: 0 14px 10px; }

.detached-log {
  border-top: 1px solid var(--border);
  height: 180px;
  overflow-y: auto;
  flex-shrink: 0;
}

.panel-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  align-items: stretch;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  background: rgba(255,255,255,.05);
  padding: 0 4px;
}
html.dark .panel-header { background: rgba(255,255,255,.03); }

.tab-btn {
  flex: 1; padding: 8px 6px;
  background: transparent; border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  color: var(--text-muted); font-size: 12px; font-weight: 600;
  font-family: var(--font); cursor: pointer;
  transition: color .18s, border-color .18s;
}
.tab-btn:hover { color: var(--text); }
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }

.switch-btn {
  flex: none; padding: 8px 10px;
  font-size: 10px; opacity: .6;
  border-left: 1px solid var(--border);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.switch-btn:hover { opacity: 1; color: var(--text); }
.switch-btn.active { color: var(--accent); opacity: 1; border-bottom-color: var(--accent); }

.panel-body {
  flex: 1; min-height: 0; overflow: hidden;
  display: flex; flex-direction: column;
}

.grid-footer {
  flex-shrink: 0;
  display: flex; align-items: center; gap: 6px;
  padding: 4px 0;
  overflow: visible;
  position: relative;
  z-index: 200;
}

/* 三个按钮等宽 */
.reset-btn, .min-btn, .tsw-wrap {
  flex: 1;
}

.reset-btn {
  font-size: 11px; padding: 5px 6px;
  justify-content: center;
  opacity: .7;
}
.reset-btn:hover { opacity: 1; }

.min-btn {
  font-size: 11px; padding: 5px 6px;
  justify-content: center;
  white-space: nowrap;
}

/* 主题切换包装 */
.tsw-wrap {
  position: relative;
  display: flex;
}

.theme-btn {
  flex: 1;
  width: 100%;
  font-size: 11px; padding: 5px 6px;
  justify-content: center;
  white-space: nowrap;
}
.theme-btn--open {
  background: var(--accent-dim) !important;
  color: var(--text) !important;
  border-color: var(--accent) !important;
}

/* 主题菜单向上弹出 */
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
  display: flex; align-items: center; gap: 10px;
  padding: 9px 14px; border-radius: 8px;
  cursor: pointer; font-size: 13px; font-weight: 600;
  color: var(--text-muted); user-select: none;
}
.tsw-item:hover { background: var(--accent-dim); color: var(--text); }
.tsw-item--active { color: var(--accent); background: var(--accent-dim); }
.tsw-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.tsw-check { margin-left: auto; color: var(--accent); font-weight: 800; font-size: 12px; }
</style>
