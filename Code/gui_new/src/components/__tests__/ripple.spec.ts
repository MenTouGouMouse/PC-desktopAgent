import { describe, it, expect, beforeEach } from 'vitest'
import fc from 'fast-check'
import { calculateRippleSize, calculateRipplePosition, isDragging, vRipple } from '../../directives/ripple'

// ── Unit Tests ───────────────────────────────────────────────

describe('calculateRipplePosition', () => {
  it('centers ripple: left === mouseX - diameter/2, top === mouseY - diameter/2', () => {
    const mouseX = 120
    const mouseY = 80
    const diameter = 200
    const { left, top } = calculateRipplePosition(mouseX, mouseY, diameter)
    expect(left).toBe(mouseX - diameter / 2)
    expect(top).toBe(mouseY - diameter / 2)
  })
})

describe('isDragging', () => {
  it('returns false when no .vgl-item--dragging ancestor', () => {
    const el = document.createElement('div')
    document.body.appendChild(el)
    expect(isDragging(el)).toBe(false)
    document.body.removeChild(el)
  })

  it('returns true when .vgl-item--dragging ancestor exists', () => {
    const parent = document.createElement('div')
    parent.classList.add('vgl-item--dragging')
    const child = document.createElement('div')
    parent.appendChild(child)
    document.body.appendChild(parent)
    expect(isDragging(child)).toBe(true)
    document.body.removeChild(parent)
  })
})

describe('two consecutive mousemove events', () => {
  it('create two independent ripple children when throttle window has passed', () => {
    const el = document.createElement('div')
    el.style.width = '200px'
    el.style.height = '100px'
    document.body.appendChild(el)

    el.getBoundingClientRect = () => ({
      width: 200, height: 100, left: 0, top: 0,
      right: 200, bottom: 100, x: 0, y: 0, toJSON: () => {},
    })

    vRipple.mounted!(el as any, {} as any, {} as any, {} as any)

    // First event
    el.dispatchEvent(new MouseEvent('mousemove', { clientX: 50, clientY: 50, bubbles: true }))
    // Force throttle window to pass by backdating the timestamp
    ;(el as any)._rippleLastTime = Date.now() - 200
    // Second event after throttle
    el.dispatchEvent(new MouseEvent('mousemove', { clientX: 60, clientY: 60, bubbles: true }))

    expect(el.children.length).toBe(2)

    document.body.removeChild(el)
  })
})

describe('ripple cleanup on animationend (Property 3)', () => {
  it('ripple div removed from DOM after animationend fires', () => {
    const el = document.createElement('div')
    el.getBoundingClientRect = () => ({
      width: 200, height: 100, left: 0, top: 0,
      right: 200, bottom: 100, x: 0, y: 0, toJSON: () => {},
    })
    document.body.appendChild(el)

    vRipple.mounted!(el as any, {} as any, {} as any, {} as any)
    el.dispatchEvent(new MouseEvent('mousemove', { clientX: 50, clientY: 50, bubbles: true }))

    expect(el.children.length).toBe(1)
    const ripple = el.children[0] as HTMLElement

    ripple.dispatchEvent(new Event('animationend'))

    expect(el.children.length).toBe(0)

    document.body.removeChild(el)
  })
})

// ── Property Tests ───────────────────────────────────────────

/**
 * Property 1: calculateRippleSize(w, h) === Math.sqrt(w*w + h*h) * 1.5
 * Validates: Requirements 1.1
 */
describe('Property 1: calculateRippleSize formula', () => {
  it('equals Math.sqrt(w*w + h*h) * 1.5 for any w,h in [50, 2000]', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 50, max: 2000 }),
        fc.integer({ min: 50, max: 2000 }),
        (w, h) => {
          const expected = Math.sqrt(w * w + h * h) * 1.5
          expect(calculateRippleSize(w, h)).toBeCloseTo(expected, 10)
        },
      ),
      { numRuns: 100 },
    )
  })
})

/**
 * Property 2: ripple element always has pointer-events:none, position:absolute, border-radius:50%
 * Validates: Requirements 1.2
 */
