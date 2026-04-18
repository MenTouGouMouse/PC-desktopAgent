<template>
  <button
    class="btn btn-ghost reset-btn"
    @click="store.resetToDefault()"
    title="恢复默认布局"
  >
    ⊞ 默认布局
  </button>
</template>

<script setup lang="ts">
import { useLayoutStore } from '../stores/layoutStore'
const store = useLayoutStore()
</script>

<style scoped>
.reset-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 10;
  font-size: 11px;
  padding: 4px 10px;
  opacity: 0.7;
  transition: opacity 0.2s ease;
}

.reset-btn:hover {
  opacity: 1;
}
</style>
