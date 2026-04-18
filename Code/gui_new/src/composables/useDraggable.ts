// Feature: draggable-card-layout
// Composable for per-card drag and resize logic using native mouse events.

import { ref, computed, onUnmounted } from 'vue'
import type { ComputedRef, Ref, CSSProperties } from 'vue'
import { clamp } from '@/utils/layout'
import type { CardId } from '@/utils/layout'
import { useLayoutStore } from '@/stores/layoutStore'

export interface UseDraggableOptions {
  resizable?: boolean
  aspectRatio?: number  // e.g. 16/9
  minWidth?: number     // default 200
  minHeight?: number    // default 150
}

export function useDraggable(
  cardId: CardId,
  options: UseDraggableOptions = {},
): {
  cardStyle: ComputedRef<CSSProperties>
  handleMousedown: (e: MouseEvent) => void
  resizeMousedown: (e: MouseEvent) => void
  isDragging: Ref<boolean>
} {
  const store = useLayoutStore()
  const { resizable = false, aspectRatio, minWidth = 200, minHeight = 150 } = options

  const isDragging = ref(false)

  // ── Drag state ─────────────────────────────────────────────────────────────
  let startMouseX = 0
  let startMouseY = 0
  let startCardX = 0
  let startCardY = 0

  function onDragMove(e: MouseEvent): void {
    const vw = window.innerWidth
    const vh = window.innerHeight
    const card = store.cards[cardId]
    const rawX = startCardX + (e.clientX - startMouseX)
    const rawY = startCardY + (e.clientY - startMouseY)
    const { x, y } = clamp(rawX, rawY, card.width, card.height, vw, vh)
    store.updateCard(cardId, { x, y })
  }

  function onDragUp(): void {
    document.removeEventListener('mousemove', onDragMove)
    document.removeEventListener('mouseup', onDragUp)
    isDragging.value = false
  }

  function handleMousedown(e: MouseEvent): void {
    e.preventDefault()
    startMouseX = e.clientX
    startMouseY = e.clientY
    startCardX = store.cards[cardId].x
    startCardY = store.cards[cardId].y
    isDragging.value = true
    document.addEventListener('mousemove', onDragMove)
    document.addEventListener('mouseup', onDragUp)
  }

  // ── Resize state ───────────────────────────────────────────────────────────
  let resizeStartMouseX = 0
  let resizeStartMouseY = 0
  let resizeStartWidth = 0
  let resizeStartHeight = 0

  function onResizeMove(e: MouseEvent): void {
    const deltaX = e.clientX - resizeStartMouseX
    const deltaY = e.clientY - resizeStartMouseY

    let newWidth = Math.max(resizeStartWidth + deltaX, minWidth)
    let newHeight: number

    if (aspectRatio != null) {
      // Lock aspect ratio: only width drives the resize
      newHeight = newWidth / aspectRatio
    } else {
      newHeight = Math.max(resizeStartHeight + deltaY, minHeight)
    }

    store.updateCard(cardId, { width: newWidth, height: newHeight })
  }

  function onResizeUp(): void {
    document.removeEventListener('mousemove', onResizeMove)
    document.removeEventListener('mouseup', onResizeUp)
  }

  function resizeMousedown(e: MouseEvent): void {
    if (!resizable) return
    e.preventDefault()
    e.stopPropagation()
    resizeStartMouseX = e.clientX
    resizeStartMouseY = e.clientY
    resizeStartWidth = store.cards[cardId].width
    resizeStartHeight = store.cards[cardId].height
    document.addEventListener('mousemove', onResizeMove)
    document.addEventListener('mouseup', onResizeUp)
  }

  // ── cardStyle computed ─────────────────────────────────────────────────────
  const cardStyle = computed<CSSProperties>(() => {
    const { x, y, width, height } = store.cards[cardId]
    return {
      position: 'fixed',
      left: `${x}px`,
      top: `${y}px`,
      width: `${width}px`,
      height: `${height}px`,
      zIndex: isDragging.value ? 1000 : 100,
    }
  })

  // ── Cleanup ────────────────────────────────────────────────────────────────
  onUnmounted(() => {
    document.removeEventListener('mousemove', onDragMove)
    document.removeEventListener('mouseup', onDragUp)
    document.removeEventListener('mousemove', onResizeMove)
    document.removeEventListener('mouseup', onResizeUp)
  })

  return { cardStyle, handleMousedown, resizeMousedown, isDragging }
}
