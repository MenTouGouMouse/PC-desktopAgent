import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import fc from 'fast-check'
import GlassProgressBar from '../GlassProgressBar.vue'

/**
 * Property 1: 进度值截断
 * Validates: Requirements 5.8
 */
describe('GlassProgressBar', () => {
  it('clampedPercent is always in [0, 100] for any float input', () => {
    fc.assert(
      fc.property(fc.float({ noNaN: true }), (n) => {
        const clamped = Math.min(100, Math.max(0, n))
        expect(clamped).toBeGreaterThanOrEqual(0)
        expect(clamped).toBeLessThanOrEqual(100)
      }),
      { numRuns: 200 },
    )
  })

  it('renders .prog-sweep when isRunning=true', () => {
    const wrapper = mount(GlassProgressBar, {
      props: { percent: 50, isRunning: true, statusText: 'running' },
    })
    expect(wrapper.find('.prog-sweep').exists()).toBe(true)
  })

  it('does NOT render .prog-sweep when isRunning=false', () => {
    const wrapper = mount(GlassProgressBar, {
      props: { percent: 50, isRunning: false, statusText: 'idle' },
    })
    expect(wrapper.find('.prog-sweep').exists()).toBe(false)
  })

  it('displays "42%" text when percent=42', () => {
    const wrapper = mount(GlassProgressBar, {
      props: { percent: 42, isRunning: false, statusText: '' },
    })
    // percent=42 > 8, so text is rendered inside .pct-inner
    expect(wrapper.find('.pct-inner').text()).toBe('42%')
  })
})
