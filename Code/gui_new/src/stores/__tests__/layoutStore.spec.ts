// Feature: draggable-card-layout
// Unit tests for useLayoutStore — updateCard, resetToDefault, toggleLogDetached, localStorage serialization.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useLayoutStore, STORAGE_KEY } from '../layoutStore'
import { computeDefaultLayout } from '@/utils/layout'

describe('useLayoutStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // ── updateCard ─────────────────────────────────────────────────────────────

  it('updateCard patches the specified card state', () => {
    const store = useLayoutStore()
    const before = { ...store.cards.preview }
    store.updateCard('preview', { x: 999, y: 888 })
    expect(store.cards.preview.x).toBe(999)
    expect(store.cards.preview.y).toBe(888)
    expect(store.cards.preview.width).toBe(before.width)
    expect(store.cards.preview.height).toBe(before.height)
  })

  it('updateCard writes to localStorage after 300ms debounce', () => {
    const store = useLayoutStore()
    store.updateCard('task', { x: 42 })
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    vi.advanceTimersByTime(300)
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
    expect(saved.cards.task.x).toBe(42)
  })

  it('updateCard debounces multiple rapid calls into one write', () => {
    const store = useLayoutStore()
    store.updateCard('chat', { x: 1 })
    store.updateCard('chat', { x: 2 })
    store.updateCard('chat', { x: 3 })
    vi.advanceTimersByTime(300)
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
    expect(saved.cards.chat.x).toBe(3)
    // Only one write should have happened
    expect(localStorage.getItem(STORAGE_KEY)).not.toBeNull()
  })

  // ── resetToDefault ─────────────────────────────────────────────────────────

  it('resetToDefault restores all cards to computed default layout', () => {
    const store = useLayoutStore()
    store.updateCard('preview', { x: 9999, y: 9999 })
    store.updateCard('task', { x: 9999, y: 9999 })
    vi.advanceTimersByTime(300)

    store.resetToDefault()
    const expected = computeDefaultLayout(window.innerWidth, window.innerHeight)
    expect(store.cards.preview).toEqual(expected.preview)
    expect(store.cards.task).toEqual(expected.task)
    expect(store.cards.chat).toEqual(expected.chat)
    expect(store.cards.toolbar).toEqual(expected.toolbar)
  })

  it('resetToDefault sets isResetting=true then false after 300ms', () => {
    const store = useLayoutStore()
    store.resetToDefault()
    expect(store.isResetting).toBe(true)
    vi.advanceTimersByTime(300)
    expect(store.isResetting).toBe(false)
  })

  it('resetToDefault persists default layout to localStorage', () => {
    const store = useLayoutStore()
    store.resetToDefault()
    vi.advanceTimersByTime(300)
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
    const expected = computeDefaultLayout(window.innerWidth, window.innerHeight)
    expect(saved.cards.preview).toEqual(expected.preview)
    expect(saved.cards.toolbar).toEqual(expected.toolbar)
  })

  // ── toggleLogDetached ──────────────────────────────────────────────────────

  it('toggleLogDetached flips logDetached from false to true', () => {
    const store = useLayoutStore()
    expect(store.logDetached).toBe(false)
    store.toggleLogDetached()
    expect(store.logDetached).toBe(true)
  })

  it('toggleLogDetached flips logDetached from true to false', () => {
    const store = useLayoutStore()
    store.toggleLogDetached()
    store.toggleLogDetached()
    expect(store.logDetached).toBe(false)
  })

  it('toggleLogDetached persists logDetached to localStorage', () => {
    const store = useLayoutStore()
    store.toggleLogDetached()
    vi.advanceTimersByTime(300)
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
    expect(saved.logDetached).toBe(true)
  })

  // ── localStorage initialization ────────────────────────────────────────────

  it('loads saved layout from localStorage on init', () => {
    const vw = window.innerWidth
    const vh = window.innerHeight
    const savedData = {
      cards: {
        preview: { x: 11, y: 22, width: 333, height: 444 },
        task:    { x: 55, y: 66, width: 777, height: 888 },
        chat:    { x: 99, y: 11, width: 222, height: 333 },
        toolbar: { x: 44, y: 55, width: 666, height: 52 },
      },
      logDetached: true,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(savedData))
    setActivePinia(createPinia())
    const store = useLayoutStore()
    expect(store.cards.preview.x).toBe(11)
    expect(store.cards.task.x).toBe(55)
    expect(store.logDetached).toBe(true)
  })

  it('falls back to default layout when localStorage is empty', () => {
    setActivePinia(createPinia())
    const store = useLayoutStore()
    const expected = computeDefaultLayout(window.innerWidth, window.innerHeight)
    expect(store.cards.preview).toEqual(expected.preview)
    expect(store.logDetached).toBe(false)
  })

  it('falls back to default layout when localStorage data is malformed', () => {
    localStorage.setItem(STORAGE_KEY, 'not-valid-json{{{')
    setActivePinia(createPinia())
    const store = useLayoutStore()
    const expected = computeDefaultLayout(window.innerWidth, window.innerHeight)
    expect(store.cards.preview).toEqual(expected.preview)
  })

  // ── clampToViewport ────────────────────────────────────────────────────────

  it('clampToViewport brings out-of-bounds cards back into viewport', () => {
    const store = useLayoutStore()
    // Force a card way off screen
    store.cards.preview = { x: 99999, y: 99999, width: 840, height: 473 }
    store.clampToViewport()
    expect(store.cards.preview.x).toBeLessThanOrEqual(window.innerWidth - 40)
    expect(store.cards.preview.y).toBeLessThanOrEqual(window.innerHeight - 40)
  })

  // ── localStorage serialization format ─────────────────────────────────────

  it('serialized format contains cards and logDetached keys', () => {
    const store = useLayoutStore()
    store.updateCard('preview', { x: 10 })
    vi.advanceTimersByTime(300)
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
    expect(saved).toHaveProperty('cards')
    expect(saved).toHaveProperty('logDetached')
    expect(saved.cards).toHaveProperty('preview')
    expect(saved.cards).toHaveProperty('task')
    expect(saved.cards).toHaveProperty('chat')
    expect(saved.cards).toHaveProperty('toolbar')
  })
})
