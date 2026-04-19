<template>
  <div class="chat">
    <div class="messages" ref="msgEl">
      <div
        v-for="(m, i) in msgs"
        :key="i"
        :class="['wrap', `wrap-${m.role}`]"
      >
        <div
          :class="['bubble', `b-${m.role}`, { confirm: !!m.cid }]"
          v-html="hl(m.content)"
        ></div>
        <div v-if="m.cid && !m.done" class="confirm-row">
          <button class="btn btn-ghost csm yes" @click="resolve(m, true)">✅ 是</button>
          <button class="btn btn-ghost csm no"  @click="resolve(m, false)">❌ 否</button>
        </div>
        <div v-if="m.cid && m.done" class="answered">已确认</div>
      </div>

      <div v-if="thinking" class="wrap wrap-assistant">
        <div class="bubble b-assistant dots">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>

    <div class="input-row">
      <textarea
        v-model="text"
        class="inp"
        placeholder="输入指令，Enter 发送…"
        rows="1"
        @keydown="onKey"
      ></textarea>
      <button class="btn btn-primary send" @click="send" :disabled="!text.trim()">发送</button>
      <button class="btn btn-ghost send icon-btn" @click="clearCtx" title="清除上下文">🗑</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { usePyWebView } from '../composables/usePyWebView'

interface Msg { role: string; content: string; cid?: string; done?: boolean }

const msgs = ref<Msg[]>([])
const text = ref('')
const thinking = ref(false)
const msgEl = ref<HTMLElement | null>(null)
const api = usePyWebView()

function scroll() {
  nextTick(() => { if (msgEl.value) msgEl.value.scrollTop = msgEl.value.scrollHeight })
}

function push(role: string, content: string, cid?: string) {
  msgs.value.push({ role, content, cid, done: false })
  scroll()
}

function hl(t: string) {
  let s = t
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;')

  // 文件路径
  s = s.replace(
    /((?:[A-Za-z]:)?[/\\][^\s<>"]*|[^\s<>"]*\.(?:exe|zip|msi|dmg|tar|gz|pkg|deb|rpm))/g,
    x => `<span class="hl-path">${x}</span>`
  )

  // 成功关键词 — 带背景
  s = s.replace(
    /(整理完成|安装成功|已完成|完成|成功)/g,
    x => `<span class="hl-ok">${x}</span>`
  )

  // 错误关键词 — 带背景
  s = s.replace(
    /(超时|拒绝|失败|错误|异常|警告)/g,
    x => `<span class="hl-err">${x}</span>`
  )

  // 数字+单位
  s = s.replace(
    /(\d+(?:\.\d+)?)\s*(%|个|秒|ms|MB|GB|KB)/g,
    (_, n, u) => `<span class="hl-num">${n}</span>${u}`
  )

  // **bold**
  s = s.replace(/\*\*([^*]+)\*\*/g, (_, x) => `<strong>${x}</strong>`)

  return s
}

async function send() {
  const t = text.value.trim()
  if (!t) return
  push('user', t)
  text.value = ''
  thinking.value = true
  api.chatWithAgent(t)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
}

async function clearCtx() {
  await api.clearChatContext()
  msgs.value = []
}

async function resolve(m: Msg, answer: boolean) {
  if (m.done || !m.cid) return
  m.done = true
  api.resolveConfirmation?.(m.cid, answer)
}

onMounted(() => {
  window.appendChatMessage = (role, content) => {
    thinking.value = false
    push(role, content)
  }
  window.setChatThinking = (v) => { thinking.value = v }
  window.appendConfirmMessage = (raw) => {
    thinking.value = false
    const p = typeof raw === 'string' ? JSON.parse(raw) : raw
    push('system', p.message, p.id)
  }
})
</script>

<style scoped>
.chat { display: flex; flex-direction: column; height: 100%; overflow: hidden; }

.messages {
  flex: 1; overflow-y: auto; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 7px;
}

.wrap { display: flex; animation: fadeUp .18s ease-out both; }
.wrap-user      { justify-content: flex-end; }
.wrap-assistant { justify-content: flex-start; }
.wrap-system    { justify-content: center; flex-direction: column; align-items: center; }

.bubble {
  border-radius: var(--r-card); padding: 7px 11px;
  max-width: 84%; word-break: break-word; white-space: pre-wrap;
  font-size: 12.5px; line-height: 1.55;
}
.b-user {
  background: var(--grad-btn); color: #fff;
  border-radius: var(--r-card) var(--r-card) 4px var(--r-card);
}
.b-assistant {
  background: var(--glass);
  backdrop-filter: blur(var(--blur));
  border: 1px solid var(--border); color: var(--text);
  border-radius: var(--r-card) var(--r-card) var(--r-card) 4px;
}
.b-system {
  background: var(--accent-dim); color: var(--text-muted);
  font-size: 11.5px; text-align: center; max-width: 90%;
  border-radius: var(--r-sm);
}
.confirm {
  background: var(--warn-dim);
  border: 1px solid rgba(217,119,6,.3); color: var(--text); max-width: 90%;
}

/* Thinking dots */
.dots { display: flex; align-items: center; gap: 4px; padding: 9px 13px; }
.dots span {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--text-muted); animation: blink 1.2s infinite;
}
.dots span:nth-child(2) { animation-delay: .4s; }
.dots span:nth-child(3) { animation-delay: .8s; }

/* Confirm */
.confirm-row { display: flex; gap: 7px; margin-top: 5px; justify-content: center; }
.csm { padding: 4px 12px; font-size: 11.5px; border-radius: var(--r-sm); }
.yes { color: var(--success); border-color: var(--success); }
.yes:hover { background: var(--success-dim); }
.no  { color: var(--danger); border-color: var(--danger); }
.no:hover  { background: var(--danger-dim); }
.answered { font-size: 11px; color: var(--text-muted); font-style: italic; margin-top: 4px; }

/* Input */
.input-row {
  display: flex; gap: 7px; padding: 9px 12px;
  border-top: 1px solid var(--border); flex-shrink: 0;
}
.inp {
  flex: 1; resize: none; max-height: 90px; overflow-y: auto;
  background: rgba(255,255,255,.06); color: var(--text);
  border: 1px solid var(--border); border-radius: var(--r-sm);
  padding: 6px 11px; font-size: 12.5px; font-family: var(--font);
  outline: none; line-height: 1.5;
  transition: border-color .18s, box-shadow .18s;
}
.inp:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-dim); }
.inp::placeholder { color: var(--text-muted); }
.send { align-self: flex-end; padding: 6px 13px; font-size: 12.5px; border-radius: var(--r-sm); }
.icon-btn { padding: 6px 10px; }

/* ── Inline highlights ─────────────────────────────────────── */
:deep(.hl-path) {
  color: var(--accent); font-family: var(--font-mono);
  font-size: 11.5px; font-weight: 600;
  background: var(--accent-dim); border-radius: 3px; padding: 0 2px;
}
:deep(.hl-ok) {
  color: var(--success); font-weight: 800;
  background: var(--success-dim); border-radius: 3px; padding: 0 3px;
}
:deep(.hl-err) {
  color: var(--danger); font-weight: 800;
  background: var(--danger-dim); border-radius: 3px; padding: 0 3px;
}
:deep(.hl-num) {
  color: var(--accent); font-weight: 700;
}
</style>
