<template>
  <div class="app">
    <!-- Left: preview 60% -->
    <div class="left">
      <div class="preview-wrap" ref="wrapRef">
        <svg
          v-if="svgReady"
          class="perim-svg"
          :viewBox="`0 0 ${svgW} ${svgH}`"
          aria-hidden="true"
        >
          <path class="perim-track" :d="pathD" />
          <path
            class="perim-fill"
            :d="pathD"
            :stroke-dasharray="perimLen"
            :stroke-dashoffset="perimOffset"
          />
        </svg>
        <PreviewPanel :percent="pct" @open-settings="settingsOpen = true" @toggle-theme="toggleTheme" />
      </div>
    </div>

    <!-- Right: controls 40% -->
    <div class="right">
      <CardGrid
        :percent="pct"
        :is-running="running"
        :status-text="status"
      />
    </div>

    <SettingsDialog :visible="settingsOpen" @close="settingsOpen = false" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import PreviewPanel from './components/PreviewPanel.vue'
import CardGrid from './components/CardGrid.vue'
import SettingsDialog from './components/SettingsDialog.vue'

const pct = ref(0)
const running = ref(false)
const status = ref('就绪')
const dark = ref(document.documentElement.classList.contains('dark'))
const settingsOpen = ref(false)

// ── Perimeter progress SVG ──────────────────────────────────
const wrapRef = ref<HTMLElement | null>(null)
const svgW = ref(800)
const svgH = ref(450)
const svgReady = ref(false)
const sw = 3
const r = 14

const pathD = computed(() => {
  const x = sw / 2
  const y = sw / 2
  const w = svgW.value - sw
  const h = svgH.value - sw
  const cx = x + w / 2
  return [
    `M ${cx} ${y}`,
    `L ${x + w - r} ${y}`,
    `A ${r} ${r} 0 0 1 ${x + w} ${y + r}`,
    `L ${x + w} ${y + h - r}`,
    `A ${r} ${r} 0 0 1 ${x + w - r} ${y + h}`,
    `L ${x + r} ${y + h}`,
    `A ${r} ${r} 0 0 1 ${x} ${y + h - r}`,
    `L ${x} ${y + r}`,
    `A ${r} ${r} 0 0 1 ${x + r} ${y}`,
    `L ${cx} ${y}`,
  ].join(' ')
})

const perimLen = computed(() => {
  const w = svgW.value - sw
  const h = svgH.value - sw
  return 2 * (w + h) - 8 * r + 2 * Math.PI * r
})

const perimOffset = computed(() => {
  const p = Math.min(100, Math.max(0, pct.value))
  return perimLen.value * (1 - p / 100)
})

let ro: ResizeObserver | null = null

function toggleTheme() {
  dark.value = !dark.value
  document.documentElement.classList.toggle('dark', dark.value)
}

onMounted(() => {
  window.updateProgress = (p, t, r) => {
    pct.value = p
    status.value = t || (r ? '运行中' : '就绪')
    running.value = r
  }

  if (wrapRef.value) {
    const update = () => {
      const el = wrapRef.value
      if (!el) return
      svgW.value = el.offsetWidth
      svgH.value = el.offsetHeight
      svgReady.value = true
    }
    update()
    ro = new ResizeObserver(update)
    ro.observe(wrapRef.value)
  }

  const appEl = document.getElementById('app')
  if (appEl) {
    appEl.addEventListener('mouseenter', (e) => {
      const target = e.target as Element
      if (!target.closest('.island-card, .dynamic-card')) return
      appEl.classList.remove('pulse-active')
      void appEl.offsetWidth
      appEl.classList.add('pulse-active')
    }, { capture: true })

    appEl.addEventListener('animationend', (e) => {
      if ((e as AnimationEvent).animationName === 'globalPulse') {
        appEl.classList.remove('pulse-active')
      }
    })
  }
})

onUnmounted(() => {
  ro?.disconnect()
})
</script>

<style scoped>
.app {
  display: flex; flex-direction: row;
  width: 100vw; height: 100vh; overflow: hidden;
  background: var(--bg-grad);
  gap: 10px; padding: 10px; position: relative;
}

.left {
  flex: 65; min-width: 0; height: 100%;
  display: flex; align-items: flex-start; justify-content: flex-start;
}

.right { flex: 35; min-width: 300px; max-width: 480px; height: 100%; overflow: hidden; }

/* ThemeSwitcher anchor removed — theme switcher is now in CardGrid footer */

.preview-wrap {
  height: 100%;
  aspect-ratio: 16 / 9;
  max-width: 100%;
  flex-shrink: 0;
  position: relative;
}

.perim-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 20;
  overflow: visible;
}

.perim-track {
  fill: none;
  stroke: rgba(255,255,255,.10);
  stroke-width: 3;
}

.perim-fill {
  fill: none;
  stroke: var(--accent);
  stroke-width: 3;
  stroke-linecap: round;
  transition: stroke-dashoffset .45s cubic-bezier(.2,.9,.4,1.05);
  filter: drop-shadow(0 0 5px var(--accent-glow));
}
</style>
