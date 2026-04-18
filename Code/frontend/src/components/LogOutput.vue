<template>
  <div class="log-output" ref="logContainer">
    <p v-if="logs.length === 0" class="placeholder">暂无日志</p>
    <p
      v-for="(entry, i) in logs"
      :key="i"
      class="log-line"
      :class="entry.cls"
      v-html="entry.html"
    ></p>
  </div>
</template>

<script setup lang="ts">
import { ref, inject, watch, nextTick } from 'vue'

interface LogEntry {
  html: string
  cls: string
}

const logs = ref<LogEntry[]>([])
const logContainer = ref<HTMLElement | null>(null)

// 从 App.vue 注入日志数组
const appLogs = inject<ReturnType<typeof ref<string[]>>>('appLogs')!

function scrollToBottom() {
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
}

function classifyLog(msg: string): string {
  if (/ERROR|错误|失败/.test(msg)) return 'log-line--error'
  if (/✓|完成|成功|done/i.test(msg)) return 'log-line--success'
  if (/⚠️|警告|低置信度|待确认/.test(msg)) return 'log-line--warn'
  return ''
}

function wrapSpan(cls: string, text: string): string {
  return `<span class="${cls}">${text}</span>`
}

function renderLog(msg: string): string {
  let s = msg
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
  s = s.replace(/(\[[^\]]{1,30}\])/g, (m) => wrapSpan('hl-tag', m))
  s = s.replace(/([A-Za-z]:[/\\][^\s<>"→]+)/g, (m) => wrapSpan('hl-path', m))
  s = s.replace(/\s*→\s*/g, ` <span class="hl-arrow">→</span> `)
  s = s.replace(
    /\b([\w\-.]+\.(?:pdf|docx?|xlsx?|pptx?|txt|md|zip|rar|7z|exe|msi|jpg|jpeg|png|gif|mp4|mp3|csv|json|yaml|yml|py|ts|js))\b/gi,
    (m) => wrapSpan('hl-filename', m)
  )
  s = s.replace(/\*\*([^*]+)\*\*/g, (_, inner) => `<strong class="hl-bold">${inner}</strong>`)
  s = s.replace(
    /(\d+(?:\.\d+)?)\s*(%|个|秒|ms|MB|GB|KB)/g,
    (_, num, unit) => `${wrapSpan('hl-num', num)}${unit}`
  )
  s = s.replace(
    /\b(conf=)(\d+\.\d+)/g,
    (_, prefix, val) => `${prefix}${wrapSpan('hl-conf', val)}`
  )
  s = s.replace(/(整理完成|任务完成|移动成功|成功|✓|完成)/g, (m) => wrapSpan('hl-success', m))
  s = s.replace(/(失败|错误|超时|异常|跳过|⚠️|警告)/g, (m) => wrapSpan('hl-error', m))
  return s
}

// 监听 appLogs 新增条目
watch(
  () => appLogs.value.length,
  (newLen, oldLen) => {
    for (let i = oldLen ?? 0; i < newLen; i++) {
      const msg = appLogs.value[i]
      logs.value.push({ html: renderLog(msg), cls: classifyLog(msg) })
    }
    nextTick(() => scrollToBottom())
  }
)
</script>

<style scoped>
.log-output {
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  max-height: 200px;
  overflow-y: scroll;
  padding: 8px 10px;
  background: var(--bg-secondary);
  border-radius: 6px;
}

.log-line {
  margin: 3px 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.log-line--error { color: #ff6b6b; }
.log-line--success { color: var(--accent-green); }
.log-line--warn { color: #f59e0b; }

.placeholder {
  color: var(--text-muted);
  font-style: italic;
}

:deep(.hl-tag) {
  color: var(--text-muted);
  font-size: 11px;
  background: rgba(255,255,255,0.06);
  border-radius: 3px;
  padding: 0 3px;
}

:deep(.hl-path) {
  color: var(--accent-cyan);
  font-family: 'Courier New', monospace;
  font-weight: 700;
  background: rgba(0, 212, 255, 0.08);
  border-radius: 3px;
  padding: 0 2px;
}

:deep(.hl-filename) {
  color: var(--accent-cyan);
  font-weight: 600;
}

:deep(.hl-arrow) {
  color: var(--accent-cyan);
  font-weight: 800;
  font-size: 14px;
}

:deep(.hl-bold) {
  font-weight: 700;
  color: var(--text-primary);
}

:deep(.hl-num) {
  color: var(--accent-cyan);
  font-weight: 600;
}

:deep(.hl-conf) {
  color: #f59e0b;
  font-weight: 700;
}

:deep(.hl-success) {
  color: var(--accent-green);
  font-weight: 700;
}

:deep(.hl-error) {
  color: #ff4d6d;
  font-weight: 700;
}
</style>
