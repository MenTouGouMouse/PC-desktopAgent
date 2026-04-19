// Feature: draggable-card-layout
// Property-based tests for useLayoutStore.
// Covers: Property 2, 7, 8, 10, 11

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import * as fc from 'fast-check'
import { useLayoutStore, STORAGE_KEY } from '../layoutStore'
import { computeDefaultLayout, parseStoredLayout } from '@/utils/layout'
import type { CardId, CardState } from '@/utils/layout'

// ── Arbitraries ──────────────────────────────────────────────────────────────

const cardIdArb: fc.Arbitrary<CardId> = fc.constantFrom('preview', 'task', 'chat', 'toolbar')

const cardStateArb: fc.Arbitrary<CardState> = fc.record({
  x: fc.integer({ min: -500, max: 3000 }),
  y: fc.integer({ min: -500, max: 2000 }),
  width: fc.integer({ min: 100, max: 1200 }),
  height: fc.integer({ min: 50, max: 900 }),
})

const allCardsArb: fc.Arbitrary<Record<CardId, CardState>> = fc.record({
  preview: cardStateArb,
  task:    cardStateArb,
  chat:    cardStateArb,
  toolbar: cardStateArb,
})

// ── Setup ─────────────────────────────────────────────────────────────────────

describe('useLayoutStore — property-based tests', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // ── Property 2: 拖拽释放后位置持久化 ─────────────────────────────────────
  // For any card position P after drag release, reading from useLayoutStore
  // and from localStorage should both equal P.
  // Validates: Requirements 1.3, 6.1, 6.2

  it('Property 2: updateCard position is persisted to store and localStorage', () => {
    fc.assert(
      fc.property(
        cardIdArb,
        cardStateArb,
        (id, patch) => {
          setActivePinia(createPinia())
          localStorage.clear()
          const store = useLayoutStore()

          store.updateCard(id, patch)

          // Store state is updated immediately
          expect(store.cards[id].x).toBe(patch.x)
          expect(store.cards[id].y).toBe(patch.y)
          expect(store.cards[id].width).toBe(patch.width)
          expect(store.cards[id].height).toBe(patch.height)

          // After debounce, localStorage reflects the same value
          vi.advanceTimersByTime(300)
          const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
          expect(saved.cards[id].x).toBe(patch.x)
          expect(saved.cards[id].y).toBe(patch.y)
          expect(saved.cards[id].width).toBe(patch.width)
          expect(saved.cards[id].height).toBe(patch.height)
        },
      ),
      { numRuns: 100 },
    )
  })

  // ── Property 7: logDetached 双次切换恢复原状态 ────────────────────────────
  // For any initial logDetached value, calling toggleLogDetached() twice
  // must restore the original value (idempotent round-trip).
  // Validates: Requirements 3.5, 3.6

  it('Property 7: toggleLogDetached twice restores original state', () => {
    fc.assert(
      fc.property(
        fc.boolean(),
        (initialValue) => {
          setActivePinia(createPinia())
          localStorage.clear()
          const store = useLayoutStore()

          // Set initial logDetached value
          if (store.logDetached !== initialValue) {
            store.toggleLogDetached()
          }
          const before = store.logDetached

          store.toggleLogDetached()
          store.toggleLogDetached()

          expect(store.logDetached).toBe(before)
        },
      ),
      { numRuns: 100 },
    )
  })

  // ── Property 8: logDetached 持久化往返 ───────────────────────────────────
  // For any logDetached boolean, after writing to localStorage and re-parsing,
  // the logDetached field must equal the written value.
  // Validates: Requirements 3.8

  it('Property 8: logDetached persists and round-trips through localStorage', () => {
    fc.assert(
      fc.property(
        fc.boolean(),
        (targetValue) => {
          setActivePinia(createPinia())
          localStorage.clear()
          const store = useLayoutStore()

          // Drive logDetached to targetValue, always trigger at least one write
          if (store.logDetached !== targetValue) {
            store.toggleLogDetached()
          } else {
            // Force a write by updating any card
            store.updateCard('preview', { ...store.cards.preview })
          }
          expect(store.logDetached).toBe(targetValue)

          vi.advanceTimersByTime(300)

          const raw = localStorage.getItem(STORAGE_KEY)
          const parsed = parseStoredLayout(raw)
          expect(parsed).not.toBeNull()
          expect(parsed!.logDetached).toBe(targetValue)
        },
      ),
      { numRuns: 100 },
    )
  })

  // ── Property 10: resetToDefault 后所有卡片位置等于 DEFAULT_LAYOUT ─────────
  // For any current layout state, calling resetToDefault() must set all cards
  // to the values returned by computeDefaultLayout(vw, vh).
  // Validates: Requirements 5.4, 6.4

  it('Property 10: resetToDefault always produces computeDefaultLayout values', () => {
    fc.assert(
      fc.property(
        allCardsArb,
        fc.boolean(),
        (arbitraryCards, arbitraryLogDetached) => {
          setActivePinia(createPinia())
          localStorage.clear()
          const store = useLayoutStore()

          // Set arbitrary state
          const ids: CardId[] = ['preview', 'task', 'chat', 'toolbar']
          for (const id of ids) {
            store.updateCard(id, arbitraryCards[id])
          }
          if (store.logDetached !== arbitraryLogDetached) {
            store.toggleLogDetached()
          }

          store.resetToDefault()

          const expected = computeDefaultLayout(window.innerWidth, window.innerHeight)
          for (const id of ids) {
            expect(store.cards[id]).toEqual(expected[id])
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  // ── Property 11: 布局序列化往返 ──────────────────────────────────────────
  // For any valid layout state (cards + logDetached), JSON.stringify then
  // JSON.parse must produce values equal to the originals.
  // Validates: Requirements 6.1, 6.2

  it('Property 11: layout serialization round-trip preserves all fields', () => {
    fc.assert(
      fc.property(
        allCardsArb,
        fc.boolean(),
        (arbitraryCards, logDetachedValue) => {
          setActivePinia(createPinia())
          localStorage.clear()
          const store = useLayoutStore()

          const ids: CardId[] = ['preview', 'task', 'chat', 'toolbar']
          for (const id of ids) {
            store.updateCard(id, arbitraryCards[id])
          }
          if (store.logDetached !== logDetachedValue) {
            store.toggleLogDetached()
          }

          vi.advanceTimersByTime(300)

          const raw = localStorage.getItem(STORAGE_KEY)
          const parsed = parseStoredLayout(raw)

          expect(parsed).not.toBeNull()
          expect(parsed!.logDetached).toBe(logDetachedValue)
          for (const id of ids) {
            expect(parsed!.cards[id]).toEqual(store.cards[id])
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})
