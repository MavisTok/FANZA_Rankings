const RANK_TABLE = [
  [1, 1, 6],
  [2, 10, 4],
  [11, 30, 3],
  [31, 50, 2],
  [51, 100, 1]
]

export function rankScore(rank) {
  const value = Number(rank) || 0
  const row = RANK_TABLE.find(([low, high]) => low <= value && value <= high)
  return row ? row[2] : 0
}

export function normalizeMonth(month) {
  if (typeof month !== 'string') return ''
  const match = month.match(/^(\d{4})-(\d{1,2})/)
  if (!match) return ''
  const year = Number(match[1])
  const monthNo = Number(match[2])
  if (!year || monthNo < 1 || monthNo > 12) return ''
  return `${year}-${String(monthNo).padStart(2, '0')}`
}

export function monthToIndex(month) {
  const normalized = normalizeMonth(month)
  if (!normalized) return Number.NaN
  const [year, monthNo] = normalized.split('-').map(Number)
  return year * 12 + monthNo
}

export function indexToMonth(index) {
  const year = Math.floor((index - 1) / 12)
  const monthNo = index - year * 12
  return `${year}-${String(monthNo).padStart(2, '0')}`
}

export function monthsBetween(start, end) {
  const startIndex = monthToIndex(start)
  const endIndex = monthToIndex(end)
  if (!Number.isFinite(startIndex) || !Number.isFinite(endIndex) || startIndex > endIndex) {
    return []
  }
  const months = []
  for (let current = startIndex; current <= endIndex; current += 1) {
    months.push(indexToMonth(current))
  }
  return months
}

export function latestCompleteMonth(now = new Date()) {
  const currentYear = now.getFullYear()
  const currentMonth = now.getMonth() + 1
  const currentIndex = currentYear * 12 + currentMonth
  return indexToMonth(currentIndex - 1)
}

export function tenYearRange(now = new Date()) {
  const endYear = now.getFullYear()
  const endMonth = now.getMonth() + 1
  return {
    label: '近十年榜单',
    start: `${endYear - 10}-${String(endMonth).padStart(2, '0')}`,
    end: `${endYear}-${String(endMonth).padStart(2, '0')}`
  }
}

export function fanzaSince2026Range(now = new Date()) {
  const endYear = now.getFullYear()
  const endMonth = now.getMonth() + 1
  return {
    label: 'FANZA 2026 起榜单',
    start: '2026-01',
    end: `${endYear}-${String(endMonth).padStart(2, '0')}`
  }
}

export function yearRange(year) {
  const value = Number(year)
  return {
    label: `${value} 年榜单`,
    start: `${value}-01`,
    end: `${value}-12`
  }
}

export function monthRange(month) {
  const normalized = normalizeMonth(month)
  return {
    label: `${normalized || month} 月榜单`,
    start: normalized,
    end: normalized
  }
}

export function monthsForPeriod(period, options = {}, now = new Date()) {
  if (period === 'month') {
    const month = normalizeMonth(options.month)
    return month ? [month] : []
  }

  if (period === 'year') {
    const range = yearRange(options.year)
    const latest = latestCompleteMonth(now)
    const end = monthToIndex(range.end) > monthToIndex(latest) ? latest : range.end
    return monthsBetween(range.start, end)
  }

  const range = tenYearRange(now)
  const latest = latestCompleteMonth(now)
  const end = monthToIndex(range.end) > monthToIndex(latest) ? latest : range.end
  return monthsBetween(range.start, end)
}

export function availableYears(months) {
  const years = new Set()
  months.map(normalizeMonth).filter(Boolean).forEach(month => {
    years.add(Number(month.slice(0, 4)))
  })
  return [...years].sort((a, b) => b - a)
}

export function productCodeFromUrl(url) {
  if (typeof url !== 'string') return ''
  try {
    const parsed = new URL(url, 'http://local/')
    const pathMatch = parsed.pathname.match(/cid=([^/]+)/i)
    const queryCode = parsed.searchParams.get('cid')
      || parsed.searchParams.get('product_id')
      || parsed.searchParams.get('content_id')
    return (pathMatch?.[1] || queryCode || '').trim()
  } catch {
    const match = url.match(/cid=([^/&]+)/i)
    return (match?.[1] || '').trim()
  }
}

