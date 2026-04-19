// Feature: draggable-card-layout
// Pinia store for managing draggable card positions, sizes, and logDetached state.

import { defineStore } from 'pinia'
import { ref, onMounted, onUnmounted } from 'vue'
import {
  type CardId,
  type CardState,
  type LayoutData,
  clamp,
  computeDefaultLayout,
  parseStoredLayout,
} from '@/utils/layout'

export const STORAGE_KEY = 'draggable-card-layout'
const LAYOUT_VERSION = 2  // bump this to force reset on breaking layout changes

export { type CardId, type CardState, type LayoutData }

export const useLayoutStore = defineStore('layout', () => {
  // ── State ──────────────────────────────────────────────────────────────────
  function loadInitialState(): { cards: Record<CardId, CardState>; logDetached: boolean } {
    try {
      const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
      const parsed = parseStoredLayout(raw)
      if (parsed) {
        // Validate that stored layout has reasonable dimensions (not from a broken init)
        const p = parsed.cards.preview
        if (p.width > 100 && p.height > 50) return parsed
      }
    } catch (e) {
      console.warn('[layoutStore] Failed to read localStorage, using default layout', e)
    }
    return {
      cards: computeDefaultLayout(
        typeof window !== 'undefined' ? window.innerWidth : 1440,
        typeof window !== 'undefined' ? window.innerHeight : 900,
      ),
      logDetached: false,
    }
  }

  const initial = loadInitialState()

  const cards = ref<Record<CardId, CardState>>(initial.cards)
  const logDetached = ref<boolean>(initial.logDetached)
  const isResetting = ref<boolean>(false)

  // ── Debounced localStorage write ───────────────────────────────────────────

  let saveTimer: ReturnType<typeof setTimeout> | null = null

  function scheduleSave(): void {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => {
      try {
        const data: LayoutData = {
          cards: cards.value,
          logDetached: logDetached.value,
        }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
      } catch (e) {
        console.warn('[layoutStore] Failed to save layout to localStorage', e)
      }
    }, 300)
  }

  // ── Methods ────────────────────────────────────────────────────────────────

  function updateCard(id: CardId, patch: Partial<CardState>): void {
    cards.value = {
      ...cards.value,
      [id]: { ...cards.value[id], ...patch },
    }
    scheduleSave()
  }

  function resetToDefault(): void {
    const vw = typeof document !== 'undefined'
      ? document.documentElement.clientWidth
      : (typeof window !== 'undefined' ? window.innerWidth : 1440)
    const vh = typeof document !== 'undefined'
      ? document.documentElement.clientHeight
      : (typeof window !== 'undefined' ? window.innerHeight : 900)
    cards.value = computeDefaultLayout(vw, vh)
    isResetting.value = true
    setTimeout(() => {
      isResetting.value = false
    }, 300)
    scheduleSave()
  }

  function clampToViewport(): void {
    const vw = typeof document !== 'undefined'
      ? document.documentElement.clientWidth
      : (typeof window !== 'undefined' ? window.innerWidth : 1440)
    const vh = typeof document !== 'undefined'
      ? document.documentElement.clientHeight
      : (typeof window !== 'undefined' ? window.innerHeight : 900)
    const updated = { ...cards.value }
    const ids: CardId[] = ['preview', 'task', 'chat', 'toolbar']
    for (const id of ids) {
      const c = updated[id]
      const { x, y } = clamp(c.x, c.y, c.width, c.height, vw, vh)
      updated[id] = { ...c, x, y }
    }
    cards.value = updated
    scheduleSave()
  }

  function toggleLogDetached(): void {
    logDetached.value = !logDetached.value
    const vw = typeof document !== 'undefined'
      ? document.documentElement.clientWidth
      : (typeof window !== 'undefined' ? window.innerWidth : 1440)
    const vh = typeof document !== 'undefined'
      ? document.documentElement.clientHeight
      : (typeof window !== 'undefined' ? window.innerHeight : 900)
    const defaultLayout = computeDefaultLayout(vw, vh)
    if (logDetached.value) {
      // Expand task card to include log area
      const taskH = defaultLayout.task.height + 220
      const chatY = cards.value.task.y + taskH + 10
      const chatH = Math.max(200, vh - chatY - 60)
      cards.value = {
        ...cards.value,
        task: { ...cards.value.task, height: taskH },
        chat: { ...cards.value.chat, y: chatY, height: chatH },
      }
    } else {
      // Collapse task card back
      cards.value = {
        ...cards.value,
        task: { ...cards.value.task, height: defaultLayout.task.height },
        chat: { ...cards.value.chat, y: defaultLayout.chat.y, height: defaultLayout.chat.height },
      }
    }
    scheduleSave()
  }

  // ── Window resize listener ─────────────────────────────────────────────────

  function onResize(): void {
    clampToViewport()
  }

  if (typeof window !== 'undefined') {
    // Use onMounted-equivalent: register immediately (store is set up at app init)
    window.addEventListener('resize', onResize)
  }

  // ── Expose ─────────────────────────────────────────────────────────────────

  return {
    cards,
    logDetached,
    isResetting,
    updateCard,
    resetToDefault,
    clampToViewport,
    toggleLogDetached,
  }
})

// ── Legacy exports for backward compatibility ──────────────────────────────
// (kept so any existing imports of DEFAULT_LAYOUT / LayoutItem don't break)

export interface LayoutItem {
  i: string
  x: number
  y: number
  w: number
  h: number
  minW?: number
  minH?: number
}

export const DEFAULT_LAYOUT: LayoutItem[] = [
  { i: 'actions',  x: 0, y: 0,  w: 12, h: 5,  minW: 6, minH: 4 },
  { i: 'progress', x: 0, y: 5,  w: 12, h: 4,  minW: 6, minH: 3 },
  { i: 'panel',    x: 0, y: 9,  w: 12, h: 13, minW: 6, minH: 6 },
]
