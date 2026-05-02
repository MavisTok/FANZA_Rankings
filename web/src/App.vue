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

// 持久化用户的视图选项，刷新后保留状态；版本号用于未来字段不兼容时主动作废
const STORAGE_KEY = 'fanza-ranking:ui-state:v1'
const ALLOWED_RANKING_MODE = ['score', 'sales']
const ALLOWED_DATA_SOURCE = ['jinjier', 'fanza']
const ALLOWED_PERIOD = ['decade', 'year', 'month']
const ALLOWED_SORT_KEY = ['rank', 'score', 'appearances']

function loadSavedState() {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function pickFromList(value, allowed, fallback) {
  return allowed.includes(value) ? value : fallback
}

const saved = loadSavedState()

const allEntries = ref([])
const jinjierMovieEntries = ref([])      // 仅 jinjier 模式启用：影片榜规范化条目，用于女优 → 作品反查
const meta = ref({ months: [] })
const loading = ref(true)
const error = ref('')
const syncing = ref(false)
const syncMessage = ref('')

const sortKey = ref(pickFromList(saved.sortKey, ALLOWED_SORT_KEY, 'rank'))
const keyword = ref('')                 // 搜索词不持久化，刷新后清空
const dataSource = ref(pickFromList(saved.dataSource, ALLOWED_DATA_SOURCE, 'fanza'))
const rankingMode = ref(pickFromList(saved.rankingMode, ALLOWED_RANKING_MODE, 'score'))
const period = ref(pickFromList(saved.period, ALLOWED_PERIOD, 'decade'))
const selectedYear = ref(typeof saved.selectedYear === 'string' ? saved.selectedYear : '')
const selectedMonth = ref(
  typeof saved.selectedMonth === 'string' && saved.selectedMonth
    ? saved.selectedMonth
    : latestCompleteMonth()
)
const routeHash = ref(window.location.hash)
let ready = false
let loadVersion = 0
let ensureVersion = 0
let ensureTimer = 0

// 强制重抓：Ctrl+Shift+K 唤起密码弹窗
const RECRAWL_PASSPHRASE = 'fanza2026'
const RECRAWL_COMBO = { ctrl: true, shift: true, key: 'k' }
const showReCrawlModal = ref(false)
const reCrawlInput = ref('')
const reCrawlError = ref('')
const reCrawlBusy = ref(false)
const reCrawlResult = ref('')

function handleKeydown(e) {
  if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === RECRAWL_COMBO.key) {
    e.preventDefault()
    if (showReCrawlModal.value) return
    reCrawlInput.value = ''
    reCrawlError.value = ''
    reCrawlResult.value = ''
    showReCrawlModal.value = true
  }
}

function closeReCrawl() {
  showReCrawlModal.value = false
}

async function submitReCrawl() {
  if (reCrawlInput.value !== RECRAWL_PASSPHRASE) {
    reCrawlError.value = '密码错误'
    reCrawlInput.value = ''
    return
  }
  reCrawlError.value = ''
  reCrawlResult.value = ''
  reCrawlBusy.value = true

  // 只重抓当前视图范围内的月份
  const months = [...selectedPeriodMonths.value]
    .filter(m => m >= '2026-01')
    .sort()

  if (!months.length) {
    reCrawlResult.value = '当前视图没有可重抓的月份。'
    reCrawlBusy.value = false
    return
  }

  reCrawlResult.value = `正在重抓 ${months.join('、')}，请等待…`

  try {
    const res = await fetch(
      `/api/ensure-ranking?months=${encodeURIComponent(months.join(','))}&force=1`,
      { cache: 'no-cache' }
    )
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    if (!data.ok) {
      const failed = data.failed?.map(item => `${item.month}: ${item.error}`).join('；') || '未知错误'
      throw new Error(failed)
    }
    reCrawlResult.value = data.crawled?.length
      ? `已完成：${data.crawled.join('、')}。${data.skipped?.length ? '跳过：' + data.skipped.join('、') : ''}`
      : '重抓完成。'

    // 有变更则刷新前端数据（封面路径已更新）
    if (data.ranking) setPayload(data.ranking)
  } catch (e) {
    reCrawlResult.value = `重抓失败：${e.message}`
  } finally {
    reCrawlBusy.value = false
  }
}

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
  const merged = [...new Set([...recentYears, ...fromData])]
  // FANZA 数据源仅展示 2026 年起的年份，过滤历史数据混入
  const filtered = dataSource.value === 'fanza'
    ? merged.filter(year => year >= 2026)
    : merged
  return filtered.sort((a, b) => b - a)
})

