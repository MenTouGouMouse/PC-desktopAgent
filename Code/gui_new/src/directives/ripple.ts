import type { ObjectDirective } from 'vue'

// ── Exported pure functions (testable) ──────────────────────

/** Calculate ripple diameter: diagonal * 1.5 to cover all corners */
export function calculateRippleSize(w: number, h: number): number {
  return Math.sqrt(w * w + h * h) * 1.5
}

/** Calculate top-left position so ripple is centered on mouse entry point */
export function calculateRipplePosition(
  mouseX: number,
  mouseY: number,
  diameter: number
): { left: number; top: number } {
  return {
    left: mouseX - diameter / 2,
    top: mouseY - diameter / 2,
  }
}

/** Check if element or any ancestor is currently being dragged by vue-grid-layout */
export function isDragging(el: HTMLElement): boolean {
  return !!el.closest('.vgl-item--dragging')
}

// ── Directive ───────────────────────────────────────────────

interface RippleEl extends HTMLElement {
  _rippleHandler?: (e: MouseEvent) => void
  _rippleLastTime?: number
}

export const vRipple: ObjectDirective = {
  mounted(el: RippleEl) {
    if (!(el instanceof HTMLElement)) return

    // Ensure ripple children can be absolutely positioned
    if (getComputedStyle(el).position === 'static') {
      el.style.position = 'relative'
    }

    const handler = (e: MouseEvent) => {
      if (isDragging(el)) return

      // Throttle: max one ripple every 120ms to avoid flooding on mousemove
      const now = Date.now()
      if (el._rippleLastTime && now - el._rippleLastTime < 120) return
      el._rippleLastTime = now

      const rect = el.getBoundingClientRect()
      const w = rect.width
      const h = rect.height

      // Skip invisible elements
      if (w === 0 || h === 0) return

      const mouseX = e.clientX - rect.left
      const mouseY = e.clientY - rect.top
      const diameter = calculateRippleSize(w, h)
      const { left, top } = calculateRipplePosition(mouseX, mouseY, diameter)

      const ripple = document.createElement('div')
      ripple.className = 'ripple-wave'
      ripple.style.cssText = [
        `width:${diameter}px`,
        `height:${diameter}px`,
        `left:${left}px`,
        `top:${top}px`,
        'position:absolute',
        'border-radius:50%',
        'pointer-events:none',
        'will-change:transform',
      ].join(';')

      el.appendChild(ripple)

      // Trigger animation on next frame to ensure styles are applied
      requestAnimationFrame(() => {
        ripple.classList.add('ripple-animate')
      })

      // Primary cleanup: animationend
      const cleanup = () => {
        if (ripple.parentNode === el) el.removeChild(ripple)
      }
      ripple.addEventListener('animationend', cleanup, { once: true })

      // Fallback cleanup: 600ms (500ms animation + 100ms buffer)
      setTimeout(cleanup, 600)
    }

    el._rippleHandler = handler
    el.addEventListener('mousemove', handler)
  },

  unmounted(el: RippleEl) {
    if (el._rippleHandler) {
      el.removeEventListener('mousemove', el._rippleHandler)
      delete el._rippleHandler
      delete el._rippleLastTime
    }
  },
}
