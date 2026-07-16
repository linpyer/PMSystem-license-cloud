<script setup lang="ts">defineProps<{ title: string; description?: string }>()</script>
<template>
  <header class="page-head"><div><h1>{{ title }}</h1><p v-if="description">{{ description }}</p></div><div><slot /></div></header>
</template>
