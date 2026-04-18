import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useThemeStore, CANVA_COLOR_VARS, STORAGE_KEY, DEFAULT_THEME } from '../themeStore'

describe('themeStore — unit tests', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    // Reset documentElement state
    document.documentElement.classList.remove('dark')
    for (const prop of Object.keys(CANVA_COLOR_VARS)) {
      document.documentElement.style.removeProperty(prop)
    }
  })

  // Requirements: 3.4
  it('setTheme("Dark") adds dark class and removes inline styles', () => {
    const store = useThemeStore()
    store.setTheme('Dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    for (const prop of Object.keys(CANVA_COLOR_VARS)) {
      expect(document.documentElement.style.getPropertyValue(prop)).toBe('')
    }
  })

  // Requirements: 3.5
  it('setTheme("Light") removes dark class and removes inline styles', () => {
    const store = useThemeStore()
    // First set dark so we have something to remove
    store.setTheme('Dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    store.setTheme('Light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    for (const prop of Object.keys(CANVA_COLOR_VARS)) {
      expect(document.documentElement.style.getPropertyValue(prop)).toBe('')
    }
  })

  // Requirements: 3.6, 5.2
  it('setTheme("Canva-Color") injects all CSS variables as inline styles', () => {
    const store = useThemeStore()
    store.setTheme('Canva-Color')
    for (const [prop, value] of Object.entries(CANVA_COLOR_VARS)) {
      expect(document.documentElement.style.getPropertyValue(prop)).toBe(value)
    }
  })

  // Requirements: 5.3
  it('switching from Canva-Color to Light clears all inline styles', () => {
    const store = useThemeStore()
    store.setTheme('Canva-Color')
    // Verify styles were set
    expect(document.documentElement.style.getPropertyValue('--accent')).toBe('#00d4ff')
    store.setTheme('Light')
    for (const prop of Object.keys(CANVA_COLOR_VARS)) {
      expect(document.documentElement.style.getPropertyValue(prop)).toBe('')
    }
  })

  // Requirements: 5.3
  it('switching from Canva-Color to Dark clears all inline styles', () => {
    const store = useThemeStore()
    store.setTheme('Canva-Color')
    store.setTheme('Dark')
    for (const prop of Object.keys(CANVA_COLOR_VARS)) {
      expect(document.documentElement.style.getPropertyValue(prop)).toBe('')
    }
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  // Requirements: 6.3
  it('does not throw when localStorage is unavailable', () => {
    const store = useThemeStore()
    // Simulate localStorage failure
    const original = Object.getOwnPropertyDescriptor(window, 'localStorage')
    Object.defineProperty(window, 'localStorage', {
      get() { throw new Error('localStorage unavailable') },
      configurable: true,
    })
    expect(() => store.setTheme('Dark')).not.toThrow()
    // Restore
    if (original) Object.defineProperty(window, 'localStorage', original)
  })

  // Requirements: 6.3 — unknown theme name falls back to Light
  it('initializes to DEFAULT_THEME (Light) when localStorage has unknown theme', () => {
    localStorage.setItem(STORAGE_KEY, 'UnknownTheme')
    setActivePinia(createPinia())
    const store = useThemeStore()
    expect(store.activeTheme).toBe(DEFAULT_THEME)
  })

  // Requirements: 6.2
  it('reads persisted theme from localStorage on initialization', () => {
    localStorage.setItem(STORAGE_KEY, 'Dark')
    setActivePinia(createPinia())
    const store = useThemeStore()
    expect(store.activeTheme).toBe('Dark')
  })

  // Requirements: 6.1
  it('writes theme to localStorage on setTheme', () => {
    const store = useThemeStore()
    store.setTheme('Canva-Color')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('Canva-Color')
  })
})
