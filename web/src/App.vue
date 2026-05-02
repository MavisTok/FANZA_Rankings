<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import RankingList from './components/RankingList.vue'
import {
  aggregateEntries,
  availableYears,
  enrichJinjierWithMovies,
  entriesFromJinjierActresses,
  entriesFromJinjierMovies,
  entriesFromPayload,
  fanzaSince2026Range,
  filterEntriesByRange,
  latestCompleteMonth,
  monthRange,
  monthsBetween,
  monthsForPeriod,
  tenYearRange,
  yearRange
} from './ranking.js'

const allEntries = ref([])
const jinjierMovieEntries = ref([])      // 仅 jinjier 模式启用：影片榜规范化条目，用于女优 → 作品反查
const meta = ref({ months: [] })
const loading = ref(true)
const error = ref('')
const syncing = ref(false)
const syncMessage = ref('')

const sortKey = ref('rank')          // rank | score | appearances
const keyword = ref('')
const dataSource = ref('fanza')      // jinjier | fanza
const period = ref('decade')
const selectedYear = ref('')
const selectedMonth = ref(latestCompleteMonth())
const routeHash = ref(window.location.hash)
let ready = false
let loadVersion = 0
let ensureVersion = 0
let ensureTimer = 0

function updateRouteHash() {
  routeHash.value = window.location.hash
}

const years = computed(() => {
  const fromData = availableYears(meta.value.months || [])
  const latestYear = dataSource.value === 'fanza'
    ? Math.max(2026, Number(latestCompleteMonth().slice(0, 4)))
    : Number(latestCompleteMonth().slice(0, 4))
  const recentYears = dataSource.value === 'fanza'
    ? Array.from({ length: latestYear - 2026 + 1 }, (_, index) => latestYear - index)
    : Array.from({ length: 10 }, (_, index) => latestYear - index)
  return [...new Set([...recentYears, ...fromData])].sort((a, b) => b - a)
})

const monthOptions = computed(() => {
  const fromData = meta.value.months || []
  const generated = dataSource.value === 'fanza'
    ? monthsBetween('2026-01', latestCompleteMonth())
    : monthsForPeriod('decade')
  return [...new Set([...generated, ...fromData])]
    .filter(Boolean)
    .sort((a, b) => b.localeCompare(a))
})

const activeRange = computed(() => {
  if (period.value === 'month' && selectedMonth.value) {
    return monthRange(selectedMonth.value)
  }
  if (period.value === 'year' && selectedYear.value) {
    return yearRange(selectedYear.value)
  }
  if (dataSource.value === 'fanza') {
    return fanzaSince2026Range()
  }
  return tenYearRange()
})

const rankedItems = computed(() => {
  const entries = filterEntriesByRange(allEntries.value, activeRange.value)
  const aggregated = aggregateEntries(entries)
  if (dataSource.value === 'jinjier') {
    return enrichJinjierWithMovies(aggregated, jinjierMovieEntries.value, activeRange.value)
  }
  return aggregated
})

const filtered = computed(() => {
  let arr = [...rankedItems.value]
  if (keyword.value.trim()) {
    const kw = keyword.value.trim().toLowerCase()
    arr = arr.filter(x => (x.name || '').toLowerCase().includes(kw))
  }
  if (sortKey.value === 'score') {
    arr.sort((a, b) => b.score - a.score || a.best_rank - b.best_rank)
  } else if (sortKey.value === 'appearances') {
    arr.sort((a, b) => b.appearances - a.appearances || b.score - a.score)
  } else {
    arr.sort((a, b) => a.rank - b.rank)
  }
  return arr
})

const detailKey = computed(() => {
  const prefix = '#/detail/'
  if (!routeHash.value.startsWith(prefix)) return ''
  return decodeURIComponent(routeHash.value.slice(prefix.length))
})

const detailItem = computed(() => {
  if (!detailKey.value) return null
  return rankedItems.value.find(item => (item.detail_key || item.url || item.name) === detailKey.value) || null
})

