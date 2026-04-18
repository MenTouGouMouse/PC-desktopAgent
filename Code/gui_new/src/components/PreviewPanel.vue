<template>
  <div class="preview-panel glass">

    <div class="toolbar">
      <span class="label">实时预览</span>
      <div class="actions">
        <button class="btn btn-ghost sm theme-toggle" @click="handleToggleTheme" :title="isDark ? '切换浅色' : '切换深色'">
          {{ isDark ? '☀️' : '🌙' }}
        </button>
        <button
          class="btn btn-ghost sm"
          :class="{ 'active-box': showBoxes }"
          @click="toggleBoxes"
        >{{ showBoxes ? '✅ 识别框' : '🔍 识别框' }}</button>
        <button class="btn btn-ghost sm" @click="emit('openSettings')">⚙️ 路径设置</button>
        <button class="btn btn-ghost sm" @click="paused = !paused">
          {{ paused ? '▶ 恢复' : '⏸ 暂停' }}
        </button>
      </div>
    </div>
    <div class="frame-area">
      <img v-if="src" :src="src" class="frame-img" alt="screen" />
      <div v-else class="placeholder">
        <span class="icon">🖥️</span>
        <span>等待屏幕预览…</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { usePyWebView } from '../composables/usePyWebView'
import { useThemeStore } from '../stores/themeStore'

const emit = defineEmits<{ openSettings: []; toggleTheme: [] }>()

const themeStore = useThemeStore()
const isDark = computed(() => themeStore.activeTheme === 'Dark')

function handleToggleTheme(): void {
  themeStore.setTheme(isDark.value ? 'Light' : 'Dark')
  emit('toggleTheme')
}

const src = ref('')
const paused = ref(false)
const showBoxes = ref(false)
const api = usePyWebView()

let lastRender = 0
let pending: string | null = null
let rafId: number | null = null

function scheduleRender() {
  if (rafId !== null) return
  rafId = requestAnimationFrame((now) => {
    rafId = null
    if (now - lastRender >= 100 && pending !== null) {
      src.value = 'data:image/jpeg;base64,' + pending
      pending = null
      lastRender = now
    } else if (pending !== null) {
      scheduleRender()
    }
  })
}

async function toggleBoxes() {
  showBoxes.value = !showBoxes.value
  try { await api.setShowBoxes(showBoxes.value) }
  catch { showBoxes.value = !showBoxes.value }
}

onMounted(() => {
  window.updateFrame = (b64: string) => {
    if (!b64 || paused.value) return
    pending = b64
    scheduleRender()
  }
})
</script>

<style scoped>
.preview-panel {
  width: 100%; height: 100%;
  display: flex; flex-direction: column;
  padding: 0; overflow: hidden;
  -webkit-font-smoothing: antialiased;
  position: relative;
}

.preview-panel:hover {
  box-shadow: var(--shadow-h), 0 0 0 1px var(--accent-dim);
}

.toolbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 9px 13px; border-bottom: 1px solid var(--border); flex-shrink: 0;
}

.label {
  font-size: 11px; font-weight: 700; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: .6px;
}

.actions { display: flex; gap: 5px; }

.sm { padding: 4px 10px; font-size: 11.5px; border-radius: var(--r-sm); }
.theme-toggle { padding: 4px 8px; font-size: 14px; }

.active-box {
  background: var(--success-dim) !important;
  color: var(--success) !important;
  border-color: var(--success) !important;
}

.frame-area {
  flex: 1; min-height: 0; display: flex;
  align-items: center; justify-content: center;
  background: #000;
  overflow: hidden;
  padding: 6px;
  transition: none !important;
  /* Force independent compositing layer — prevents WebView2 repaint flash on theme switch */
  transform: translateZ(0);
  isolation: isolate;
  will-change: contents;
  contain: strict;
}

.frame-img {
  width: 100%; height: 100%; object-fit: contain; display: block;
  border-radius: 8px;
  transform: translateZ(0);
  transition: none !important;
  /* Prevent any compositor layer promotion changes from causing flash */
  will-change: auto;
  isolation: isolate;
}

.placeholder {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  color: var(--text-muted); font-size: 13px;
}
.icon { font-size: 32px; opacity: .35; }
</style>
