/**
 * Typed wrapper around window.pywebview.api.*
 * Gracefully handles missing window.pywebview (dev mode without PyWebView).
 * All methods return undefined when the api is not available.
 */

export interface PyWebViewAPI {
  startFileOrganizer: () => Promise<unknown> | undefined;
  startSmartInstaller: () => Promise<unknown> | undefined;
  minimizeToBall: () => Promise<unknown> | undefined;
  restoreMainWindow: () => Promise<unknown> | undefined;
  getProgress: () => Promise<unknown> | undefined;
  stopTask: () => Promise<unknown> | undefined;
  moveBallWindow: (x: number, y: number) => Promise<unknown> | undefined;
  chatWithAgent: (message: string) => Promise<unknown> | undefined;
  clearChatContext: () => Promise<unknown> | undefined;
  setShowBoxes: (show: boolean) => Promise<unknown> | undefined;
  getDefaultPaths: () => Promise<unknown> | undefined;
  saveDefaultPaths: (organizeSource: string, organizeTarget: string, installerDefaultDir: string) => Promise<unknown> | undefined;
  openFolderDialog: () => Promise<unknown> | undefined;
  resolveConfirmation: (confirmId: string, answer: boolean) => Promise<unknown> | undefined;
}

export function usePyWebView(): PyWebViewAPI {
  // Resolve api lazily at call time, not at composable init time.
  // This ensures the PyWebView JS bridge is available even if it is
  // injected after the Vue component has already mounted.
  const getApi = () => (window as any).pywebview?.api;

  return {
    startFileOrganizer: () => getApi()?.start_file_organizer(),
    startSmartInstaller: () => getApi()?.start_smart_installer(),
    minimizeToBall: () => getApi()?.minimize_to_ball(),
    restoreMainWindow: () => getApi()?.restore_main_window(),
    getProgress: () => getApi()?.get_progress(),
    stopTask: () => getApi()?.stop_task(),
    moveBallWindow: (x: number, y: number) => getApi()?.move_ball_window(x, y),
    chatWithAgent: (message: string) => getApi()?.chat_with_agent(message),
    clearChatContext: () => getApi()?.clear_chat_context(),
    setShowBoxes: (show: boolean) => getApi()?.set_show_boxes(show),
    getDefaultPaths: () => getApi()?.get_default_paths(),
    saveDefaultPaths: (organizeSource: string, organizeTarget: string, installerDefaultDir: string) => getApi()?.save_default_paths(organizeSource, organizeTarget, installerDefaultDir),
    openFolderDialog: () => getApi()?.open_folder_dialog(),
    resolveConfirmation: (confirmId: string, answer: boolean) => getApi()?.resolve_confirmation(confirmId, answer),
  };
}
