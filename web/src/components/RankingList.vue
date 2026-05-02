<script setup>
defineProps({
  items: { type: Array, required: true },
  countLabel: { type: String, default: '作品' },
  countUnit: { type: String, default: '部' }
})

function detailHref(item) {
  return `#/detail/${encodeURIComponent(item.detail_key || item.url || item.name)}`
}
</script>

<template>
  <ul class="grid" v-if="items.length">
    <li
      v-for="item in items"
      :key="item.detail_key || item.code || item.url || item.name"
      class="card"
    >
      <div class="rank-badge">#{{ item.rank }}</div>
      <a class="cover-wrap" :href="detailHref(item)" :aria-label="`${item.name} 详情`">
        <img
          v-if="item.cover"
          :src="item.cover"
          :alt="item.name"
          loading="lazy"
          referrerpolicy="no-referrer"
        />
        <div v-else class="cover-placeholder">无封面</div>
      </a>
      <div class="info">
        <h3 class="name" :title="item.name">
          <a :href="detailHref(item)">{{ item.name }}</a>
        </h3>
        <div class="stats">
          <span class="tag tag-score">得分 {{ item.score }}</span>
          <span class="tag">{{ countLabel }} {{ item.appearances }} {{ countUnit }}</span>
          <span class="tag">最高 #{{ item.best_rank }}</span>
        </div>
      </div>
    </li>
  </ul>
  <p v-else class="empty">暂无数据</p>
</template>

<style scoped>
.grid {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

.card {
  position: relative;
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.1);
}

.rank-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  background: rgba(0, 0, 0, 0.72);
  color: #fff;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  z-index: 1;
}

.cover-wrap {
  display: block;
  aspect-ratio: 3 / 4;
  background: #eee;
  color: inherit;
  text-decoration: none;
}
.cover-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cover-placeholder {
  width: 100%; height: 100%;
  display: flex; align-items: center; justify-content: center;
  color: #999; font-size: 14px;
}

.info { padding: 12px; }
.name {
  margin: 0 0 8px;
  font-size: 14px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.name a {
  color: inherit;
  text-decoration: none;
}
.name a:hover { text-decoration: underline; }

.stats { display: flex; flex-wrap: wrap; gap: 6px; }
.tag {
  font-size: 12px;
  color: #6e6e73;
  background: #f2f2f5;
  padding: 2px 8px;
  border-radius: 6px;
}
.tag-score { background: #fff1d6; color: #8a5a00; font-weight: 600; }

.empty { color: #6e6e73; }
</style>
