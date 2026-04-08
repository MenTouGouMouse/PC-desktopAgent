<template>
  <div class="chat-interface">
    <!-- Message history -->
    <div class="chat-messages" ref="messagesEl">
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        :class="['bubble-wrap', `bubble-wrap--${msg.role}`]"
      >
        <div :class="['bubble', `bubble--${msg.role}`, { 'bubble--confirm': !!msg.confirmId }]"
             v-html="highlightContent(msg.content)">
        </div>
        <!-- Inline yes/no buttons for confirm messages -->
        <div v-if="msg.confirmId && !msg.confirmed" class="confirm-actions">
          <button class="confirm-btn confirm-btn--yes" @click="resolveConfirm(msg, true)">✅ 是</button>
          <button class="confirm-btn confirm-btn--no" @click="resolveConfirm(msg, false)">❌ 否</button>
        </div>
        <div v-if="msg.confirmId && msg.confirmed" class="confirm-answered">
          已确认
        </div>
      </div>

      <!-- Thinking animation -->
      <div v-if="isThinking" class="bubble-wrap bubble-wrap--assistant">
        <div class="bubble bubble--assistant thinking">
          <span class="dot"></span>
          <span class="dot"></span>
          <span class="dot"></span>
        </div>
      </div>
    </div>

    <!-- Input area -->
    <div class="chat-input-area">
      <textarea
        v-model="inputText"
        class="chat-input"
        placeholder="输入任务指令，按 Enter 发送..."
        rows="1"
        @keydown="onKeydown"
      ></textarea>
      <button class="send-btn" @click="sendMessage" :disabled="!inputText.trim()">
        发送
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { usePyWebView } from '../composables/usePyWebView'

interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  confirmId?: string   // present for confirm-type messages
  confirmed?: boolean  // true once user has answered
}

const messages = ref<ChatMessage[]>([])
const inputText = ref<string>('')
const isThinking = ref<boolean>(false)
const messagesEl = ref<HTMLElement | null>(null)

const { chatWithAgent, resolveConfirmation } = usePyWebView()

/**
 * Highlight_Renderer: transforms plain text into HTML with semantic highlights.
 * Priority order: file paths → success keywords → error keywords → numbers+units → **bold**
 */
function highlightContent(text: string): string {
  // Escape HTML to prevent XSS before applying highlights
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')

  // Track whether any rule matched
  let result = escaped

  // 1. File paths: starts with / or \, or contains common installer/archive extensions
  result = result.replace(
    /((?:[A-Za-z]:)?[/\\][^\s<>"]*|[^\s<>"]*\.(?:exe|zip|msi|dmg|tar|gz|pkg|deb|rpm))/g,
    '<span style="color:var(--accent-cyan);font-family:monospace">$1</span>'
  )

  // 2. Success keywords
  result = result.replace(
    /(整理完成|安装成功|已完成|完成|成功)/g,
    '<span style="color:var(--accent-green);font-weight:600">$1</span>'
  )

  // 3. Error/warning keywords
  result = result.replace(
    /(超时|拒绝|失败|错误|异常|警告)/g,
    '<span style="color:#ff4d6d;font-weight:600">$1</span>'
  )

  // 4. Numbers + units (highlight only the numeric part)
  result = result.replace(
    /(\d+(?:\.\d+)?)(\s*(?:%|个|秒|分钟|小时|MB|GB|KB|ms|px|次|条|行|项))/g,
    '<span style="color:var(--accent-cyan);font-weight:600">$1</span>$2'
  )

  // 5. **bold** markdown
  result = result.replace(
    /\*\*([^*]+)\*\*/g,
    '<span style="font-weight:600">$1</span>'
  )

  return result
}

function scrollToBottom(): void {
  nextTick(() => {
    if (messagesEl.value) {
      messagesEl.value.scrollTop = messagesEl.value.scrollHeight - messagesEl.value.clientHeight
    }
  })
}

function appendMessage(role: 'user' | 'assistant' | 'system', content: string): void {
  messages.value.push({ role, content, timestamp: Date.now() })
  scrollToBottom()
}