const selectedPeriodMonths = computed(() => {
  if (period.value === 'month') {
    return monthsForPeriod('month', { month: selectedMonth.value })
  }
  if (period.value === 'year') {
    return monthsForPeriod('year', { year: selectedYear.value })
  }
  if (dataSource.value === 'fanza') {
    return monthsBetween('2026-01', latestCompleteMonth())
  }
  return monthsForPeriod('decade')
})

const activeMonths = computed(() => {
  const months = rankedItems.value
    .flatMap(item => item.months)
    .filter((month, index, arr) => arr.indexOf(month) === index)
  return months.length ? months : selectedPeriodMonths.value
})

// FANZA 接口仅保留近 5 个月左右的滚动窗口；落在当前查询区间内的不可用月份单独提示
const unavailableInRange = computed(() => {
  if (dataSource.value !== 'fanza') return []
  const list = meta.value.months_unavailable || []
  const { start, end } = activeRange.value
  return list.filter(month => month >= start && month <= end).sort()
})

const detailDescription = computed(() => {
  if (!detailItem.value) return ''
  return detailItem.value.description || '暂无详细简介。'
})

const detailFanzaRank = computed(() => {
  if (!detailItem.value) return ''
  return detailItem.value.best_rank && detailItem.value.best_rank !== 9999
    ? `#${detailItem.value.best_rank}`
    : '未记录'
})

const countLabel = computed(() => dataSource.value === 'jinjier' ? '上榜' : '作品')
const countUnit = computed(() => dataSource.value === 'jinjier' ? '次' : '部')
const detailRecordsTitle = computed(() => dataSource.value === 'jinjier' ? '上榜记录' : '上榜作品')

function setPayload(data) {
  allEntries.value = entriesFromPayload(data)
  meta.value = {
    generated_at: data.generated_at,
    months: data.months_included || allEntries.value.map(item => item.month),
    months_unavailable: data.months_unavailable || [],
    total: data.total,
    entries_total: allEntries.value.length
  }
}

function setJinjierPayload(data) {
  allEntries.value = entriesFromJinjierActresses(data)
  const months = allEntries.value
    .map(item => item.month)
    .filter((month, index, arr) => month && arr.indexOf(month) === index)
    .sort()
  meta.value = {
    generated_at: data.generated_at,
    months,
    months_unavailable: [],
    total: data.total,
    entries_total: allEntries.value.length
  }
}

async function loadRanking() {
  const version = ++loadVersion
  const source = dataSource.value
  if (source === 'jinjier') {
    const [actressRes, moviesRes] = await Promise.all([
      fetch('./data/jinjier/fanza_actresses.json', { cache: 'no-cache' }),
      fetch('./data/jinjier/fanza_movies.json', { cache: 'no-cache' })
    ])
    if (version !== loadVersion || dataSource.value !== source) return
    if (!actressRes.ok) throw new Error(`HTTP ${actressRes.status}`)
    const actressData = await actressRes.json()
    if (version !== loadVersion || dataSource.value !== source) return
    setJinjierPayload(actressData)
    jinjierMovieEntries.value = moviesRes.ok ? entriesFromJinjierMovies(await moviesRes.json()) : []
    return
  }

  jinjierMovieEntries.value = []
  const res = await fetch('./data/ranking.json', { cache: 'no-cache' })
  if (version !== loadVersion || dataSource.value !== source) return
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  setPayload(await res.json())
}

function syncSelectionDefaults() {
  if (!selectedYear.value && years.value.length) {
    selectedYear.value = String(years.value[0])
  }
  if (!monthOptions.value.includes(selectedMonth.value)) {
    selectedMonth.value = monthOptions.value[0] || latestCompleteMonth()
  }
  if (period.value === 'month' && selectedMonth.value) {
    selectedYear.value = selectedMonth.value.slice(0, 4)
  } else if (!years.value.map(String).includes(selectedYear.value)) {
    selectedYear.value = years.value[0] ? String(years.value[0]) : ''
  }
}