export function formatProductCode(code) {
  const raw = String(code || '').trim()
  if (!raw) return ''

  const normalized = raw
    .replace(/^h_\d*/i, '')
    .replace(/^\d+/, '')
    .replace(/[_\s-]+/g, '')

  const match = normalized.match(/^([a-z]+)(\d+)([a-z]*)$/i)
  if (!match) return raw.toUpperCase()

  const [, label, numberPart, suffix] = match
  const number = String(Number(numberPart)).padStart(3, '0')
  return `${label.toUpperCase()}-${number}${suffix.toUpperCase()}`
}

// FANZA awsimgsrc 的 ps.jpg 是 ~125×178 缩略图，pl.jpg 是 ~800×538 大图
// 老数据里 cover_url 普遍是 ps，前端展示前升级为 pl 即可立即清晰
const FANZA_COVER_UPGRADE_RE = /(awsimgsrc\.dmm\.co\.jp\/[^?#]*?)ps(\.(?:jpg|jpeg|png|webp))(?=$|[?#])/i

export function upgradeFanzaCoverUrl(url) {
  if (typeof url !== 'string' || !url) return url
  return url.replace(FANZA_COVER_UPGRADE_RE, '$1pl$2')
}

// ============================
// 多人合集过滤规则
// ============================

// 业务规则：
// description 中演员数量 > 5，则认为是多人合集作品，
// 不参与「个人榜」统计。
const COMPILATION_ACTOR_THRESHOLD = 5
const COMPILATION_SHOT_THRESHOLD = 50
const COMPILATION_KEYWORDS = [
  '大集合',
  '大乱交',
  '乱交ツアー',
  'バコバコバス'
]

/**
 * 统计 description 中的演员数量
 *
 * description 通常格式：
 * "演员A / 演员B / 演员C"
 */
export function detectActorCount(description) {
  return String(description || '')
    .split('/')
    .map(name => name.trim())
    .filter(Boolean)
    .length
}

export function detectParticipantCount(text) {
  const counts = [...String(text || '').matchAll(/(\d{1,3})(?:名|人)/g)]
    .map(match => Number(match[1]))
    .filter(Number.isFinite)
  return counts.length ? Math.max(...counts) : 0
}

export function detectShotCount(text) {
  const counts = [...String(text || '').matchAll(/(\d{2,})(?:連発|発)/g)]
    .map(match => Number(match[1]))
    .filter(Number.isFinite)
  return counts.length ? Math.max(...counts) : 0
}

/**
 * 判断是否为多人合集作品
 */
export function isCompilationWork(item, threshold = COMPILATION_ACTOR_THRESHOLD) {
  const text = typeof item === 'string'
    ? item
    : `${item?.name || ''} ${item?.title || ''} ${item?.raw_name || ''} ${item?.description || ''}`
  const actorCount = typeof item === 'string' ? 0 : detectActorCount(item?.description)
  return actorCount > threshold
    || detectParticipantCount(text) > threshold
    || detectShotCount(text) >= COMPILATION_SHOT_THRESHOLD
    || COMPILATION_KEYWORDS.some(keyword => text.includes(keyword))
}

/**
 * 从接口 payload 中提取有效条目
 */
export function entriesFromPayload(data) {
  if (!Array.isArray(data?.monthly_entries)) {
    return []
  }

  return data.monthly_entries
    .map(item => {
      const code = item.code || productCodeFromUrl(item.url)

      return {
        ...item,
        code,
        display_code: item.display_code || formatProductCode(code),
        cover_url: upgradeFanzaCoverUrl(item.cover_url),
        month: normalizeMonth(item.month)
      }
    })
    .filter(item =>
      item.month && !isCompilationWork(item)
    )
}

export function entriesFromJinjierActresses(data) {
  return (data.items || [])
    .filter(item => item.period === 'month')
    .map(item => {
      const month = normalizeMonth(item.month)
      const localCover = item.local_cover || ''
      // 本地下载的封面保留原文件路径；网络回退源做 ps→pl 升级
      const cover = localCover || upgradeFanzaCoverUrl(item.fanza_image_url || item.cover_url || '')
      return {
        name: `${item.note} #${item.rank}`,
        url: '',
        code: `${month}-${item.rank}`,
        display_code: item.note,
        cover,
        cover_url: upgradeFanzaCoverUrl(item.fanza_image_url || item.cover_url || ''),
        description: item.name || '',
        rank: item.rank,
        month,
        source: 'jinjier',
        source_note: item.note,
        source_date: item.date
      }
    })
    .filter(item => item.month && item.description)
}

// jinjier 影片榜数据：每行是某月某作品的榜单条目，按 cid 去重后即可作为某女优的"上榜作品"
export function entriesFromJinjierMovies(data) {
  return (data?.items || [])
    .filter(item => item.period === 'month')
    .map(item => {
      const month = normalizeMonth(item.month)
      if (!month) return null
      const code = item.code || item.cid || productCodeFromUrl(item.url)
      const rawTitle = String(item.title || item.name || '').trim()
      // movie.name 往往以 "MIDE-974 标题" 形式出现，title 是去番号后的纯标题；优先使用 title
      const cleanTitle = rawTitle || item.name || ''
      return {
        raw_name: item.name || '',
        title: cleanTitle,
        code,
        display_code: formatProductCode(code) || code,
        cid: item.cid || '',
        url: item.url || '',
        cover_url: upgradeFanzaCoverUrl(item.cover_url || ''),
        rank: Number(item.rank) || 9999,
        month
      }
    })
    .filter(item => item && !isCompilationWork(`${item.raw_name} ${item.title}`))
}

function pickBestWork(existing, candidate) {
  if (candidate.rank < existing.rank) {
    existing.rank = candidate.rank
    existing.title = candidate.title || existing.title
    existing.url = candidate.url || existing.url
    existing.cover_url = candidate.cover_url || existing.cover_url
    existing.month = candidate.month
  }
}

// 从 jinjier 影片榜中筛出包含 actressName 的所有作品；按 cid 去重并合并月份与最佳排名
export function worksFromJinjierMovies(actressName, movieEntries, range) {
  if (!actressName || !Array.isArray(movieEntries) || !movieEntries.length) return []

  const startIdx = range ? monthToIndex(range.start) : Number.NEGATIVE_INFINITY
  const endIdx = range ? monthToIndex(range.end) : Number.POSITIVE_INFINITY
  const byKey = new Map()

  for (const movie of movieEntries) {
    if (!movie.raw_name?.includes(actressName) && !movie.title?.includes(actressName)) continue
    const idx = monthToIndex(movie.month)
    if (!Number.isFinite(idx) || idx < startIdx || idx > endIdx) continue

    const key = movie.cid || movie.code || movie.url || movie.title
    if (!key) continue

    const existing = byKey.get(key)
    if (!existing) {
      byKey.set(key, {
        name: movie.title,
        url: movie.url,
        code: movie.code,
        display_code: movie.display_code,
        cover: '',
        cover_url: movie.cover_url,
        rank: movie.rank,
        month: movie.month,
        months: [movie.month]
      })
      continue
    }
    if (!existing.months.includes(movie.month)) existing.months.push(movie.month)
    pickBestWork(existing, { rank: movie.rank, title: movie.title, url: movie.url, cover_url: movie.cover_url, month: movie.month })
  }

  return [...byKey.values()]
    .map(work => ({ ...work, months: work.months.slice().sort() }))
    .sort((a, b) => a.rank - b.rank || a.months[0].localeCompare(b.months[0]))
}

// 用 jinjier 影片榜替换聚合后女优的 works 列表，使详情页与 FANZA 模式视觉一致
export function enrichJinjierWithMovies(actresses, movieEntries, range) {
  if (!Array.isArray(actresses) || !actresses.length) return actresses
  if (!Array.isArray(movieEntries) || !movieEntries.length) return actresses

  return actresses.map(actress => {
    const works = worksFromJinjierMovies(actress.name, movieEntries, range)
    return works.length ? { ...actress, works } : actress
  })
}

export function peopleFromEntry(item) {
  const names = String(item.description || '')
    .split(/[、/,，]+/)
    .map(name => name.trim())
    .filter(Boolean)

  return names.length ? names : [item.name || '未标注演员']
}

function workKey(item) {
  return item.code || item.url || item.name || ''
}

function addMonth(target, month) {
  if (month && !target.includes(month)) target.push(month)
}

export function aggregateEntries(entries) {
  const bucket = new Map()

  entries.forEach(item => {
    const people = peopleFromEntry(item)

    people.forEach(personName => {
      const personKey = personName
      if (!personKey) return

      if (!bucket.has(personKey)) {
        bucket.set(personKey, {
          name: personName,
          detail_key: `person:${personName}`,
          url: item.url || '',
          code: personName,
          cover: item.cover || '',
          cover_url: item.cover_url || '',
          description: `${personName} 的上榜作品汇总。`,
          category: item.category || '',
          best_rank: Number(item.rank) || 9999,
          months: [],
          worksMap: new Map()
        })
      }

      const entry = bucket.get(personKey)
      const itemRank = Number(item.rank) || 9999
      if (itemRank < entry.best_rank) {
        entry.url = item.url || entry.url
        entry.cover = item.cover || entry.cover
        entry.cover_url = item.cover_url || entry.cover_url
      }
      if (!entry.cover && item.cover) entry.cover = item.cover
      if (!entry.cover_url && item.cover_url) entry.cover_url = item.cover_url
      if (Number(item.rank)) entry.best_rank = Math.min(entry.best_rank, Number(item.rank))
      addMonth(entry.months, item.month)

      const currentWorkKey = workKey(item)
      if (!currentWorkKey) return
      const existing = entry.worksMap.get(currentWorkKey)
      if (!existing) {
        entry.worksMap.set(currentWorkKey, {
          name: item.name || '',
          url: item.url || '',
          code: item.code || '',
          display_code: item.display_code || formatProductCode(item.code),
          cover: item.cover || '',
          cover_url: item.cover_url || '',
          rank: itemRank,
          month: item.month || '',
          months: item.month ? [item.month] : []
        })
        return
      }

      addMonth(existing.months, item.month)
      if (itemRank < existing.rank) {
        existing.name = item.name || existing.name
        existing.url = item.url || existing.url
        existing.code = item.code || existing.code
        existing.display_code = item.display_code || formatProductCode(item.code) || existing.display_code
        existing.cover = item.cover || existing.cover
        existing.cover_url = item.cover_url || existing.cover_url
        existing.rank = itemRank
        existing.month = item.month || existing.month
      }
    })
  })

  const ranked = [...bucket.values()].map(entry => {
    const works = [...entry.worksMap.values()]
      .map(work => ({
        ...work,
        months: work.months.sort()
      }))
      .sort((a, b) => a.rank - b.rank || a.month.localeCompare(b.month))
    const baseScore = works.reduce((sum, work) => sum + rankScore(work.rank), 0)
    const appearances = works.length

    return {
      ...entry,
      months: entry.months.sort(),
      works,
      appearances,
      score: baseScore + Math.max(0, appearances - 1),
      worksMap: undefined
    }
  })

  ranked.sort((a, b) => b.score - a.score || a.best_rank - b.best_rank)
  ranked.forEach((entry, index) => {
    entry.rank = index + 1
  })
  return ranked
}

export function filterEntriesByRange(entries, range) {
  const start = monthToIndex(range.start)
  const end = monthToIndex(range.end)
  return entries.filter(item => {
    const current = monthToIndex(item.month)
    return Number.isFinite(current) && start <= current && current <= end
  })
}
