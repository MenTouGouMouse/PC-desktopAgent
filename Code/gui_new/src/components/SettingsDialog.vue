<template>
  <Teleport to="body">
    <div v-if="visible" class="overlay" @click.self="emit('close')">
      <div class="dialog glass">
        <div class="dialog-header">
          <span class="dialog-title">⚙️ 路径设置</span>
          <button class="btn btn-ghost close-btn" @click="emit('close')">✕</button>
        </div>

        <div class="fields">
          <div class="field" v-for="f in fields" :key="f.key">
            <label class="field-label">{{ f.label }}</label>
            <div class="field-row">
              <input
                class="field-input"
                type="text"
                v-model="paths[f.key]"
                :placeholder="f.placeholder"
              />
              <button class="btn btn-ghost pick-btn" @click="pickFolder(f.key)">📁</button>
            </div>
          </div>
        </div>

        <div v-if="msg" class="msg" :class="msgType">{{ msg }}</div>

        <div class="dialog-footer">
          <button class="btn btn-ghost" @click="emit('close')">取消</button>
          <button class="btn btn-primary" @click="save" :disabled="saving">
            {{ saving ? '保存中…' : '💾 保存' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { usePyWebView } from '../composables/usePyWebView'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ close: [] }>()

const api = usePyWebView()
const saving = ref(false)
const msg = ref('')
const msgType = ref<'ok' | 'err'>('ok')

const paths = ref({ organize_source: '', organize_target: '', installer_default_dir: '' })

const fields = [
  { key: 'organize_source' as const,       label: '整理源目录',     placeholder: '选择或输入路径…' },
  { key: 'organize_target' as const,       label: '整理目标目录',   placeholder: '选择或输入路径…' },
  { key: 'installer_default_dir' as const, label: '安装包默认目录', placeholder: '选择或输入路径…' },
]

watch(() => props.visible, async (v) => {
  if (!v) return
  msg.value = ''
  const res = await api.getDefaultPaths() as Record<string, string> | null
  if (res) {
    paths.value.organize_source = res.organize_source ?? ''
    paths.value.organize_target = res.organize_target ?? ''
    paths.value.installer_default_dir = res.installer_default_dir ?? ''
  }
})

async function pickFolder(key: keyof typeof paths.value) {
  const res = await api.openFolderDialog() as { path: string } | null
  if (res?.path) paths.value[key] = res.path
}

async function save() {
  saving.value = true; msg.value = ''
  try {
    const res = await api.saveDefaultPaths(
      paths.value.organize_source,
      paths.value.organize_target,
      paths.value.installer_default_dir,
    ) as { success: boolean; error?: string } | null
    if (res?.success === false) {
      msg.value = res.error ?? '保存失败'; msgType.value = 'err'
    } else {
      msg.value = '✅ 已保存'; msgType.value = 'ok'
      setTimeout(() => emit('close'), 800)
    }
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,.38);
  display: flex; align-items: center; justify-content: center;
  animation: fadeUp .18s ease-out both;
}

.dialog {
  width: 420px; max-width: 92vw;
  display: flex; flex-direction: column; gap: 0;
  overflow: hidden;
}

.dialog-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--border);
}
.dialog-title { font-size: 14px; font-weight: 700; color: var(--text); }
.close-btn { padding: 4px 8px; font-size: 13px; border-radius: var(--r-sm); }

.fields { padding: 16px 18px; display: flex; flex-direction: column; gap: 14px; }

.field { display: flex; flex-direction: column; gap: 5px; }
.field-label {
  font-size: 11px; font-weight: 700; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: .5px;
}
.field-row { display: flex; gap: 6px; }
.field-input {
  flex: 1; height: 34px; padding: 0 12px;
  background: rgba(255,255,255,.06); color: var(--text);
  border: 1px solid var(--border); border-radius: var(--r-sm);
  font-size: 13px; font-family: var(--font); outline: none;
  transition: border-color .18s, box-shadow .18s;
}
.field-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-dim); }
.field-input::placeholder { color: var(--text-muted); }
.pick-btn { padding: 0 10px; height: 34px; border-radius: var(--r-sm); font-size: 14px; }

.msg {
  margin: 0 18px; padding: 7px 12px; border-radius: var(--r-sm);
  font-size: 12px; font-weight: 600;
}
.msg.ok  { background: var(--success-dim); color: var(--success); }
.msg.err { background: var(--danger-dim);  color: var(--danger); }

.dialog-footer {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 14px 18px; border-top: 1px solid var(--border);
}
</style>
