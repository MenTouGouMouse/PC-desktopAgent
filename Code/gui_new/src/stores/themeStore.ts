import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ThemeName = 'Light' | 'Dark' | 'Canva-Color'

export const AVAILABLE_THEMES: ThemeName[] = ['Dark', 'Light', 'Canva-Color']

const STORAGE_KEY = 'ui-theme'
const DEFAULT_THEME: ThemeName = 'Dark'

export const CANVA_COLOR_VARS: Record<string, string> = {
  '--bg':           '#0a0e1a',
  '--bg-grad':      '#0a0e1a',
  '--glass':        'rgba(17, 24, 39, 0.8)',
  '--accent':       '#00d4ff',
  '--accent-h':     '#7c3aed',
  '--accent-dim':   'rgba(0, 212, 255, 0.1)',
  '--accent-glow':  'rgba(0, 212, 255, 0.3)',
  '--text':         '#e2e8f0',
  '--text-muted':   '#64748b',
  '--border':       'rgba(0, 212, 255, 0.3)',
  '--success':      '#00ff88',
  '--success-dim':  'rgba(0, 255, 136, 0.14)',
  '--grad-btn':     'linear-gradient(135deg, #00d4ff, #7c3aed)',
  '--progress-bar': 'linear-gradient(90deg, #00d4ff, #00ff88)',
  // Progress bar fill — cyan to green
  '--prog-fill-bg': 'linear-gradient(90deg, rgba(0,180,220,.75) 0%, rgba(0,212,255,.85) 50%, rgba(0,255,136,.70) 100%)',
  '--prog-fill-shadow': '0 0 12px rgba(0,212,255,.40), inset 0 1px 0 rgba(255,255,255,.28), inset 0 -1px 0 rgba(0,150,180,.22)',
  '--prog-glow-tip-bg': 'radial-gradient(ellipse at 35% 50%, rgba(0,255,136,.55) 0%, rgba(0,212,255,.22) 45%, transparent 70%)',
  // Log viewer highlight colors
  '--log-path-color':    '#00d4ff',
  '--log-path-bg':       'rgba(0, 212, 255, 0.1)',
  '--log-fn-color':      '#00d4ff',
  '--log-arr-color':     '#00d4ff',
  '--log-num-color':     '#00d4ff',
  '--log-ok-kw-color':   '#00ff88',
  '--log-ok-kw-bg':      'rgba(0, 255, 136, 0.14)',
}

function loadPersistedTheme(): ThemeName {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && (AVAILABLE_THEMES as string[]).includes(stored)) {
      return stored as ThemeName
    }
  } catch { /* ignore */ }
  return DEFAULT_THEME
}

// Apply theme to #app element (NOT html) to avoid triggering full-page WebView2 repaint
function applyThemeToDOM(name: ThemeName): void {
  // Keep html.dark for CSS selectors that depend on it (scrollbar, etc.)
  // but also apply to #app for scoped theming
  const html = document.documentElement
  const app = document.getElementById('app')

  // Clear previous state
  html.classList.remove('dark')
  html.removeAttribute('data-theme')
  if (app) {
    app.classList.remove('dark', 'theme-canva')
    for (const prop of Object.keys(CANVA_COLOR_VARS)) {
      app.style.removeProperty(prop)
    }
  }

  switch (name) {
    case 'Dark':
      html.classList.add('dark')
      if (app) app.classList.add('dark')
      break
    case 'Light':
      // no class needed, default is light
      break
    case 'Canva-Color':
      html.classList.add('dark') // base on dark
      if (app) {
        app.classList.add('dark', 'theme-canva')
        for (const [prop, value] of Object.entries(CANVA_COLOR_VARS)) {
          app.style.setProperty(prop, value)
        }
      }
      break
  }
}

export const useThemeStore = defineStore('theme', () => {
  const activeTheme = ref<ThemeName>(loadPersistedTheme())

  function setTheme(name: ThemeName): void {
    if (!(AVAILABLE_THEMES as string[]).includes(name)) return
    activeTheme.value = name
    try { localStorage.setItem(STORAGE_KEY, name) } catch { /* ignore */ }
    applyThemeToDOM(name)
  }

  // Apply on init
  applyThemeToDOM(activeTheme.value)

  return { activeTheme, availableThemes: AVAILABLE_THEMES, setTheme }
})

export { STORAGE_KEY, DEFAULT_THEME }