function periodMonthsToEnsure(snapshot = {}) {
  const source = snapshot.source ?? dataSource.value
  const currentPeriod = snapshot.period ?? period.value
  const year = snapshot.year ?? selectedYear.value
  const month = snapshot.month ?? selectedMonth.value

  if (source !== 'fanza') return []
  if (currentPeriod === 'month') {
    return monthsForPeriod('month', { month })
  }
  if (currentPeriod === 'year') {
    return monthsForPeriod('year', { year })
  }

  const entriesInRange = filterEntriesByRange(allEntries.value, fanzaSince2026Range())
  return entriesInRange.length ? [] : [latestCompleteMonth()]
}

async function ensureActiveData() {
  if (!ready || dataSource.value !== 'fanza') return
  const version = ++ensureVersion
  const snapshot = {
    source: dataSource.value,
    period: period.value,
    year: selectedYear.value,
    month: selectedMonth.value
  }
  const months = periodMonthsToEnsure(snapshot)
  const knownMonths = new Set([
    ...(meta.value.months || []).map(String),
    ...(meta.value.months_unavailable || []).map(String)
  ])
  const missing = months.filter(month => !knownMonths.has(month))
  if (!missing.length) {
    syncMessage.value = ''
    syncing.value = false
    return
  }

  syncing.value = true
  error.value = ''
  syncMessage.value = `首次抓取 ${missing.join('、')} 数据，请等待，完成后会自动刷新榜单。`
  try {
    const res = await fetch(`/api/ensure-ranking?months=${encodeURIComponent(missing.join(','))}`, {
      cache: 'no-cache'
    })
    if (version !== ensureVersion || dataSource.value !== snapshot.source) return
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    if (version !== ensureVersion || dataSource.value !== snapshot.source) return
    if (!data.ok) {
      const failed = data.failed?.map(item => `${item.month}: ${item.error}`).join('\n') || '未知错误'
      throw new Error(failed)
    }
    if (data.ranking) setPayload(data.ranking)
    syncMessage.value = data.crawled?.length
      ? `已抓取 ${data.crawled.join('、')}，榜单已更新。`
      : ''
  } catch (e) {
    if (version === ensureVersion && dataSource.value === snapshot.source) {
      error.value = `抓取失败：${e.message}`
    }
  } finally {
    if (version === ensureVersion && dataSource.value === snapshot.source) {
      syncing.value = false
    }
  }
}

function scheduleEnsureActiveData() {
  if (ensureTimer) window.clearTimeout(ensureTimer)
  ensureTimer = window.setTimeout(() => {
    ensureTimer = 0
    ensureActiveData()
  }, 120)
}

