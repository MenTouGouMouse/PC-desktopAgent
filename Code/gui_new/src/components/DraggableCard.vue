<script setup lang="ts">
// Feature: draggable-card-layout
// Generic draggable card container component.

import { computed } from 'vue'
import type { CardId } from '@/utils/layout'
import { useDraggable } from '@/composables/useDraggable'
import { useLayoutStore } from '@/stores/layoutStore'

interface Props {
  cardId: CardId
  title?: string
  resizable?: boolean
  aspectRatio?: number
  minWidth?: number
  minHeight?: number
}

const props = withDefaults(defineProps<Props>(), {
  resizable: false,
})

const store = useLayoutStore()

const { cardStyle, handleMousedown, resizeMousedown, isDragging } = useDraggable(props.cardId, {
  resizable: props.resizable,
  aspectRatio: props.aspectRatio,
  minWidth: props.minWidth,
  minHeight: props.minHeight,
})

const isResetting = computed(() => store.isResetting)
</script>

<template>
  <div
    class="draggable-card glass"
    :style="cardStyle"
    :class="{ dragging: isDragging, resetting: isResetting }"
  >
    <!-- 标题栏 / Drag Handle -->
    <div class="drag-handle" @mousedown="handleMousedown">
      <slot name="handle">
        <span class="drag-title">{{ title }}</span>
      </slot>
    </div>
    <!-- 内容区 -->
    <div class="card-content">
      <slot />
    </div>
    <!-- Resize handle（仅 resizable=true 时渲染） -->
    <div v-if="resizable" class="resize-handle" @mousedown.stop="resizeMousedown" />
  </div>
</template>

<style scoped>
.draggable-card {
  position: fixed;
  border-radius: var(--r-card);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.drag-handle {
  cursor: grab;
  padding: 8px 12px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  user-select: none;
  display: flex;
  align-items: center;
  gap: 8px;
}

.dragging .drag-handle {
  cursor: grabbing;
}

.dragging {
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.35), 0 0 0 2px var(--accent-dim);
  transition: none !important;
}

.resetting {
  transition:
    left 300ms cubic-bezier(0.34, 1.56, 0.64, 1),
    top 300ms cubic-bezier(0.34, 1.56, 0.64, 1) !important;
}

.card-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.resize-handle {
  position: absolute;
  bottom: 0;
  right: 0;
  width: 16px;
  height: 16px;
  cursor: se-resize;
  opacity: 0.4;
}

.resize-handle:hover {
  opacity: 0.8;
}

.drag-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}
</style>
