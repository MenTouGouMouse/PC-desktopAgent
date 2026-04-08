<template>
  <div
    class="floating-ball"
    @mousedown="onMouseDown"
    @dblclick="onDblClick"
  >
    <RingProgress :percent="percent" />
    <div v-if="isRunning" class="pulse-dot" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import RingProgress from './components/RingProgress.vue'
import { usePyWebView } from './composables/usePyWebView'

const percent = ref<number>(0)
const isRunning = ref<boolean>(false)

const isDragging = ref(false)
let dragStartX = 0
let dragStartY = 0

const BALL_SIZE = 80

function onMouseDown(e: MouseEvent) {
  dragStartX = e.screenX - window.screenX
  dragStartY = e.screenY - window.screenY
  isDragging.value = true
  e.preventDefault()
}

function onMouseMove(e: MouseEvent) {
  if (!isDragging.value) return
  const newX = Math.max(0, Math.min(e.screenX - dragStartX, screen.width - BALL_SIZE))
  const newY = Math.max(0, Math.min(e.screenY - dragStartY, screen.height - BALL_SIZE))
  usePyWebView().moveBallWindow(newX, newY)
}

function onMouseUp() {
  isDragging.value = false
}

function onDblClick() {
  usePyWebView().restoreMainWindow()
}

onMounted(() => {
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)

  // Expose to window for evaluate_js calls from Python
  ;(window as any).updateProgress = (p: number, _t: string, r: boolean) => {
    percent.value = p
    isRunning.value = r
  }
})

onUnmounted(() => {
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
})
</script>

<style scoped>
.floating-ball {
  position: relative;
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: var(--bg-primary, #0a0e1a);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  user-select: none;
  overflow: hidden;
}

.pulse-dot {
  position: absolute;
  bottom: 14px;
  right: 14px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--accent-cyan, #00d4ff);
  animation: pulse 1.5s infinite;
}
</style>

<style>
body {
  background: transparent;
  margin: 0;
  overflow: hidden;
}
</style>
