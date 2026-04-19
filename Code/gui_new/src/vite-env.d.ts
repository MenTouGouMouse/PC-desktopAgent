/// <reference types="vite/client" />

// Global callbacks injected by Python via evaluate_js
interface Window {
  updateFrame: (b64: string) => void
  updateProgress: (percent: number, statusText: string, isRunning: boolean) => void
  appendLog: (message: string) => void
  appendChatMessage: (role: string, content: string) => void
  appendConfirmMessage: (payload: string) => void
  setChatThinking: (thinking: boolean) => void
}