describe('Property 2: ripple element styles', () => {
  it('always has pointer-events:none, position:absolute, border-radius:50%', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 500 }),
        fc.integer({ min: 1, max: 500 }),
        (x, y) => {
          const el = document.createElement('div')
          el.getBoundingClientRect = () => ({
            width: 200, height: 100, left: 0, top: 0,
            right: 200, bottom: 100, x: 0, y: 0, toJSON: () => {},
          })
          document.body.appendChild(el)

          vRipple.mounted!(el as any, {} as any, {} as any, {} as any)
          el.dispatchEvent(new MouseEvent('mousemove', { clientX: x, clientY: y, bubbles: true }))

          const ripple = el.children[0] as HTMLElement
          expect(ripple).toBeDefined()
          expect(ripple.style.pointerEvents).toBe('none')
          expect(ripple.style.position).toBe('absolute')
          expect(ripple.style.borderRadius).toBe('50%')

          document.body.removeChild(el)
        },
      ),
      { numRuns: 100 },
    )
  })
})

/**
 * Property 4: no ripple child created when .vgl-item--dragging ancestor present
 * Validates: Requirements 1.4
 */
describe('Property 4: no ripple when dragging', () => {
  it('creates no ripple child when .vgl-item--dragging ancestor present', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 500 }),
        fc.integer({ min: 1, max: 500 }),
        (x, y) => {
          const wrapper = document.createElement('div')
          wrapper.classList.add('vgl-item--dragging')
          const el = document.createElement('div')
          el.getBoundingClientRect = () => ({
            width: 200, height: 100, left: 0, top: 0,
            right: 200, bottom: 100, x: 0, y: 0, toJSON: () => {},
          })
          wrapper.appendChild(el)
          document.body.appendChild(wrapper)

          vRipple.mounted!(el as any, {} as any, {} as any, {} as any)
          el.dispatchEvent(new MouseEvent('mousemove', { clientX: x, clientY: y, bubbles: true }))

          expect(el.children.length).toBe(0)

          document.body.removeChild(wrapper)
        },
      ),
      { numRuns: 100 },
    )
  })
})

/**
 * Property 5: after vRipple.unmounted(el), mouseenter creates no ripple child
 * Validates: Requirements 1.5
 */
describe('Property 5: no ripple after unmounted', () => {
  it('mouseenter creates no ripple after vRipple.unmounted', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 500 }),
        fc.integer({ min: 1, max: 500 }),
        (x, y) => {
          const el = document.createElement('div')
          el.getBoundingClientRect = () => ({
            width: 200, height: 100, left: 0, top: 0,
            right: 200, bottom: 100, x: 0, y: 0, toJSON: () => {},
          })
          document.body.appendChild(el)

          vRipple.mounted!(el as any, {} as any, {} as any, {} as any)
          vRipple.unmounted!(el as any, {} as any, {} as any, {} as any)

          el.dispatchEvent(new MouseEvent('mousemove', { clientX: x, clientY: y, bubbles: true }))

          expect(el.children.length).toBe(0)

          document.body.removeChild(el)
        },
      ),
      { numRuns: 100 },
    )
  })
})

/**
 * Property 6: static position becomes relative; non-static positions unchanged
 * Validates: Requirements 1.6
 */
describe('Property 6: position style after mounted', () => {
  it('static element gets position:relative after mounted', () => {
    fc.assert(
      fc.property(fc.constant('static'), (pos) => {
        const el = document.createElement('div')
        el.style.position = pos
        document.body.appendChild(el)

        vRipple.mounted!(el as any, {} as any, {} as any, {} as any)

        expect(el.style.position).toBe('relative')

        document.body.removeChild(el)
      }),
      { numRuns: 100 },
    )
  })

  it('non-static positions are unchanged after mounted', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('relative', 'absolute', 'fixed', 'sticky'),
        (pos) => {
          const el = document.createElement('div')
          el.style.position = pos
          // Override getComputedStyle for this element to return the set position
          const origGetComputedStyle = window.getComputedStyle
          const mockGetComputedStyle = (target: Element) => {
            if (target === el) {
              return { position: pos } as CSSStyleDeclaration
            }
            return origGetComputedStyle(target)
          }
          Object.defineProperty(window, 'getComputedStyle', {
            value: mockGetComputedStyle,
            configurable: true,
          })

          document.body.appendChild(el)
          vRipple.mounted!(el as any, {} as any, {} as any, {} as any)

          expect(el.style.position).toBe(pos)

          document.body.removeChild(el)
          Object.defineProperty(window, 'getComputedStyle', {
            value: origGetComputedStyle,
            configurable: true,
          })
        },
      ),
      { numRuns: 100 },
    )
  })
})
