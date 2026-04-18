<template>
  <div class="log-viewer" ref="el">
    <p v-if="!logs.length" class="empty">暂无日志</p>
    <div
      v-for="(e, i) in logs"
      :key="i"
      class="entry"
      :class="e.cls"
      v-html="e.html"
    ></div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'

interface Entry { html: string; cls: string }

const MAX = 500
const logs = ref<Entry[]>([])
const el = ref<HTMLElement | null>(null)

function scroll() { if (el.value) el.value.scrollTop = el.value.scrollHeight }

function cls(msg: string) {
  if (/ERROR|错误|失败|异常|超时/.test(msg)) return 'err'
  if (/✓|完成|成功/i.test(msg)) return 'ok'
  if (/⚠️|警告|注意/.test(msg)) return 'warn'
  return ''
}

function esc(s: string) {
  return s
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;')
}

function sp(c: string, t: string) { return `<span class="${c}">${t}</span>` }

function render(msg: string) {
  let s = esc(msg)

  // 标签 [xxx]
  s = s.replace(/(\[[^\]]{1,30}\])/g, m => sp('t', m))

  // Windows 路径
  s = s.replace(/([A-Za-z]:[/\\][^\s<>"→]+)/g, m => sp('p', m))

  // 箭头
  s = s.replace(/\s*→\s*/g, ` <span class="arr">→</span> `)

  // 文件名
  s = s.replace(
    /\b([\w\-.]+\.(?:exe|msi|zip|rar|7z|pdf|docx?|xlsx?|py|ts|js|json|yaml|yml|log))\b/gi,
    m => sp('fn', m)
  )

  // **bold**
  s = s.replace(/\*\*([^*]+)\*\*/g, (_, x) => `<strong class="bold">${x}</strong>`)

  // 数字+单位
  s = s.replace(
    /(\d+(?:\.\d+)?)\s*(%|个|秒|ms|MB|GB|KB|次|条)/g,
    (_, n, u) => `${sp('num', n)}${u}`
  )

  // 置信度 conf=0.xx
  s = s.replace(/\b(conf=)(\d+\.\d+)/g, (_, pre, val) => `${pre}${sp('conf', val)}`)

  // 成功关键词 — 高亮更强
  s = s.replace(
    /(整理完成|任务完成|安装成功|移动成功|成功|✓|完成)/g,
    m => sp('ok-kw', m)
  )

  // 错误关键词 — 高亮更强
  s = s.replace(
    /(失败|错误|超时|异常|跳过|拒绝|⚠️|警告)/g,
    m => sp('err-kw', m)
  )

  return s
}

onMounted(() => {
  window.appendLog = (msg: string) => {
    if (logs.value.length >= MAX) logs.value.shift()
    logs.value.push({ html: render(msg), cls: cls(msg) })
    nextTick(scroll)
  }
})
</script>

<style scoped>
.log-viewer {
  flex: 1; overflow-y: auto; padding: 8px 12px;
  font-family: var(--font-mono); font-size: 13px; line-height: 1.65;
  color: var(--text-2); display: flex; flex-direction: column; gap: 1px;
}

.entry {
  padding: 2px 5px; border-radius: 4px;
  white-space: pre-wrap; word-break: break-word;
  animation: fadeUp .14s ease-out both;
  transition: background .15s;
}
.entry:hover { background: var(--accent-dim); }

/* 行级颜色 */
.err  { color: var(--danger); background: var(--danger-dim); border-radius: 4px; }
.ok   { color: var(--success); }
.warn { color: var(--warn); background: var(--warn-dim); border-radius: 4px; }

.empty {
  color: var(--text-muted); font-style: italic;
  font-family: var(--font); padding: 8px 5px;
}

/* ── Inline highlights ─────────────────────────────────────── */
:deep(.t) {
  color: var(--text-muted); font-size: 12px;
  background: var(--border); border-radius: 3px; padding: 0 3px;
}
:deep(.p) {
  color: var(--log-path-color, var(--accent)); font-weight: 700;
  background: var(--log-path-bg, var(--accent-dim)); border-radius: 3px; padding: 0 2px;
  text-decoration: underline dotted;
}
:deep(.fn)   { color: var(--log-fn-color, var(--accent)); font-weight: 600; }
:deep(.arr)  { color: var(--log-arr-color, var(--accent)); font-weight: 800; font-size: 14px; }
:deep(.num)  { color: var(--log-num-color, var(--accent)); font-weight: 700; }
:deep(.conf) { color: var(--warn); font-weight: 700; }
:deep(.bold) { font-weight: 800; color: var(--text); }

/* 成功关键词 — 带背景高亮 */
:deep(.ok-kw) {
  color: var(--log-ok-kw-color, var(--success)); font-weight: 800;
  background: var(--log-ok-kw-bg, var(--success-dim));
  border-radius: 3px; padding: 0 3px;
}

/* 错误关键词 — 带背景高亮 */
:deep(.err-kw) {
  color: var(--danger); font-weight: 800;
  background: var(--danger-dim);
  border-radius: 3px; padding: 0 3px;
}
</style>
