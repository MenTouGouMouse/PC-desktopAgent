<template>
  <Teleport to="body">
    <div v-if="visible" class="settings-overlay" @click.self="onOverlayClick">
      <div class="settings-dialog glass-card" role="dialog" aria-modal="true" aria-label="修改默认路径">
        <h2 class="dialog-title">⚙️ 修改默认路径</h2>

        <div class="field-group">
          <label class="field-label" for="organize-source">文件整理源目录</label>
          <div class="input-row">
            <input
              id="organize-source"
              v-model="organizeSource"
              type="text"
              class="path-input"
              placeholder="例如：E:\Downloads"
            />
            <button class="action-btn browse-btn" @click="browseOrganizeSource">浏览</button>
          </div>
          <p v-if="organizeSourceWarning" class="warning-text">保存失败，请检查路径或权限</p>
        </div>

        <div class="field-group">
          <label class="field-label" for="organize-target">文件整理目标目录</label>
          <div class="input-row">
            <input
              id="organize-target"
              v-model="organizeTarget"
              type="text"
              class="path-input"
              placeholder="例如：E:\Organized"
            />
            <button class="action-btn browse-btn" @click="browseOrganizeTarget">浏览</button>
          </div>
          <p class="hint-text">整理后的文件夹将命名为 YY.MM.DD-AgentOrganized</p>
        </div>

        <div class="field-group">
          <label class="field-label" for="installer-dir">智能安装默认目录</label>
          <div class="input-row">
            <input
              id="installer-dir"
              v-model="installerDefaultDir"
              type="text"
              class="path-input"
              placeholder="例如：E:\Installers"
            />
            <button class="action-btn browse-btn" @click="browseInstallerDir">浏览</button>
          </div>
          <p v-if="installerDirWarning" class="warning-text">保存失败，请检查路径或权限</p>
        </div>

        <div class="btn-row">
          <button class="action-btn save-btn" :disabled="isSaving" @click="onSave">
            {{ isSaving ? '保存中…' : '保存' }}
          </button>
          <button class="cancel-btn" @click="onCancel">取消</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { usePyWebView } from '../composables/usePyWebView'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const api = usePyWebView()

const organizeSource = ref('')
const organizeTarget = ref('')
const installerDefaultDir = ref('')
const organizeSourceWarning = ref(false)
const installerDirWarning = ref(false)
const isSaving = ref(false)

// Pre-fill values when dialog opens
watch(
  () => props.visible,
  async (val) => {
    if (!val) return
    organizeSourceWarning.value = false
    installerDirWarning.value = false
    try {
      const result = (await api.getDefaultPaths()) as any
      if (result && !result.error) {
        organizeSource.value = result.organize_source ?? ''
        organizeTarget.value = result.organize_target ?? ''
        installerDefaultDir.value = result.installer_default_dir ?? ''
      }
    } catch {
      // silently ignore — inputs stay empty
    }
  }
)

async function browseOrganizeSource() {
  try {
    const result = (await api.openFolderDialog()) as any
    if (result?.path) organizeSource.value = result.path
  } catch { /* ignore */ }
}

async function browseOrganizeTarget() {
  try {
    const result = (await api.openFolderDialog()) as any
    if (result?.path) organizeTarget.value = result.path
  } catch { /* ignore */ }
}

async function browseInstallerDir() {
  try {
    const result = (await api.openFolderDialog()) as any
    if (result?.path) installerDefaultDir.value = result.path
  } catch { /* ignore */ }
}

async function onSave() {
  if (isSaving.value) return
  isSaving.value = true
  organizeSourceWarning.value = false
  installerDirWarning.value = false

  try {
    const result = (await api.saveDefaultPaths(
      organizeSource.value,
      organizeTarget.value,
      installerDefaultDir.value
    )) as any

    if (result?.success === false) {
      organizeSourceWarning.value = true
      installerDirWarning.value = true
    } else {
      emit('close')
    }
  } catch {
    emit('close')
  } finally {
    isSaving.value = false
  }
}

function onCancel() {
  emit('close')
}

function onOverlayClick() {
  emit('close')
}

function onKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.visible) emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeyDown))
onUnmounted(() => window.removeEventListener('keydown', onKeyDown))
</script>

<style scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.settings-dialog {
  width: 480px;
  max-width: 90vw;
  padding: 28px 32px;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.dialog-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--accent-cyan);
  margin: 0;
}

.field-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 12px;
  color: var(--text-muted);
}

.input-row {
  display: flex;
  gap: 8px;
}

.path-input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid var(--border-glow);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
  color: inherit;
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
}

.path-input:focus {
  border-color: var(--accent-cyan);
}

.browse-btn {
  padding: 8px 14px;
  font-size: 13px;
  white-space: nowrap;
}

.btn-row {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.action-btn {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  background: var(--gradient-btn);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}

.action-btn:hover:not(:disabled) {
  opacity: 0.85;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.cancel-btn {
  padding: 10px 20px;
  border: 1px solid var(--border-glow);
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.2s, border-color 0.2s;
}

.cancel-btn:hover {
  color: var(--accent-cyan);
  border-color: var(--accent-cyan);
}

.warning-text {
  font-size: 11px;
  color: #f59e0b;
  margin: 0;
}

.hint-text {
  font-size: 11px;
  color: var(--text-muted);
  margin: 0;
  font-style: italic;
}
</style>
