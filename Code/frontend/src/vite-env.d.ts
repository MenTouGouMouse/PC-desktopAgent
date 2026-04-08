/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

interface Window {
  updateFrame: (b64: string) => void
  appendLog: (msg: string) => void
  updateProgress: (percent: number, text: string, running: boolean) => void
}