async function sendMessage(): Promise<void> {
  const text = inputText.value.trim()
  if (!text) return

  appendMessage('user', text)
  inputText.value = ''
  isThinking.value = true

  chatWithAgent(text)
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

async function resolveConfirm(msg: ChatMessage, answer: boolean): Promise<void> {
  if (msg.confirmed || !msg.confirmId) return
  msg.confirmed = true
  resolveConfirmation?.(msg.confirmId, answer)
}

onMounted(() => {
  // Expose global functions for Python evaluate_js calls
  ;(window as any).appendChatMessage = (role: 'user' | 'assistant' | 'system', content: string) => {
    isThinking.value = false
    appendMessage(role, content)
  }
  ;(window as any).setChatThinking = (thinking: boolean) => {
    isThinking.value = thinking
  }
  ;(window as any).appendConfirmMessage = (payload: { type: string; id: string; message: string }) => {
    isThinking.value = false
    messages.value.push({
      role: 'system',
      content: payload.message,
      timestamp: Date.now(),
      confirmId: payload.id,
      confirmed: false,
    })
    scrollToBottom()
  }
})
</script>

<style scoped>
.chat-interface {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-glow);
  overflow: hidden;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bubble-wrap {
  display: flex;
  animation: box-fadein 0.3s ease-out;
}

.bubble-wrap--user {
  justify-content: flex-end;
}

.bubble-wrap--assistant {
  justify-content: flex-start;
}

.bubble-wrap--system {
  justify-content: center;
  flex-direction: column;
  align-items: center;
}

.bubble {
  border-radius: 8px;
  padding: 4px 8px;
  max-width: 80%;
  word-break: break-word;
  white-space: pre-wrap;
}

.bubble--user {
  background: var(--gradient-btn);
  color: #ffffff;
}

.bubble--assistant {
  background: var(--bg-glass);
  color: var(--text-primary);
}

.bubble--system {
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}

/* Thinking animation */
.thinking {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
  animation: blink 1.2s infinite;
}

.dot:nth-child(2) {
  animation-delay: 0.4s;
}

.dot:nth-child(3) {
  animation-delay: 0.8s;
}

@keyframes blink {
  0%, 80%, 100% { opacity: 0.2; }
  40% { opacity: 1; }
}

/* Input area */
.chat-input-area {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid var(--border-glow);
  background: var(--bg-secondary);
}

.chat-input {
  flex: 1;
  resize: none;
  max-height: 120px;
  overflow-y: auto;
  background: var(--bg-glass);
  color: var(--text-primary);
  border: 1px solid var(--border-glow);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  line-height: 1.5;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.chat-input:focus {
  border-color: var(--accent-cyan);
  box-shadow: 0 0 8px rgba(0, 212, 255, 0.4);
}

.chat-input::placeholder {
  color: var(--text-muted);
}

.send-btn {
  background: var(--gradient-btn);
  color: #ffffff;
  border: none;
  border-radius: 8px;
  padding: 6px 16px;
  cursor: pointer;
  font-size: 14px;
  white-space: nowrap;
  align-self: flex-end;
  transition: box-shadow 0.2s;
}

.send-btn:hover:not(:disabled) {
  animation: btn-glow 2s infinite;
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Confirm message bubble */
.bubble--confirm {
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: var(--text-primary);
  text-align: left;
  white-space: pre-wrap;
  max-width: 90%;
}

/* Confirm yes/no action row */
.confirm-actions {
  display: flex;
  gap: 8px;
  margin-top: 6px;
  justify-content: center;
}

.confirm-btn {
  padding: 4px 16px;
  border-radius: 6px;
  border: none;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s, box-shadow 0.2s;
}

.confirm-btn--yes {
  background: rgba(0, 255, 136, 0.2);
  border: 1px solid var(--accent-green);
  color: var(--accent-green);
}

.confirm-btn--yes:hover {
  background: rgba(0, 255, 136, 0.35);
  box-shadow: 0 0 8px rgba(0, 255, 136, 0.4);
}

.confirm-btn--no {
  background: rgba(255, 77, 109, 0.15);
  border: 1px solid #ff4d6d;
  color: #ff4d6d;
}

.confirm-btn--no:hover {
  background: rgba(255, 77, 109, 0.3);
  box-shadow: 0 0 8px rgba(255, 77, 109, 0.4);
}

.confirm-answered {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
  text-align: center;
  font-style: italic;
}
</style>
