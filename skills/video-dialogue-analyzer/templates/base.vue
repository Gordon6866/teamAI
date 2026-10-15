<template>
  <div class="base-template">
    <slot />
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' }
});
</script>
