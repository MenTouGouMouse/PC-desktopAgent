<template>
  <div class="screen-preview-wrapper">
    <div class="toolbar">
      <button
        class="toggle-btn"
        :class="{ active: showBoxes }"
        @click="toggleShowBoxes"
      >
        {{ showBoxes ? '✅ 识别框已启用' : '🔍 显示识别框' }}
      </button>
      <button class="toggle-btn" @click="showSettings = true">
        ⚙️ 修改默认路径
      </button>
    </div>
    <div class="screen-preview">
      <img v-if="frameSrc" :src="frameSrc" class="preview-img" alt="屏幕预览" />
      <div v-else class="placeholder">等待屏幕预览...</div>
    </div>
    <SettingsDialog :visible="showSettings" @close="showSettings = false" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePyWebView } from '../composables/usePyWebView'
import SettingsDialog from './SettingsDialog.vue'

const frameSrc = ref<string>('')
const showBoxes = ref<boolean>(false)
const showSettings = ref<boolean>(false)
const { setShowBoxes } = usePyWebView()

async function toggleShowBoxes() {
  showBoxes.value = !showBoxes.value
  try {
    const result = await setShowBoxes(showBoxes.value)
    console.log('[ScreenPreview] set_show_boxes result:', result)
  } catch (e) {
    console.error('[ScreenPreview] set_show_boxes error:', e)
    // 回滚状态，避免前后端不一致
    showBoxes.value = !showBoxes.value
  }
}

onMounted(() => {
  showBoxes.value = false

  /**
   * updateFrame — 由 Python push_frame() 通过 evaluate_js 调用。
   * 接收 base64 JPEG 字符串，更新预览图像。
   * 追加时间戳参数防止浏览器缓存旧帧。
   */
  window.updateFrame = (b64: string) => {
    if (!b64) {
      console.warn('[ScreenPreview] updateFrame: 收到空 base64 字符串，跳过')
      return
    }
    // 直接使用 data URI，不需要时间戳（data URI 不走 HTTP 缓存）
    frameSrc.value = 'data:image/jpeg;base64,' + b64
  }
})
</script>

<style scoped>
.screen-preview-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toolbar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.toggle-btn {
  align-self: flex-start;
  padding: 6px 14px;
  border-radius: 8px;
  border: 1px solid var(--border-glow);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s, color 0.2s;
}

.toggle-btn:hover {
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

.toggle-btn.active {
  background: rgba(0, 255, 136, 0.15);
  border-color: var(--accent-green);
  color: var(--accent-green);
}

.screen-preview {
  width: 100%;
  flex: 1;
  border: 2px solid var(--accent-green);
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-secondary);
}

.preview-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.placeholder {
  color: var(--text-muted);
  font-size: 14px;
}
</style>