const monthOptions = computed(() => {
  const fromData = meta.value.months || []
  const generated = dataSource.value === 'fanza'
    ? monthsBetween('2026-01', latestCompleteMonth())
    : monthsForPeriod('decade')
  const merged = [...new Set([...generated, ...fromData])].filter(Boolean)
  // FANZA 数据源仅展示 2026-01 起的月份，过滤历史数据混入
  const filtered = dataSource.value === 'fanza'
    ? merged.filter(month => month >= '2026-01')
    : merged
  return filtered.sort((a, b) => b.localeCompare(a))
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

// 销售榜模式：保留原始 entries，按月份分组并按 rank 升序排列
const salesGroups = computed(() => {
  if (rankingMode.value !== 'sales') return []
  const entries = filterEntriesByRange(allEntries.value, activeRange.value)
  const kw = keyword.value.trim().toLowerCase()
  const filteredEntries = kw
    ? entries.filter(x =>
        (x.name || '').toLowerCase().includes(kw) ||
        (x.description || '').toLowerCase().includes(kw)
      )
    : entries

  const byMonth = new Map()
  for (const item of filteredEntries) {
    if (!item.month) continue
    if (!byMonth.has(item.month)) byMonth.set(item.month, [])
    byMonth.get(item.month).push(item)
  }
  return [...byMonth.entries()]
    .map(([month, items]) => ({
      month,
      items: items.slice().sort((a, b) => (Number(a.rank) || 9999) - (Number(b.rank) || 9999))
    }))
    .sort((a, b) => b.month.localeCompare(a.month))
})

const salesTotal = computed(() =>
  salesGroups.value.reduce((sum, group) => sum + group.items.length, 0)
)

const totalCount = computed(() =>
  rankingMode.value === 'sales' ? salesTotal.value : filtered.value.length
)

const detailKey = computed(() => {
  const prefix = '#/detail/'
  if (!routeHash.value.startsWith(prefix)) return ''
  return decodeURIComponent(routeHash.value.slice(prefix.length))
})

const detailItem = computed(() => {
  // 销售榜模式直跳外链，不进入聚合详情页
  if (rankingMode.value === 'sales') return null
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
  if (rankingMode.value === 'sales') {
    return salesGroups.value.map(group => group.month)
  }
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
  window.addEventListener('keydown', handleKeydown)
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
  window.removeEventListener('keydown', handleKeydown)
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

// 视图选项变更时持久化到 localStorage，刷新后恢复
watch(
  [rankingMode, dataSource, period, selectedYear, selectedMonth, sortKey],
  () => {
    if (typeof window === 'undefined') return
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
        rankingMode: rankingMode.value,
        dataSource: dataSource.value,
        period: period.value,
        selectedYear: selectedYear.value,
        selectedMonth: selectedMonth.value,
        sortKey: sortKey.value
      }))
    } catch {
      // localStorage 写入失败（如配额超限/隐私模式）不阻塞主流程
    }
  }
)
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
      <div class="header-main">
        <h1>{{ activeRange.label }}</h1>
        <div v-if="meta.generated_at" class="meta">
          <span>数据源 {{ dataSource === 'jinjier' ? 'Jinjier 历史数据' : 'FANZA 官方抓取' }}</span>
          <span class="meta-sep">·</span>
          <span>共 {{ totalCount }} 条</span>
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
      </div>
      <div class="ranking-mode-switch" role="tablist" aria-label="榜单模式">
        <button
          type="button"
          role="tab"
          :aria-selected="rankingMode === 'score'"
          :class="{ active: rankingMode === 'score' }"
          @click="rankingMode = 'score'"
        >赋分排名</button>
        <button
          type="button"
          role="tab"
          :aria-selected="rankingMode === 'sales'"
          :class="{ active: rankingMode === 'sales' }"
          @click="rankingMode = 'sales'"
        >销售榜</button>
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
        v-model="selectedYear"
        class="select"
        :disabled="period !== 'year' || !years.length"
      >
        <option
          v-for="year in years"
          :key="year"
          :value="String(year)"
        >
          {{ year }} 年
        </option>
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
      <select v-model="sortKey" class="select" :disabled="rankingMode === 'sales'">
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
        <RankingList
          v-if="rankingMode === 'score'"
          :items="filtered"
          :count-label="countLabel"
          :count-unit="countUnit"
        />
        <template v-else>
          <section
            v-for="group in salesGroups"
            :key="group.month"
            class="month-section"
          >
            <h2 class="month-title">
              {{ group.month }} 月
              <span class="month-count">{{ group.items.length }} 部</span>
            </h2>
            <RankingList :items="group.items" mode="sales" />
          </section>
          <p v-if="!salesGroups.length" class="hint">暂无数据</p>
        </template>
      </template>
    </template>

    <!-- 强制重抓弹窗：Ctrl+Shift+K 唤起 -->
    <div v-if="showReCrawlModal" class="modal-backdrop" @click.self="closeReCrawl">
      <div class="modal" role="dialog" aria-label="强制重抓封面">
        <h2 class="modal-title">强制重抓封面</h2>
        <p class="modal-desc">输入密码后将以大图源重抓 {{ dataSource === 'fanza' ? 'FANZA' : 'Jinjier' }} 数据可用月份的全部封面。</p>
        <form @submit.prevent="submitReCrawl" class="modal-form">
          <input
            v-model="reCrawlInput"
            type="password"
            class="modal-input"
            placeholder="输入密码…"
            :disabled="reCrawlBusy"
            autofocus
          />
          <div class="modal-actions">
            <button type="button" class="btn btn-secondary" @click="closeReCrawl" :disabled="reCrawlBusy">取消</button>
            <button type="submit" class="btn btn-primary" :disabled="reCrawlBusy || !reCrawlInput">
              {{ reCrawlBusy ? '进行中…' : '确认' }}
            </button>
          </div>
        </form>
        <p v-if="reCrawlError" class="modal-error">{{ reCrawlError }}</p>
        <p v-if="reCrawlResult" class="modal-result">{{ reCrawlResult }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.header-main { flex: 1; min-width: 0; }
.header h1 { margin: 0 0 8px; font-size: 28px; }

.ranking-mode-switch {
  display: inline-flex;
  background: #f2f2f5;
  border-radius: 9px;
  padding: 3px;
  gap: 2px;
  flex-shrink: 0;
}
.ranking-mode-switch button {
  border: none;
  background: transparent;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 13px;
  color: #1d1d1f;
  cursor: pointer;
  transition: background 0.15s ease, box-shadow 0.15s ease;
}
.ranking-mode-switch button:hover:not(.active) {
  color: #0066cc;
}
.ranking-mode-switch button.active {
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  font-weight: 600;
}

.month-section + .month-section { margin-top: 28px; }
.month-title {
  font-size: 18px;
  font-weight: 650;
  margin: 0 0 12px;
  display: flex;
  align-items: baseline;
  gap: 10px;
  color: #1d1d1f;
}
.month-count {
  color: #6e6e73;
  font-size: 13px;
  font-weight: normal;
}

/* 强制重抓弹窗 */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: #fff;
  border-radius: 14px;
  padding: 28px 32px;
  max-width: 420px;
  width: calc(100% - 32px);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.18);
}
.modal-title {
  margin: 0 0 12px;
  font-size: 20px;
  font-weight: 650;
}
.modal-desc {
  margin: 0 0 18px;
  font-size: 14px;
  color: #6e6e73;
  line-height: 1.6;
}
.modal-form { display: flex; flex-direction: column; gap: 14px; }
.modal-input {
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid #d2d2d7;
  font-size: 15px;
  width: 100%;
  box-sizing: border-box;
}
.modal-input:focus { outline: none; border-color: #0066cc; box-shadow: 0 0 0 3px rgba(0, 102, 204, 0.15); }
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; }
.btn {
  padding: 8px 20px;
  border-radius: 8px;
  border: none;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn:disabled { opacity: 0.45; cursor: default; }
.btn-secondary { background: #f2f2f5; color: #1d1d1f; }
.btn-secondary:hover:not(:disabled) { background: #e5e5ea; }
.btn-primary { background: #0066cc; color: #fff; }
.btn-primary:hover:not(:disabled) { background: #0055aa; }
.modal-error { margin: 12px 0 0; color: #d70015; font-size: 13px; }
.modal-result { margin: 12px 0 0; font-size: 13px; color: #1d1d1f; line-height: 1.5; }
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
