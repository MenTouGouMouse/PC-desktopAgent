/**
 * SettingsDialog.vue component tests
 * Validates: Requirements 5.2, 5.4, 5.6, 5.7, 5.8, 6.1
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import SettingsDialog from '../SettingsDialog.vue'

// Mock usePyWebView composable
const mockGetDefaultPaths = vi.fn()
const mockSaveDefaultPaths = vi.fn()
const mockOpenFolderDialog = vi.fn()

vi.mock('../../composables/usePyWebView', () => ({
  usePyWebView: () => ({
    getDefaultPaths: mockGetDefaultPaths,
    saveDefaultPaths: mockSaveDefaultPaths,
    openFolderDialog: mockOpenFolderDialog,
  }),
}))

function mountDialog(visible = true) {
  return mount(SettingsDialog, {
    props: { visible },
    attachTo: document.body,
  })
}

// Helper: query inside document.body (Teleport renders there)
function bodyFind(selector: string): HTMLElement | null {
  return document.body.querySelector(selector)
}
function bodyFindAll<T extends HTMLElement = HTMLElement>(selector: string): NodeListOf<T> {
  return document.body.querySelectorAll<T>(selector)
}

describe('SettingsDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetDefaultPaths.mockResolvedValue({
      organize_source: 'E:\\Downloads',
      installer_default_dir: 'E:\\Installers',
    })
    mockSaveDefaultPaths.mockResolvedValue({ success: true })
    mockOpenFolderDialog.mockResolvedValue({ path: 'C:\\Selected' })
  })

  afterEach(() => {
    // Clean up any leftover DOM nodes
    document.body.innerHTML = ''
  })

  // Validates: Requirement 5.8 — dialog pre-fills values from getDefaultPaths
  it('opens with pre-filled values from getDefaultPaths', async () => {
    const wrapper = mountDialog(true)
    await flushPromises()

    const inputs = bodyFindAll<HTMLInputElement>('input')
    expect(inputs[0].value).toBe('E:\\Downloads')
    expect(inputs[1].value).toBe('E:\\Installers')
    expect(mockGetDefaultPaths).toHaveBeenCalledOnce()

    wrapper.unmount()
  })

  // Validates: Requirement 5.4 — browse button calls openFolderDialog and fills input
  it('browse button for organize source calls openFolderDialog and fills input', async () => {
    const wrapper = mountDialog(true)
    await flushPromises()

    const browseButtons = bodyFindAll('button.browse-btn')
    browseButtons[0].click()
    await flushPromises()

    expect(mockOpenFolderDialog).toHaveBeenCalledOnce()
    const inputs = bodyFindAll<HTMLInputElement>('input')
    expect(inputs[0].value).toBe('C:\\Selected')

    wrapper.unmount()
  })

  // Validates: Requirement 5.4 — browse button for installer dir fills correct input
  it('browse button for installer dir calls openFolderDialog and fills input', async () => {
    const wrapper = mountDialog(true)
    await flushPromises()

    const browseButtons = bodyFindAll('button.browse-btn')
    browseButtons[1].click()
    await flushPromises()

    expect(mockOpenFolderDialog).toHaveBeenCalledOnce()
    const inputs = bodyFindAll<HTMLInputElement>('input')
    expect(inputs[1].value).toBe('C:\\Selected')

    wrapper.unmount()
  })

  // Validates: Requirement 5.6 — save button calls saveDefaultPaths and emits close
  it('save button calls saveDefaultPaths and emits close', async () => {
    const wrapper = mountDialog(true)
    await flushPromises()

    const saveBtn = bodyFind('button.save-btn') as HTMLButtonElement
    saveBtn.click()
    await flushPromises()

    expect(mockSaveDefaultPaths).toHaveBeenCalledWith('E:\\Downloads', 'E:\\Installers')
    expect(wrapper.emitted('close')).toBeTruthy()

    wrapper.unmount()
  })

  // Validates: Requirement 5.7 — cancel button emits close without saving
  it('cancel button emits close without saving', async () => {
    const wrapper = mountDialog(true)
    await flushPromises()

    const cancelBtn = bodyFind('button.cancel-btn') as HTMLButtonElement
    cancelBtn.click()
    await flushPromises()

    expect(mockSaveDefaultPaths).not.toHaveBeenCalled()
    expect(wrapper.emitted('close')).toBeTruthy()

    wrapper.unmount()
  })

  // Validates: Requirement 5.7 — ESC key emits close without saving
  it('ESC key emits close without saving', async () => {
    const wrapper = mountDialog(true)
    await flushPromises()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    expect(mockSaveDefaultPaths).not.toHaveBeenCalled()
    expect(wrapper.emitted('close')).toBeTruthy()

    wrapper.unmount()
  })

  // Validates: Requirement 5.7 — overlay click emits close without saving
  it('overlay click emits close without saving', async () => {
    const wrapper = mountDialog(true)
    await flushPromises()

    const overlay = bodyFind('.settings-overlay') as HTMLElement
    overlay.click()
    await flushPromises()

    expect(mockSaveDefaultPaths).not.toHaveBeenCalled()
    expect(wrapper.emitted('close')).toBeTruthy()

    wrapper.unmount()
  })

  // Validates: Requirement 6.1 — shows warning when save returns error, does NOT auto-close
  it('shows warning when save returns backend error, does not auto-close', async () => {
    mockSaveDefaultPaths.mockResolvedValue({ success: false, error: 'permission denied' })

    const wrapper = mountDialog(true)
    await flushPromises()

    const saveBtn = bodyFind('button.save-btn') as HTMLButtonElement
    saveBtn.click()
    await flushPromises()

    // Warnings should be visible on both fields
    const warnings = bodyFindAll('.warning-text')
    expect(warnings.length).toBeGreaterThan(0)

    // Dialog should NOT close automatically — user must cancel manually
    expect(wrapper.emitted('close')).toBeFalsy()

    wrapper.unmount()
  })

  // Validates: Requirement 5.2 — dialog is not rendered when visible=false
  it('does not render dialog content when visible is false', () => {
    const wrapper = mountDialog(false)
    expect(bodyFind('.settings-dialog')).toBeNull()
    wrapper.unmount()
  })
})
