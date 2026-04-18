// Feature: draggable-card-layout, Property 3: boundary clamp guarantees minimum visible area
import { describe, it } from 'vitest'
import * as fc from 'fast-check'
import { clamp } from '../layout'

describe('layout utils – property-based tests', () => {
  /**
   * Property 3: 边界约束保证最小可见区域
   * Validates: Requirements 1.5, 6.5
   *
   * For any viewport (vw, vh), card size (w, h) and arbitrary target position (x, y),
   * the clamped position (cx, cy) must satisfy:
   *   cx >= -(w - 40)
   *   cy >= 0
   *   cx <= vw - 40
   *   cy <= vh - 40
   */
  it('Property 3: clamp guarantees 40px minimum visible area', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 200, max: 2560 }), // vw
        fc.integer({ min: 200, max: 1440 }), // vh
        fc.integer({ min: 100, max: 800 }),  // w
        fc.integer({ min: 100, max: 600 }),  // h
        fc.integer({ min: -2000, max: 3000 }), // x
        fc.integer({ min: -2000, max: 2000 }), // y
        (vw, vh, w, h, x, y) => {
          const { x: cx, y: cy } = clamp(x, y, w, h, vw, vh)
          return cx >= -(w - 40) && cy >= 0 && cx <= vw - 40 && cy <= vh - 40
        },
      ),
      { numRuns: 100 },
    )
  })
})
