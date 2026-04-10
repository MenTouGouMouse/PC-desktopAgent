<template>
  <Teleport to="body">
    <div v-if="visible" class="overlay" @click.self="onCancel">
      <div class="dialog glass-card" role="dialog" aria-modal="true" aria-label="选择安装模式">

        <h2 class="dialog-title">🚀 选择安装模式</h2>
        <p class="dialog-subtitle">请选择本次智能安装的执行方式</p>

        <div class="mode-cards">
          <!-- 静默安装 -->
          <button
            class="mode-card"
            :class="{ selected: selected === 'silent' }"
            @click="selected = 'silent'"
          >
            <span class="mode-icon">⚡</span>
            <span class="mode-name">静默安装</span>
            <span class="mode-desc">通过控件 API 精准定位按钮，无视觉调用，速度最快，稳定可靠</span>
            <span class="mode-badge silent-badge">推荐</span>
          </button>

          <!-- 视觉安装 -->
          <button
            class="mode-card"
            :class="{ selected: selected === 'visual_with_fallback' }"
            @click="selected = 'visual_with_fallback'"
          >
            <span class="mode-icon">👁️</span>
            <span class="mode-name">视觉安装</span>
            <span class="mode-desc">AI 视觉优先识别按钮并展示检测框，识别失败时自动降级到控件 API 兜底</span>
            <span class="mode-badge visual-badge">展示</span>
          </button>
        </div>

        <div class="btn-row">
          <button class="action-btn" :disabled="!selected" @click="onConfirm">
            开始安装
          </button>
          <button class="cancel-btn" @click="onCancel">取消</button>
        </div>

      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (e: 'confirm', mode: 'silent' | 'visual_with_fallback'): void
  (e: 'cancel'): void
}>()

const selected = ref<'silent' | 'visual_with_fallback'>('silent')

// Reset selection each time dialog opens
watch(() => props.visible, (val) => {
  if (val) selected.value = 'silent'
})

function onConfirm() {
  if (!selected.value) return
  emit('confirm', selected.value)
}

function onCancel() {
  emit('cancel')
}

function onKeyDown(e: KeyboardEvent) {
  if (!props.visible) return
  if (e.key === 'Escape') emit('cancel')
  if (e.key === 'Enter' && selected.value) emit('confirm', selected.value)
}

onMounted(() => window.addEventListener('keydown', onKeyDown))
onUnmounted(() => window.removeEventListener('keydown', onKeyDown))
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog {
  width: 460px;
  max-width: 92vw;
  padding: 28px 32px;
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.dialog-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--accent-cyan);
  margin: 0;
}

.dialog-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  margin: -12px 0 0;
}

/* ── Mode cards ─────────────────────────────────────────────────── */
.mode-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mode-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 16px 18px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.2s, background 0.2s;
}

.mode-card:hover {
  border-color: var(--border-glow);
  background: rgba(0, 212, 255, 0.04);
}

.mode-card.selected {
  border-color: var(--accent-cyan);
  background: rgba(0, 212, 255, 0.08);
  box-shadow: 0 0 0 1px var(--accent-cyan) inset;
}

.mode-icon {
  font-size: 22px;
  line-height: 1;
  margin-bottom: 2px;
}

.mode-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.mode-desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.mode-badge {
  position: absolute;
  top: 12px;
  right: 14px;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 20px;
  letter-spacing: 0.5px;
}

.silent-badge {
  background: rgba(0, 255, 136, 0.15);
  color: var(--accent-green);
  border: 1px solid rgba(0, 255, 136, 0.3);
}

.visual-badge {
  background: rgba(124, 58, 237, 0.2);
  color: #a78bfa;
  border: 1px solid rgba(124, 58, 237, 0.4);
}

/* ── Buttons ────────────────────────────────────────────────────── */
.btn-row {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.action-btn {
  padding: 10px 24px;
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
  opacity: 0.4;
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
</style>
