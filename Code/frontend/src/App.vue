<template>
  <div class="app-root">
    <div class="preview-pane">
      <ScreenPreview />
    </div>
    <div class="right-pane">
      <div class="control-section">
        <ControlPanel :percent="appPercent" :is-running="appIsRunning" />
      </div>
      <div class="chat-section">
        <ChatInterface />
      </div>
    </div>
  </div>
  <SettingsDialog :visible="settingsVisible" @close="settingsVisible = false" />
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import ScreenPreview from './components/ScreenPreview.vue'
import ControlPanel from './components/ControlPanel.vue'
import ChatInterface from './components/ChatInterface.vue'
import SettingsDialog from './components/SettingsDialog.vue'

const appPercent = ref<number>(0)
const appIsRunning = ref<boolean>(false)
const settingsVisible = ref<boolean>(false)

onMounted(() => {
  ;(window as any).updateProgress = (p: number, _t: string, r: boolean) => {
    appPercent.value = p
    appIsRunning.value = r
  }
})
</script>

<style scoped>
.app-root {
  display: flex;
  flex-direction: row;
  width: 100vw;
  height: 100vh;
  background: var(--bg-primary);
  overflow: hidden;
}

.preview-pane {
  width: 60%;
  height: 100%;
  padding: 16px;
  box-sizing: border-box;
}

.right-pane {
  width: 40%;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px;
  gap: 12px;
  box-sizing: border-box;
}

.control-section {
  flex-shrink: 0;
}

.chat-section {
  flex: 1;
  min-height: 0;
}
</style>
