/**
 * usePyWebView — typed wrapper around window.pywebview.api.*
 * Gracefully degrades when running outside PyWebView (dev mode).
 */

export interface PyWebViewAPI {
  startFileOrganizer: () => Promise<unknown> | undefined
  startSmartInstaller: (mode?: string) => Promise<unknown> | undefined
  stopTask: () => Promise<unknown> | undefined
  chatWithAgent: (message: string) => Promise<unknown> | undefined
  clearChatContext: () => Promise<unknown> | undefined
  getProgress: () => Promise<unknown> | undefined
  minimizeToBall: () => Promise<unknown> | undefined
  restoreMainWindow: () => Promise<unknown> | undefined
  moveBallWindow: (x: number, y: number) => Promise<unknown> | undefined
  setShowBoxes: (show: boolean) => Promise<unknown> | undefined
  getDefaultPaths: () => Promise<unknown> | undefined
  saveDefaultPaths: (src: string, tgt: string, dir: string) => Promise<unknown> | undefined
  openFolderDialog: () => Promise<unknown> | undefined
  resolveConfirmation: (id: string, answer: boolean) => Promise<unknown> | undefined
}

export function usePyWebView(): PyWebViewAPI {
  const api = () => (window as unknown as { pywebview?: { api: Record<string, (...a: unknown[]) => Promise<unknown>> } }).pywebview?.api

  return {
    startFileOrganizer: () => api()?.start_file_organizer(),
    startSmartInstaller: (mode = 'visual_with_fallback') => api()?.start_smart_installer(mode),
    stopTask: () => api()?.stop_task(),
    chatWithAgent: (msg) => api()?.chat_with_agent(msg),
    clearChatContext: () => api()?.clear_chat_context(),
    getProgress: () => api()?.get_progress(),
    minimizeToBall: () => api()?.minimize_to_ball(),
    restoreMainWindow: () => api()?.restore_main_window(),
    moveBallWindow: (x, y) => api()?.move_ball_window(x, y),
    setShowBoxes: (show) => api()?.set_show_boxes(show),
    getDefaultPaths: () => api()?.get_default_paths(),
    saveDefaultPaths: (src, tgt, dir) => api()?.save_default_paths(src, tgt, dir),
    openFolderDialog: () => api()?.open_folder_dialog(),
    resolveConfirmation: (id, answer) => api()?.resolve_confirmation(id, answer),
  }
}
