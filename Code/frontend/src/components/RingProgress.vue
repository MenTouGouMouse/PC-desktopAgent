<template>
  <svg viewBox="0 0 80 80" width="80" height="80" xmlns="http://www.w3.org/2000/svg">
    <!-- Background track -->
    <circle
      cx="40"
      cy="40"
      r="32"
      fill="none"
      stroke="rgba(0,212,255,0.15)"
      stroke-width="4"
    />
    <!-- Progress arc -->
    <circle
      cx="40"
      cy="40"
      r="32"
      fill="none"
      stroke="var(--accent-cyan)"
      stroke-width="4"
      stroke-linecap="round"
      :stroke-dasharray="DASHARRAY"
      :stroke-dashoffset="dashOffset"
      transform="rotate(-90 40 40)"
      class="progress-arc"
    />
    <!-- Center text -->
    <text
      x="40"
      y="46"
      text-anchor="middle"
      fill="white"
      font-size="18"
      font-weight="bold"
      font-family="Arial, Helvetica, sans-serif"
    >{{ percent }}%</text>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  percent: number
}>()

const DASHARRAY = 2 * Math.PI * 32 // ≈ 201.06

const dashOffset = computed(() => DASHARRAY * (1 - props.percent / 100))
</script>

<style scoped>
.progress-arc {
  transition: stroke-dashoffset 0.4s ease;
}
</style>
