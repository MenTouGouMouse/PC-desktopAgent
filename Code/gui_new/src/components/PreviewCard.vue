<script setup lang="ts">
// Feature: draggable-card-layout
// PreviewCard — wraps PreviewPanel + perim SVG inside a DraggableCard.

import { ref, onMounted, onUnmounted } from 'vue'
import DraggableCard from './DraggableCard.vue'
import PreviewPanel from './PreviewPanel.vue'

defineProps<{
  percent: number
}>()

defineEmits<{
  openSettings: []
}>()

// ── Perim SVG resize tracking ──────────────────────────────
const cardRef = ref<HTMLElement | null>(null)
const svgWidth = ref(0)
const svgHeight = ref(0)
const svgPerimeter = ref(0)

let ro: ResizeObserver | null = null

function updateSvgSize(w: number, h: number): void {
  svgWidth.value = w
  svgHeight.value = h
  svgPerimeter.value = 2 * (w + h)
}

onMounted(() => {
  // DraggableCard renders as .draggable-card — find it via the wrapper
  const el = cardRef.value
  if (!el) return
  const card = el.closest('.draggable-card') as HTMLElement | null
  const target = card ?? el
  updateSvgSize(target.offsetWidth, target.offsetHeight)
  ro = new ResizeObserver((entries) => {
    const entry = entries[0]
    if (entry) {
      const { width, height } = entry.contentRect
      updateSvgSize(width, height)
    }
  })
  ro.observe(target)
})

onUnmounted(() => {
  ro?.disconnect()
})
</script>

<template>
  <div ref="cardRef" class="preview-card-wrapper">
    <DraggableCard card-id="preview" :aspect-ratio="16 / 9">
      <template #handle>
        <!-- Simplified toolbar as drag handle; buttons use @mousedown.stop -->
        <span class="drag-title">🖥 实时预览</span>
      </template>

      <!-- PreviewPanel fills the content area -->
      <PreviewPanel @open-settings="$emit('openSettings')" />

      <!-- Perim SVG overlay — tracks card size via ResizeObserver -->
      <svg
        v-if="svgWidth > 0"
        class="perim-svg"
        :width="svgWidth"
        :height="svgHeight"
        :viewBox="`0 0 ${svgWidth} ${svgHeight}`"
        xmlns="http://www.w3.org/2000/svg"
      >
        <rect
          x="1"
          y="1"
          :width="svgWidth - 2"
          :height="svgHeight - 2"
          rx="12"
          ry="12"
          fill="none"
          stroke="var(--accent)"
          stroke-width="2"
          stroke-opacity="0.5"
          :stroke-dasharray="svgPerimeter"
          :stroke-dashoffset="svgPerimeter - (svgPerimeter * Math.min(100, Math.max(0, percent)) / 100)"
          class="perim-path"
        />
      </svg>
    </DraggableCard>
  </div>
</template>

<style scoped>
.preview-card-wrapper {
  display: contents;
}

.drag-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

.perim-svg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 20;
  border-radius: var(--r-card);
  overflow: visible;
}

.perim-path {
  transition: stroke-dashoffset 0.45s cubic-bezier(0.2, 0.9, 0.4, 1.05);
}
</style>
