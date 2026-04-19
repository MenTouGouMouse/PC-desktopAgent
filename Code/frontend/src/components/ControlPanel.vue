<template>
  <div class="glass-card control-panel">
    <div class="btn-row">
      <button class="action-btn" @click="onFileOrganizer">文件整理</button>
      <button class="action-btn" @click="onSmartInstaller" :disabled="installerPending">
        {{ installerPending ? '选择中…' : '智能安装' }}
      </button>
    </div>

    <div class="progress-section">
      <ProgressBar :percent="percent" :is-running="isRunning" :status-text="statusText" />
    </div>

    <div class="log-section">
      <p class="section-label">执行日志</p>
      <LogOutput />
    </div>

    <button class="minimize-btn" @click="onMinimize">最小化到悬浮球</button>

    <!-- 安装模式选择弹窗 -->
    <InstallModeDialog
      :visible="showModeDialog"
      @confirm="onModeConfirmed"
      @cancel="onModeCancel"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { usePyWebView } from '../composables/usePyWebView'
import ProgressBar from './ProgressBar.vue'
import LogOutput from './LogOutput.vue'
import InstallModeDialog from './InstallModeDialog.vue'

defineProps<{
  percent: number
  isRunning: boolean
  statusText?: string
}>()

const api = usePyWebView()
const installerPending = ref(false)
const showModeDialog = ref(false)

function onFileOrganizer() {
  api.startFileOrganizer()
}

function onSmartInstaller() {
  if (installerPending.value) return
  showModeDialog.value = true
}

async function onModeConfirmed(mode: 'silent' | 'visual_with_fallback') {
  showModeDialog.value = false
  installerPending.value = true
  try {
    await api.startSmartInstaller(mode)
  } finally {
    installerPending.value = false
  }
}

function onModeCancel() {
  showModeDialog.value = false
}

function onMinimize() {
  api.minimizeToBall()
}
</script>

<style scoped>
.control-panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 20px;
  height: 100%;
}

.btn-row {
  display: flex;
  gap: 12px;
}

.action-btn {
  flex: 1;
  padding: 10px 16px;
  border: none;
  border-radius: 8px;
  background: var(--gradient-btn);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}

.action-btn:hover {
  animation: btn-glow 1.5s ease-in-out infinite;
  opacity: 0.9;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  animation: none;
}

.progress-section {
  padding-top: 16px;
}

.section-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.log-section {
  flex: 1;
  min-height: 0;
}

.minimize-btn {
  padding: 8px 16px;
  border: 1px solid var(--border-glow);
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.2s, border-color 0.2s;
}

.minimize-btn:hover {
  color: var(--accent-cyan);
  border-color: var(--accent-cyan);
}
</style>
