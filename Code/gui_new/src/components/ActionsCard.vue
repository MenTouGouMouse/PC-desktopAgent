<template>
  <div class="actions-card">
    <div class="btn-row">
      <button class="btn btn-primary task-btn" :disabled="isRunning" @click="fileOrg">
        📁 文件整理
      </button>
      <button class="btn btn-primary task-btn" :disabled="isRunning || pending" @click="smartInst">
        {{ pending ? '选择中…' : '📦 智能安装' }}
      </button>
    </div>
    <button class="btn btn-danger stop-btn" :disabled="!isRunning" @click="stop">
      ⏹ 停止任务
    </button>

    <!-- Install mode dialog -->
    <div v-if="showMode" class="modal-overlay" @click.self="showMode = false">
      <div class="modal glass">
        <p class="modal-title">选择安装模式</p>
        <div class="modal-btns">
          <button class="btn btn-primary" @click="confirmMode('visual_with_fallback')">🖥 视觉安装（推荐）</button>
          <button class="btn btn-ghost"   @click="confirmMode('silent')">🔇 静默安装</button>
        </div>
        <button class="btn btn-ghost sm cancel" @click="showMode = false">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { usePyWebView } from '../composables/usePyWebView'

defineProps<{ isRunning: boolean }>()

const api = usePyWebView()
const pending = ref(false)
const showMode = ref(false)

function fileOrg() { api.startFileOrganizer() }
function smartInst() { if (!pending.value) showMode.value = true }

async function confirmMode(mode: string) {
  showMode.value = false
  pending.value = true
  try { await api.startSmartInstaller(mode) }
  finally { pending.value = false }
}

function stop() { api.stopTask() }
</script>

<style scoped>
.actions-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.btn-row {
  display: flex;
  gap: 8px;
}

.task-btn {
  flex: 1;
  justify-content: center;
  font-size: 13px;
  padding: 9px 8px;
}

.stop-btn {
  width: 100%;
  justify-content: center;
  font-size: 13px;
  padding: 9px;
}

/* ── Modal ────────────────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.35);
  display: flex; align-items: center; justify-content: center; z-index: 999;
}
.modal {
  padding: 22px; min-width: 270px;
  display: flex; flex-direction: column; gap: 14px;
}
.modal-title { font-size: 14px; font-weight: 700; color: var(--text); }
.modal-btns { display: flex; flex-direction: column; gap: 8px; }
.cancel { align-self: center; }
.sm { font-size: 12px; }
</style>