onMounted(async () => {
  window.addEventListener('hashchange', updateRouteHash)
  try {
    await loadRanking()
    syncSelectionDefaults()
    ready = true
    await ensureActiveData()
  } catch (e) {
    error.value = `数据加载失败：${e.message}`
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  window.removeEventListener('hashchange', updateRouteHash)
  if (ensureTimer) window.clearTimeout(ensureTimer)
})

watch([period, selectedYear, selectedMonth], () => {
  if (period.value === 'month' && selectedMonth.value) {
    selectedYear.value = selectedMonth.value.slice(0, 4)
  }
  scheduleEnsureActiveData()
})

watch(dataSource, async () => {
  if (!ready) return
  loading.value = true
  error.value = ''
  syncMessage.value = ''
  try {
    await loadRanking()
    syncSelectionDefaults()
    await ensureActiveData()
  } catch (e) {
    error.value = `数据加载失败：${e.message}`
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="container">
    <section v-if="detailItem" class="detail">
      <a class="back-link" href="#">返回榜单</a>
      <div class="detail-layout">
        <img
          v-if="detailItem.cover"
          class="detail-cover"
          :src="detailItem.cover"
          :alt="detailItem.name"
          referrerpolicy="no-referrer"
        />
        <div v-else class="detail-cover detail-cover-empty">无封面</div>
        <div class="detail-info">
          <h1>{{ detailItem.name }}</h1>
          <dl class="detail-fields">
            <div>
              <dt>个人名</dt>
              <dd>{{ detailItem.name }}</dd>
            </div>
            <div>
              <dt>编号</dt>
              <dd>{{ detailItem.display_code || detailItem.code || '未设置' }}</dd>
            </div>
            <div>
              <dt>FANZA 排行</dt>
              <dd>{{ detailFanzaRank }}</dd>
            </div>
          </dl>
          <p class="detail-desc">{{ detailDescription }}</p>
          <div class="detail-stats">
            <span class="tag tag-score">得分 {{ detailItem.score }}</span>
            <span class="tag">{{ countLabel }} {{ detailItem.appearances }} {{ countUnit }}</span>
            <span class="tag">最高 #{{ detailItem.best_rank }}</span>
            <span class="tag">{{ detailItem.months.join('、') }}</span>
          </div>
          <div v-if="detailItem.works?.length" class="works">
            <h2>{{ detailRecordsTitle }}</h2>
            <ol>
              <li v-for="work in detailItem.works" :key="work.code || work.url || work.name">
                <span class="work-rank">#{{ work.rank }}</span>
                <a
                  v-if="work.url"
                  :href="work.url"
                  target="_blank"
                  rel="noreferrer"
                >
                  {{ work.name }}
                </a>
                <span v-else>{{ work.name }}</span>
                <span class="work-meta">
                  {{ work.months?.join('、') || work.month }} · {{ work.display_code || work.code || '未设置编号' }}
                </span>
              </li>
            </ol>
          </div>
        </div>
      </div>
    </section>

    <template v-else>
      <header class="header">
      <h1>{{ activeRange.label }}</h1>
      <div v-if="meta.generated_at" class="meta">
        <span>数据源 {{ dataSource === 'jinjier' ? 'Jinjier 历史数据' : 'FANZA 官方抓取' }}</span>
        <span class="meta-sep">·</span>
        <span>共 {{ filtered.length }} 条</span>
        <details class="meta-details">
          <summary>更多详情</summary>
          <div class="meta-details-body">
            <span>更新于 {{ meta.generated_at }}</span>
            <span class="meta-sep">·</span>
            <span>统计区间 {{ activeRange.start }} 至 {{ activeRange.end }}</span>
            <span class="meta-sep">·</span>
            <span>纳入月份 {{ activeMonths.join('、') || '—' }}</span>
          </div>
        </details>
      </div>
      </header>

      <div class="toolbar">
      <select v-model="dataSource" class="select">
        <option value="jinjier">Jinjier 历史数据</option>
        <option value="fanza">FANZA 数据源</option>
      </select>
      <select v-model="period" class="select">
        <option value="decade">{{ dataSource === 'fanza' ? '2026 起榜单' : '近十年榜单' }}</option>
        <option value="year">年度榜单</option>
        <option value="month">月度榜单</option>
      </select>
      <select
        v-model="selectedMonth"
        class="select"
        :disabled="period !== 'month' || !monthOptions.length"
      >
        <option
          v-for="month in monthOptions"
          :key="month"
          :value="month"
        >
          {{ month }} 月
        </option>
      </select>
      <input
        v-model="keyword"
        type="search"
        placeholder="按名称搜索…"
        class="search"
      />
      <select v-model="sortKey" class="select">
        <option value="rank">综合排名</option>
        <option value="score">总分</option>
        <option value="appearances">上榜次数</option>
      </select>
      </div>

      <p v-if="loading" class="hint">加载中…</p>
      <p v-else-if="error" class="error">{{ error }}</p>
      <template v-else>
        <p v-if="syncing || syncMessage" class="hint">{{ syncMessage }}</p>
        <p v-if="unavailableInRange.length" class="notice">
          FANZA 月度排行接口仅保留近期约 5 个月数据，以下月份官方未提供，已自动跳过：{{ unavailableInRange.join('、') }}
        </p>
        <RankingList :items="filtered" :count-label="countLabel" :count-unit="countUnit" />
      </template>
    </template>
  </div>
</template>

<style scoped>
.header h1 { margin: 0 0 8px; font-size: 28px; }
.meta {
  color: #6e6e73;
  margin: 0 0 24px;
  font-size: 14px;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
}
.meta-sep { color: #c7c7cc; }
.meta-details { display: inline; }
.meta-details summary {
  display: inline;
  cursor: pointer;
  color: #0066cc;
  list-style: none;
  user-select: none;
}
.meta-details summary::-webkit-details-marker { display: none; }
.meta-details summary::before { content: '▸ '; font-size: 11px; }
.meta-details[open] summary::before { content: '▾ '; }
.meta-details summary:hover { text-decoration: underline; }
.meta-details-body {
  margin-top: 6px;
  padding: 10px 12px;
  background: #f5f5f7;
  border-radius: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex-basis: 100%;
  line-height: 1.7;
}

.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.search, .select {
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid #d2d2d7;
  background: #fff;
  font-size: 14px;
}
.search { flex: 1; min-width: 220px; }
.select { min-width: 140px; }
.select:disabled {
  color: #86868b;
  background: #f5f5f7;
}

.hint { color: #6e6e73; }
.error { color: #d70015; }
.notice {
  background: #fff8e6;
  border: 1px solid #f3d97a;
  border-radius: 8px;
  padding: 10px 14px;
  margin: 0 0 16px;
  font-size: 13px;
  color: #8a5a00;
  line-height: 1.5;
}
.detail { padding-top: 8px; }
.back-link {
  display: inline-block;
  margin-bottom: 20px;
  color: #1d1d1f;
  text-decoration: none;
  font-size: 14px;
}
.back-link:hover { text-decoration: underline; }
.detail-layout {
  display: grid;
  grid-template-columns: minmax(220px, 340px) minmax(0, 1fr);
  gap: 28px;
  align-items: start;
  max-width: 980px;
}
.detail-cover {
  width: 100%;
  max-width: 340px;
  aspect-ratio: 3 / 4;
  border-radius: 8px;
  object-fit: cover;
  background: #eee;
}
.detail-cover-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #86868b;
}
.detail-info h1 {
  margin: 0 0 18px;
  font-size: 32px;
  line-height: 1.25;
}
.detail-fields {
  display: grid;
  gap: 10px;
  margin: 0 0 18px;
}
.detail-fields div {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 12px;
  align-items: baseline;
  padding-bottom: 10px;
  border-bottom: 1px solid #e5e5ea;
}
.detail-fields dt {
  color: #6e6e73;
  font-size: 14px;
}
.detail-fields dd {
  margin: 0;
  color: #1d1d1f;
  font-weight: 650;
  overflow-wrap: anywhere;
}
.detail-desc {
  max-width: 720px;
  margin: 0 0 18px;
  color: #424245;
  line-height: 1.7;
}
.detail-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}
.tag {
  font-size: 12px;
  color: #6e6e73;
  background: #f2f2f5;
  padding: 4px 10px;
  border-radius: 6px;
}
.tag-score { background: #fff1d6; color: #8a5a00; font-weight: 600; }
.source-link {
  color: #0066cc;
  text-decoration: none;
}
.source-link:hover { text-decoration: underline; }
.works {
  margin-top: 22px;
}
.works h2 {
  margin: 0 0 10px;
  font-size: 18px;
}
.works ol {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 10px;
}
.works li {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 8px 12px;
  padding: 10px 0;
  border-bottom: 1px solid #e5e5ea;
}
.work-rank {
  color: #6e6e73;
  font-weight: 700;
}
.works a {
  color: #1d1d1f;
  text-decoration: none;
}
.works a:hover { text-decoration: underline; }
.work-meta {
  grid-column: 2;
  color: #6e6e73;
  font-size: 12px;
}

@media (max-width: 720px) {
  .detail-layout { grid-template-columns: 1fr; }
  .detail-cover { justify-self: center; max-width: 320px; }
  .detail-info h1 { font-size: 26px; }
  .detail-fields div { grid-template-columns: 76px minmax(0, 1fr); }
}
</style>
