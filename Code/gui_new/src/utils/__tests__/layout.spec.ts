// Feature: draggable-card-layout
import { describe, it, expect } from 'vitest'
import { clamp, computeDefaultLayout, parseStoredLayout } from '../layout'
import type { LayoutData } from '../layout'

// ---------------------------------------------------------------------------
// clamp
// ---------------------------------------------------------------------------
describe('clamp', () => {
  it('returns the original position when already within bounds', () => {
    const { x, y } = clamp(100, 100, 200, 150, 1440, 900)
    expect(x).toBe(100)
    expect(y).toBe(100)
  })

  it('clamps x to -(w - 40) when card is too far left', () => {
    const { x } = clamp(-300, 100, 200, 150, 1440, 900)
    expect(x).toBe(-(200 - 40)) // -160
  })

  it('clamps x to vw - 40 when card is too far right', () => {
    const { x } = clamp(2000, 100, 200, 150, 1440, 900)
    expect(x).toBe(1440 - 40) // 1400
  })

  it('clamps y to 0 when card is above viewport', () => {
    const { y } = clamp(100, -50, 200, 150, 1440, 900)
    expect(y).toBe(0)
  })

  it('clamps y to vh - 40 when card is below viewport', () => {
    const { y } = clamp(100, 2000, 200, 150, 1440, 900)
    expect(y).toBe(900 - 40) // 860
  })
})

// ---------------------------------------------------------------------------
// computeDefaultLayout – Requirements 2.2, 2.3
// ---------------------------------------------------------------------------
describe('computeDefaultLayout', () => {
  it('preview width is ~58% of viewport width', () => {
    const layout = computeDefaultLayout(1440, 900)
    expect(layout.preview.width).toBe(Math.round(1440 * 0.58))
  })

  it('preview maintains 16:9 aspect ratio', () => {
    const layout = computeDefaultLayout(1440, 900)
    const ratio = layout.preview.width / layout.preview.height
    expect(Math.abs(ratio - 16 / 9)).toBeLessThan(0.01)
  })

  it('preview maintains 16:9 aspect ratio for a small viewport', () => {
    const layout = computeDefaultLayout(800, 600)
    const ratio = layout.preview.width / layout.preview.height
    expect(Math.abs(ratio - 16 / 9)).toBeLessThan(0.01)
  })

  it('task card starts to the right of preview', () => {
    const layout = computeDefaultLayout(1440, 900)
    expect(layout.task.x).toBe(layout.preview.width + 20)
  })

  it('chat card is below task card', () => {
    const layout = computeDefaultLayout(1440, 900)
    expect(layout.chat.y).toBe(layout.task.y + layout.task.height + 10)
  })

  it('toolbar card is near the bottom of the viewport', () => {
    const layout = computeDefaultLayout(1440, 900)
    expect(layout.toolbar.y).toBe(900 - 60)
  })

  it('all cards have positive width and height', () => {
    const layout = computeDefaultLayout(1440, 900)
    for (const card of Object.values(layout)) {
      expect(card.width).toBeGreaterThan(0)
      expect(card.height).toBeGreaterThan(0)
    }
  })

  it('all cards start within the viewport horizontally', () => {
    const vw = 1440
    const layout = computeDefaultLayout(vw, 900)
    for (const card of Object.values(layout)) {
      expect(card.x).toBeGreaterThanOrEqual(0)
      expect(card.x + card.width).toBeLessThanOrEqual(vw + 1) // allow 1px rounding
    }
  })
})

// ---------------------------------------------------------------------------
// parseStoredLayout – Requirements 6.3
// ---------------------------------------------------------------------------
describe('parseStoredLayout', () => {
  const validData: LayoutData = {
    cards: {
      preview: { x: 10, y: 10, width: 840, height: 473 },
      task:    { x: 860, y: 10, width: 570, height: 180 },
      chat:    { x: 860, y: 200, width: 570, height: 480 },
      toolbar: { x: 860, y: 690, width: 570, height: 60 },
    },
    logDetached: false,
  }

  it('returns null for null input', () => {
    expect(parseStoredLayout(null)).toBeNull()
  })

  it('returns null for undefined input', () => {
    expect(parseStoredLayout(undefined)).toBeNull()
  })

  it('returns null for empty string', () => {
    expect(parseStoredLayout('')).toBeNull()
  })

  it('returns null for corrupted JSON', () => {
    expect(parseStoredLayout('{not valid json')).toBeNull()
  })

  it('returns null when cards field is missing', () => {
    expect(parseStoredLayout(JSON.stringify({ logDetached: false }))).toBeNull()
  })

  it('returns null when logDetached field is missing', () => {
    expect(parseStoredLayout(JSON.stringify({ cards: validData.cards }))).toBeNull()
  })

  it('returns null when a card entry is missing', () => {
    const partial = {
      cards: { preview: validData.cards.preview, task: validData.cards.task },
      logDetached: false,
    }
    expect(parseStoredLayout(JSON.stringify(partial))).toBeNull()
  })

  it('returns null when a card has a non-number field', () => {
    const bad = {
      ...validData,
      cards: {
        ...validData.cards,
        preview: { x: '10', y: 10, width: 840, height: 473 },
      },
    }
    expect(parseStoredLayout(JSON.stringify(bad))).toBeNull()
  })

  it('parses valid data correctly', () => {
    const result = parseStoredLayout(JSON.stringify(validData))
    expect(result).toEqual(validData)
  })

  it('preserves logDetached = true', () => {
    const data = { ...validData, logDetached: true }
    const result = parseStoredLayout(JSON.stringify(data))
    expect(result?.logDetached).toBe(true)
  })
})
