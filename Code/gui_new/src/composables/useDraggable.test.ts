// Feature: draggable-card-layout
// Tests for useDraggable composable: drag displacement, aspect ratio, resize min size, event sequence.

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import fc from 'fast-check'
import { useDraggable } from './useDraggable'
import { useLayoutStore } from '@/stores/layoutStore'

// Helper: create a minimal component that uses useDraggable
function makeComponent(cardId: string, options = {}) {
  return defineComponent({
    setup() {
      const { cardStyle, handleMousedown, resizeMousedown, isDragging } = useDraggable(
        cardId as any,
        options,
      )
      return { cardStyle, handleMousedown, resizeMousedown, isDragging }
    },
    render() {
      return h('div')
    },
  })
}

describe('useDraggable', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // Set a stable viewport
    Object.defineProperty(window, 'innerWidth', { value: 1440, writable: true, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 900, writable: true, configurable: true })
  })

  // ── Property 1: 拖拽位移等于鼠标位移 ──────────────────────────────────────
  // Validates: Requirements 1.2
  describe('Property 1: drag displacement equals mouse displacement', () => {
    it('card position changes by exactly the mouse delta (within viewport)', () => {
      // Property 1: 拖拽位移等于鼠标位移
      fc.assert(
        fc.property(
          fc.integer({ min: 100, max: 800 }),  // startCardX
          fc.integer({ min: 100, max: 600 }),  // startCardY
          fc.integer({ min: -200, max: 200 }), // deltaX
          fc.integer({ min: -200, max: 200 }), // deltaY
          (startCardX, startCardY, deltaX, deltaY) => {
            setActivePinia(createPinia())
            const store = useLayoutStore()
            // Set initial card position
            store.updateCard('task', { x: startCardX, y: startCardY })

            const wrapper = mount(makeComponent('task'))
            const vm = wrapper.vm as any

            // Simulate mousedown at (500, 400)
            const mousedownEvent = new MouseEvent('mousedown', {
              clientX: 500,
              clientY: 400,
              bubbles: true,
            })
            vm.handleMousedown(mousedownEvent)

            // Simulate mousemove
            const mousemoveEvent = new MouseEvent('mousemove', {
              clientX: 500 + deltaX,
              clientY: 400 + deltaY,
              bubbles: true,
            })
            document.dispatchEvent(mousemoveEvent)

            const card = store.cards['task']
            const expectedRawX = startCardX + deltaX
            const expectedRawY = startCardY + deltaY

            // After clamp, position should be clamped version of expected
            const vw = window.innerWidth
            const vh = window.innerHeight
            const w = card.width
            const hh = card.height
            const clampedX = Math.min(Math.max(expectedRawX, -(w - 40)), vw - 40)
            const clampedY = Math.min(Math.max(expectedRawY, 0), vh - 40)

            // Cleanup
            document.dispatchEvent(new MouseEvent('mouseup'))
            wrapper.unmount()

            return card.x === clampedX && card.y === clampedY
          },
        ),
        { numRuns: 100 },
      )
    })
  })

  // ── Property 4: PreviewCard 宽高比恒为 16:9 ───────────────────────────────
  // Validates: Requirements 2.3
  describe('Property 4: PreviewCard aspect ratio stays 16:9 during resize', () => {
    it('width/height ratio is always 16/9 when aspectRatio=16/9 is set', () => {
      // Property 4: PreviewCard 宽高比恒为 16:9
      fc.assert(
        fc.property(
          fc.integer({ min: 200, max: 600 }), // startWidth
          fc.integer({ min: 50, max: 400 }),  // deltaX (resize delta)
          (startWidth, deltaX) => {
            setActivePinia(createPinia())
            const store = useLayoutStore()
            store.updateCard('preview', { width: startWidth, height: Math.round(startWidth * 9 / 16) })

            const wrapper = mount(makeComponent('preview', { resizable: true, aspectRatio: 16 / 9, minWidth: 200 }))
            const vm = wrapper.vm as any

            // Simulate resize mousedown
            const resizeDown = new MouseEvent('mousedown', { clientX: 500, clientY: 400 })
            vm.resizeMousedown(resizeDown)

            // Simulate resize mousemove
            const resizeMove = new MouseEvent('mousemove', { clientX: 500 + deltaX, clientY: 400 + 50 })
            document.dispatchEvent(resizeMove)

            const card = store.cards['preview']
            const ratio = card.width / card.height

            // Cleanup
            document.dispatchEvent(new MouseEvent('mouseup'))
            wrapper.unmount()

            return Math.abs(ratio - 16 / 9) < 0.01
          },
        ),
        { numRuns: 100 },
      )
    })
  })

  // ── Property 5: Resize 最小尺寸约束 ──────────────────────────────────────
  // Validates: Requirements 3.4
  describe('Property 5: resize minimum size constraint', () => {
    it('width never goes below minWidth and height never below minHeight', () => {
      // Property 5: Resize 最小尺寸约束
      fc.assert(
        fc.property(
          fc.integer({ min: 300, max: 600 }), // startWidth
          fc.integer({ min: 250, max: 500 }), // startHeight
          fc.integer({ min: -600, max: 600 }), // deltaX
          fc.integer({ min: -600, max: 600 }), // deltaY
          (startWidth, startHeight, deltaX, deltaY) => {
            setActivePinia(createPinia())
            const store = useLayoutStore()
            store.updateCard('chat', { width: startWidth, height: startHeight })

            const minWidth = 280
            const minHeight = 200

            const wrapper = mount(makeComponent('chat', { resizable: true, minWidth, minHeight }))
            const vm = wrapper.vm as any

            const resizeDown = new MouseEvent('mousedown', { clientX: 500, clientY: 400 })
            vm.resizeMousedown(resizeDown)

            const resizeMove = new MouseEvent('mousemove', {
              clientX: 500 + deltaX,
              clientY: 400 + deltaY,
            })
            document.dispatchEvent(resizeMove)

            const card = store.cards['chat']

            document.dispatchEvent(new MouseEvent('mouseup'))
            wrapper.unmount()

            return card.width >= minWidth && card.height >= minHeight
          },
        ),
        { numRuns: 100 },
      )
    })
  })

  // ── Task 4.4: drag event sequence component test ──────────────────────────
  describe('drag event sequence (mousedown → mousemove → mouseup)', () => {
    it('isDragging becomes true on mousedown and false on mouseup', () => {
      const store = useLayoutStore()
      const wrapper = mount(makeComponent('task'))
      const vm = wrapper.vm as any

      expect(vm.isDragging).toBe(false)

      vm.handleMousedown(new MouseEvent('mousedown', { clientX: 100, clientY: 100 }))
      expect(vm.isDragging).toBe(true)

      document.dispatchEvent(new MouseEvent('mouseup'))
      expect(vm.isDragging).toBe(false)

      wrapper.unmount()
    })

    it('card position updates during mousemove after mousedown', () => {
      const store = useLayoutStore()
      store.updateCard('task', { x: 200, y: 150 })

      const wrapper = mount(makeComponent('task'))
      const vm = wrapper.vm as any

      vm.handleMousedown(new MouseEvent('mousedown', { clientX: 300, clientY: 300 }))
      document.dispatchEvent(new MouseEvent('mousemove', { clientX: 350, clientY: 320 }))

      // delta: +50, +20
      expect(store.cards['task'].x).toBe(250)
      expect(store.cards['task'].y).toBe(170)

      document.dispatchEvent(new MouseEvent('mouseup'))
      wrapper.unmount()
    })

    it('card position does not change after mouseup', () => {
      const store = useLayoutStore()
      store.updateCard('task', { x: 200, y: 150 })

      const wrapper = mount(makeComponent('task'))
      const vm = wrapper.vm as any

      vm.handleMousedown(new MouseEvent('mousedown', { clientX: 300, clientY: 300 }))
      document.dispatchEvent(new MouseEvent('mouseup'))

      const posAfterUp = { x: store.cards['task'].x, y: store.cards['task'].y }

      // Further mousemove should not change position
      document.dispatchEvent(new MouseEvent('mousemove', { clientX: 500, clientY: 500 }))
      expect(store.cards['task'].x).toBe(posAfterUp.x)
      expect(store.cards['task'].y).toBe(posAfterUp.y)

      wrapper.unmount()
    })

    it('cardStyle reflects current card position and isDragging z-index', () => {
      const store = useLayoutStore()
      store.updateCard('task', { x: 100, y: 200, width: 400, height: 300 })

      const wrapper = mount(makeComponent('task'))
      const vm = wrapper.vm as any

      expect(vm.cardStyle.left).toBe('100px')
      expect(vm.cardStyle.top).toBe('200px')
      expect(vm.cardStyle.zIndex).toBe(100)

      vm.handleMousedown(new MouseEvent('mousedown', { clientX: 0, clientY: 0 }))
      expect(vm.cardStyle.zIndex).toBe(1000)

      document.dispatchEvent(new MouseEvent('mouseup'))
      expect(vm.cardStyle.zIndex).toBe(100)

      wrapper.unmount()
    })
  })

  // ── resizeMousedown no-op when resizable=false ────────────────────────────
  describe('resizeMousedown', () => {
    it('does nothing when resizable is false (default)', () => {
      const store = useLayoutStore()
      store.updateCard('task', { width: 400, height: 300 })

      const wrapper = mount(makeComponent('task'))
      const vm = wrapper.vm as any

      vm.resizeMousedown(new MouseEvent('mousedown', { clientX: 500, clientY: 400 }))
      document.dispatchEvent(new MouseEvent('mousemove', { clientX: 700, clientY: 600 }))

      // Width/height should be unchanged
      expect(store.cards['task'].width).toBe(400)
      expect(store.cards['task'].height).toBe(300)

      document.dispatchEvent(new MouseEvent('mouseup'))
      wrapper.unmount()
    })
  })
})
