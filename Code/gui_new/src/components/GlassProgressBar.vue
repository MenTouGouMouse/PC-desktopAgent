<template>
  <div class="prog-wrap">
    <!-- 进度条主体 -->
    <div class="prog-track">
      <div class="prog-groove">
        <!-- 填充条 -->
        <div
          class="prog-fill"
          :style="{ width: clampedPercent + '%' }"
          :class="{ running: isRunning }"
        >
          <!-- 顶部高光线 -->
          <div class="prog-shine"></div>
          <!-- 扫光层 -->
          <div v-if="isRunning" class="prog-sweep"></div>
          <div v-if="isRunning" class="prog-sweep2"></div>
          <!-- 前端光晕 -->
          <div v-if="isRunning && clampedPercent > 2" class="prog-glow-tip"></div>
          <!-- 百分比文字（内嵌在填充条右侧） -->
          <span v-if="clampedPercent > 8" class="pct-inner">{{ clampedPercent }}%</span>
        </div>
      </div>
    </div>

    <!-- 状态文字 -->
    <div class="prog-info">
      <span class="status-txt">{{ statusText }}</span>
      <span v-if="clampedPercent <= 8" class="pct-outer">{{ clampedPercent }}%</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  percent: number
  isRunning: boolean
  statusText: string
}>()

const clampedPercent = computed(() => Math.min(100, Math.max(0, props.percent)))
</script>

<style scoped>
.prog-wrap {
  display: flex;
  flex-direction: column;
  gap: 3px;
  width: 100%;
}

/* ── 轨道 ────────────────────────────────────────────────── */
.prog-track { position: relative; }

.prog-groove {
  height: 16px;
  border-radius: 8px;
  background: rgba(100,120,180,.08);
  box-shadow:
    inset 0 2px 4px rgba(0,0,0,.15),
    inset 0 -1px 2px rgba(255,255,255,.05);
  border: 1px solid rgba(255,255,255,.10);
  overflow: hidden;
  position: relative;
}

html.dark .prog-groove {
  background: rgba(0,0,0,.30);
  border-color: rgba(255,255,255,.07);
}

/* ── 填充条 ──────────────────────────────────────────────── */
.prog-fill {
  height: 100%;
  border-radius: 6px;
  position: relative;
  overflow: hidden;
  transition: width .45s cubic-bezier(.2,.9,.4,1.05);
  will-change: width;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;

  /* Light 主题 — 紫蓝渐变 */
  background: linear-gradient(90deg, #5b6fd4 0%, #7b8cde 40%, #a78bfa 100%);
  background-size: 200% 100%;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.55),
    inset 0 -1px 0 rgba(60,40,160,.25),
    0 4px 14px rgba(91,111,212,.45),
    0 0 20px rgba(167,139,250,.20);
}

/* Dark 主题 */
html.dark .prog-fill {
  background: linear-gradient(90deg, #4a5bc4 0%, #7b8cde 40%, #9aaaf0 100%);
  background-size: 200% 100%;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.35),
    inset 0 -1px 0 rgba(30,20,120,.35),
    0 4px 16px rgba(123,140,222,.50),
    0 0 24px rgba(154,170,240,.25);
}

/* Canva-Color 主题 — 青色到绿色 */
:global(.theme-canva) .prog-fill {
  background: linear-gradient(90deg, #00b4d8 0%, #00d4ff 45%, #00ff88 100%);
  background-size: 200% 100%;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.45),
    inset 0 -1px 0 rgba(0,100,140,.30),
    0 4px 16px rgba(0,212,255,.50),
    0 0 28px rgba(0,255,136,.25);
}

/* 运行时背景流动 */
.prog-fill.running {
  animation: bgFlow 3s linear infinite;
}

@keyframes bgFlow {
  0%   { background-position: 0% 0%; }
  100% { background-position: 200% 0%; }
}

/* 光栅纹理 */
.prog-fill::before {
  content: '';
  position: absolute; inset: 0;
  background-image: repeating-linear-gradient(
    -48deg,
    transparent, transparent 4px,
    rgba(255,255,255,.04) 4px, rgba(255,255,255,.04) 6px
  );
  pointer-events: none;
}

/* ── 顶部高光线 ──────────────────────────────────────────── */
.prog-shine {
  position: absolute;
  top: 2px; left: 10px; right: 10px; height: 3px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255,255,255,.50) 25%,
    rgba(255,255,255,.70) 50%,
    rgba(255,255,255,.45) 75%,
    transparent 100%
  );
  border-radius: 99px;
  pointer-events: none;
}

/* ── 主扫光 ──────────────────────────────────────────────── */
.prog-sweep {
  position: absolute; inset: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255,255,255,.0) 25%,
    rgba(255,255,255,.38) 50%,
    rgba(255,255,255,.0) 75%,
    transparent 100%
  );
  animation: progSweep 2.2s cubic-bezier(.4,0,.6,1) infinite;
  pointer-events: none;
}

.prog-sweep2 {
  position: absolute; inset: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255,255,255,.0) 15%,
    rgba(255,255,255,.18) 35%,
    rgba(255,255,255,.0) 55%,
    transparent 100%
  );
  animation: progSweep 1.5s cubic-bezier(.4,0,.6,1) infinite .6s;
  pointer-events: none;
}

@keyframes progSweep {
  0%   { transform: translateX(-130%); opacity: 0; }
  10%  { opacity: 1; }
  90%  { opacity: 1; }
  100% { transform: translateX(230%); opacity: 0; }
}

/* ── 前端光晕 ────────────────────────────────────────────── */
.prog-glow-tip {
  position: absolute;
  top: -6px; right: -10px;
  width: 28px; height: calc(100% + 12px);
  /* Light */
  background: radial-gradient(ellipse at 30% 50%, rgba(167,139,250,.65) 0%, rgba(91,111,212,.28) 45%, transparent 70%);
  border-radius: 50%;
  pointer-events: none;
  animation: tipGlow 1.8s ease-in-out infinite;
}

html.dark .prog-glow-tip {
  background: radial-gradient(ellipse at 30% 50%, rgba(154,170,240,.65) 0%, rgba(123,140,222,.28) 45%, transparent 70%);
}

:global(.theme-canva) .prog-glow-tip {
  background: radial-gradient(ellipse at 30% 50%, rgba(0,255,136,.60) 0%, rgba(0,212,255,.25) 45%, transparent 70%);
}

@keyframes tipGlow {
  0%,100% { opacity: .65; transform: scaleX(1); }
  50%     { opacity: 1;   transform: scaleX(1.25); }
}

/* ── 百分比文字（内嵌） ──────────────────────────────────── */
.pct-inner {
  position: relative;
  z-index: 2;
  font-size: 9px;
  font-weight: 700;
  color: rgba(255,255,255,.92);
  text-shadow: 0 1px 3px rgba(0,0,0,.35);
  padding-right: 6px;
  letter-spacing: .3px;
  pointer-events: none;
  white-space: nowrap;
}

/* ── 信息行 ──────────────────────────────────────────────── */
.prog-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.status-txt {
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex: 1;
}

.pct-outer {
  font-size: 11px; font-weight: 600;
  color: var(--accent); flex-shrink: 0; margin-left: 6px;
}
</style>
