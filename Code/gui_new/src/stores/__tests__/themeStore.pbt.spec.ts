/**
 * Property-based tests for themeStore
 * Uses fast-check with minimum 100 iterations per property
 * Feature: ui-theme-switcher
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import * as fc from 'fast-check'
import { useThemeStore, AVAILABLE_THEMES, CANVA_COLOR_VARS, STORAGE_KEY, DEFAULT_THEME } from '../themeStore'
import type { ThemeName } from '../themeStore'

const arbTheme = fc.constantFrom(...AVAILABLE_THEMES)

function resetDOM(): void {
  document.documentElement.classList.remove('dark')
  for (const prop of Object.keys(CANVA_COLOR_VARS)) {
    document.documentElement.style.removeProperty(prop)
  }
}

describe('themeStore — property-based tests', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetDOM()
  })

  /**
   * Property 4: 点击主题项更新 Active_Theme
   * Feature: ui-theme-switcher, Property 4: clicking a theme item updates Active_Theme
   * Validates: Requirements 3.1
   */
  it('Property 4: setTheme(name) always sets activeTheme to name', () => {
    fc.assert(
      fc.property(arbTheme, (theme: ThemeName) => {
        setActivePinia(createPinia())
        resetDOM()
        const store = useThemeStore()
        store.setTheme(theme)
        expect(store.activeTheme).toBe(theme)
      }),
      { numRuns: 100 }
    )
  })

  /**
   * Property 5: 主题切换后 CSS 变量正确应用
   * Feature: ui-theme-switcher, Property 5: CSS state is correct after theme switch with no artifacts from previous theme
   * Validates: Requirements 3.2, 3.4, 3.5, 3.6, 5.2, 5.3
   */
  it('Property 5: after setTheme(to), DOM reflects "to" theme with no artifacts from "from" theme', () => {
    fc.assert(
      fc.property(fc.tuple(arbTheme, arbTheme), ([from, to]: [ThemeName, ThemeName]) => {
        setActivePinia(createPinia())
        resetDOM()
        const store = useThemeStore()
        store.setTheme(from)
        store.setTheme(to)

        const root = document.documentElement

        if (to === 'Dark') {
          expect(root.classList.contains('dark')).toBe(true)
          for (const prop of Object.keys(CANVA_COLOR_VARS)) {
            expect(root.style.getPropertyValue(prop)).toBe('')
          }
        } else if (to === 'Light') {
          expect(root.classList.contains('dark')).toBe(false)
          for (const prop of Object.keys(CANVA_COLOR_VARS)) {
            expect(root.style.getPropertyValue(prop)).toBe('')
          }
        } else if (to === 'Canva-Color') {
          for (const [prop, value] of Object.entries(CANVA_COLOR_VARS)) {
            expect(root.style.getPropertyValue(prop)).toBe(value)
          }
        }
      }),
      { numRuns: 100 }
    )
  })

  /**
   * Property 6: Active_Theme 变化持久化到 localStorage
   * Feature: ui-theme-switcher, Property 6: Active_Theme change is persisted to localStorage
   * Validates: Requirements 6.1
   */
  it('Property 6: after setTheme(name), localStorage["ui-theme"] === name', () => {
    fc.assert(
      fc.property(arbTheme, (theme: ThemeName) => {
        setActivePinia(createPinia())
        resetDOM()
        const store = useThemeStore()
        store.setTheme(theme)
        expect(localStorage.getItem(STORAGE_KEY)).toBe(theme)
      }),
      { numRuns: 100 }
    )
  })

  /**
   * Property 7: localStorage round-trip 保真
   * Feature: ui-theme-switcher, Property 7: writing theme to localStorage then initializing store yields same theme
   * Validates: Requirements 6.2, 6.4
   */
  it('Property 7: store initialized after writing theme to localStorage reads back the same theme', () => {
    fc.assert(
      fc.property(arbTheme, (theme: ThemeName) => {
        localStorage.setItem(STORAGE_KEY, theme)
        setActivePinia(createPinia())
        resetDOM()
        const store = useThemeStore()
        expect(store.activeTheme).toBe(theme)
      }),
      { numRuns: 100 }
    )
  })
})
