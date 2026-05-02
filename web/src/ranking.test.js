import test from 'node:test'
import assert from 'node:assert/strict'
import {
  aggregateEntries,
  availableYears,
  detectParticipantCount,
  detectShotCount,
  enrichJinjierWithMovies,
  entriesFromJinjierActresses,
  entriesFromJinjierMovies,
  entriesFromPayload,
  filterEntriesByRange,
  fanzaSince2026Range,
  formatProductCode,
  isCompilationWork,
  latestCompleteMonth,
  monthRange,
  monthsForPeriod,
  tenYearRange,
  upgradeFanzaCoverUrl,
  worksFromJinjierMovies,
  yearRange
} from './ranking.js'

test('ten year range counts back from the current month', () => {
  assert.deepEqual(tenYearRange(new Date('2026-05-01T00:00:00+08:00')), {
    label: '近十年榜单',
    start: '2016-05',
    end: '2026-05'
  })
})

test('year range covers the full calendar year', () => {
  assert.deepEqual(yearRange(2025), {
    label: '2025 年榜单',
    start: '2025-01',
    end: '2025-12'
  })
})

test('fanza source starts from 2026', () => {
  assert.deepEqual(fanzaSince2026Range(new Date('2026-05-01T00:00:00+08:00')), {
    label: 'FANZA 2026 起榜单',
    start: '2026-01',
    end: '2026-05'
  })
})

test('month range covers one selected month', () => {
  assert.deepEqual(monthRange('2026-4'), {
    label: '2026-04 月榜单',
    start: '2026-04',
    end: '2026-04'
  })
})

test('FANZA poster small URLs upgrade to large variant; non-matching URLs untouched', () => {
  assert.equal(
    upgradeFanzaCoverUrl('https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/sone00846/sone00846ps.jpg'),
    'https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/sone00846/sone00846pl.jpg'
  )
  assert.equal(
    upgradeFanzaCoverUrl('https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/abc/abcps.jpg?token=1'),
    'https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/abc/abcpl.jpg?token=1'
  )
  // 非 awsimgsrc 域名 / 非 ps.jpg 不动
  assert.equal(upgradeFanzaCoverUrl('https://example.test/foo/ps.jpg'), 'https://example.test/foo/ps.jpg')
  assert.equal(upgradeFanzaCoverUrl('https://awsimgsrc.dmm.co.jp/foo/abcpl.jpg'), 'https://awsimgsrc.dmm.co.jp/foo/abcpl.jpg')
  // 空值/非字符串保持原样
  assert.equal(upgradeFanzaCoverUrl(''), '')
  assert.equal(upgradeFanzaCoverUrl(null), null)
})

test('entriesFromPayload upgrades cover_url from ps.jpg to pl.jpg', () => {
  const entries = entriesFromPayload({
    monthly_entries: [
      {
        rank: 1, name: 'Solo work',
        code: 'sone00846', month: '2026-01',
        cover_url: 'https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/sone00846/sone00846ps.jpg'
      }
    ]
  })
  assert.equal(entries.length, 1)
  assert.equal(
    entries[0].cover_url,
    'https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/sone00846/sone00846pl.jpg'
  )
})

test('product codes are formatted for display', () => {
  assert.equal(formatProductCode('snos00038'), 'SNOS-038')
  assert.equal(formatProductCode('snos00131'), 'SNOS-131')
  assert.equal(formatProductCode('1start00257'), 'START-257')
  assert.equal(formatProductCode('h_1711dal00005'), 'DAL-005')
  assert.equal(formatProductCode('13dsvr01947'), 'DSVR-1947')
})

test('required months for latest year stop at latest complete month', () => {
  const now = new Date('2026-05-01T00:00:00+08:00')
  assert.equal(latestCompleteMonth(now), '2026-04')
  assert.deepEqual(monthsForPeriod('year', { year: 2026 }, now), [
    '2026-01',
    '2026-02',
    '2026-03',
    '2026-04'
  ])
})

test('latest incomplete year still produces a ranking from available months', () => {
  const entries = [
    { month: '2026-01', rank: 1, name: 'A', url: '/a', description: 'Actor A' },
    { month: '2026-04', rank: 8, name: 'B', url: '/b', description: 'Actor B' },
    { month: '2025-12', rank: 1, name: 'C', url: '/c', description: 'Actor C' }
  ]

  const currentYearEntries = filterEntriesByRange(entries, yearRange(2026))
  assert.equal(currentYearEntries.length, 2)
  assert.deepEqual(aggregateEntries(currentYearEntries).map(item => item.name), ['Actor A', 'Actor B'])
})

test('available years are derived from month data newest first', () => {
  assert.deepEqual(availableYears(['2024-12', '2026-01', '2025-03', 'bad']), [2026, 2025, 2024])
})

test('entries for the same person are merged and scored together', () => {
  const people = aggregateEntries([
    { month: '2026-04', rank: 2, name: 'Work 1', url: '/w1', description: 'Actor X' },
    { month: '2026-04', rank: 3, name: 'Work 2', url: '/w2', description: 'Actor X' },
    { month: '2026-04', rank: 1, name: 'Work 3', url: '/w3', description: 'Actor Y' }
  ])

  assert.equal(people[0].name, 'Actor X')
  assert.equal(people[0].score, 9)
  assert.equal(people[0].appearances, 2)
  assert.deepEqual(people[0].works.map(work => work.name), ['Work 1', 'Work 2'])
})

test('same work across months is scored once using the best rank', () => {
  const people = aggregateEntries([
    { month: '2025-12', rank: 2, name: 'Same Work', url: '/same', code: 'sone00846', description: 'Actor X' },
    { month: '2026-01', rank: 1, name: 'Same Work', url: '/same', code: 'sone00846', description: 'Actor X' },
    { month: '2026-01', rank: 2, name: 'Other Work', url: '/other', code: 'sone00720', description: 'Actor X' }
  ])

  assert.equal(people[0].name, 'Actor X')
  assert.equal(people[0].score, 11)
  assert.equal(people[0].appearances, 2)
  assert.deepEqual(people[0].works.map(work => work.display_code), ['SONE-846', 'SONE-720'])
  assert.deepEqual(people[0].works[0].months, ['2025-12', '2026-01'])
})

test('participant counts are extracted from titles like "16名" / "8人"', () => {
  assert.equal(detectParticipantCount('AV女優16名の1泊2日大乱交ツアー！'), 16)
  assert.equal(detectParticipantCount('美少女8人と過ごす夢の合宿'), 8)
  assert.equal(detectParticipantCount('シリーズ累計800万部 石川澪'), 0)         // 800万部 ≠ 名/人
})

test('compilation works are detected by keyword or participant count over the threshold', () => {
  // 用户给出的合集示例：含 大集合 / 大乱交 关键词
  assert.equal(isCompilationWork('MOODYZファン感謝祭バコバコバスツアー2026 25周年専属大集合！大乱交！大感謝スペシャル！'), true)
  // 显式标注 16名 → 超过 5 人
  assert.equal(isCompilationWork('AV男優を目指す素人16名とAV女優16名の1泊2日大乱交ツアー！'), true)
  // 单人作品保持
  assert.equal(isCompilationWork('裸天使 石川澪 （ブルーレイディスク）'), false)
  // 显式 4人 → 不到 5 人，保留
  assert.equal(isCompilationWork('女子寮の4人と過ごす休日'), false)
  // 阈值可调
  assert.equal(isCompilationWork('AV女優8名特集', 10), false)
})

test('high shot counts flag compilations while solo BEST/long-runtime works are preserved', () => {
  assert.equal(detectShotCount('おしっこ935連発 大放出'), 935)

  // 用户报告漏过滤的标题：靠 935連発 命中
  assert.equal(isCompilationWork('【超放尿1266分】美少女・美熟女がカメラの前で見せつけるおしっこ935連発 総尿量241，045mlの大放出！'), true)
  // 連発 30 < 50 阈值，保留
  assert.equal(isCompilationWork('中出し30連発スペシャル'), false)

  // 单人 BEST 长篇必须保留（用户规则只针对参与人数 > 5）
  assert.equal(isCompilationWork('ATAD-162 ATTACKERS 女優名鑑 松下紗栄子5 13時間'), false)
  assert.equal(isCompilationWork('PBD-403 山岸逢花 大人気作品を大量収録！大放出！12時間SPECIAL BEST'), false)
  assert.equal(isCompilationWork('MIDE-956 一カ月禁欲明け24時間デカチンFUCK 琴音華'), false)
  assert.equal(isCompilationWork('PED-015 たった7時間2人っきりにしてみたら… 浜崎真緒'), false)
})

test('FANZA payload filters out compilation works during ingest', () => {
  const entries = entriesFromPayload({
    months_included: ['2026-01'],
    monthly_entries: [
      { rank: 1, name: '通常の単独作品 瀬戸環奈', code: 'sone00846', month: '2026-01' },
      { rank: 2, name: 'MOODYZファン感謝祭 大集合！大乱交！大感謝スペシャル', code: 'mird00301', month: '2026-01' },
      { rank: 3, name: 'AV女優16名の特別企画', code: 'mird00302', month: '2026-01' }
    ]
  })
  assert.equal(entries.length, 1)
  assert.equal(entries[0].code, 'sone00846')
})

test('jinjier movies filter compilations the same way', () => {
  const movieEntries = entriesFromJinjierMovies({
    items: [
      { period: 'month', month: '2024-09', rank: 1, name: 'MIDV-872 みおっち', title: 'みおっち', code: 'MIDV-872', cid: 'midv872' },
      { period: 'month', month: '2024-09', rank: 2, name: 'MIRD-237 MOODYZファン感謝祭 大乱交ツアー', title: 'MOODYZファン感謝祭 大乱交ツアー', code: 'MIRD-237', cid: 'mird237' }
    ]
  })
  assert.equal(movieEntries.length, 1)
  assert.equal(movieEntries[0].display_code, 'MIDV-872')
})

test('jinjier movies are deduped per cid into FANZA-style works for an actress', () => {
  const movieEntries = entriesFromJinjierMovies({
    items: [
      { period: 'month', month: '2024-09', rank: 1, name: 'MIDV-872 みおっち 石川澪', title: 'みおっち 石川澪', code: 'MIDV-872', cid: 'midv00872', url: 'https://dmm.test/midv872', cover_url: '/c1.jpg' },
      { period: 'month', month: '2024-10', rank: 5, name: 'MIDV-872 みおっち 石川澪', title: 'みおっち 石川澪', code: 'MIDV-872', cid: 'midv00872', url: 'https://dmm.test/midv872', cover_url: '/c1.jpg' },
      { period: 'month', month: '2024-09', rank: 3, name: 'OAE-258 裸天使 石川澪', title: '裸天使 石川澪', code: 'OAE-258', cid: 'oae00258', url: 'https://dmm.test/oae258', cover_url: '/c2.jpg' },
      { period: 'month', month: '2024-09', rank: 2, name: 'XYZ-001 別の女優', title: '別の女優', code: 'XYZ-001', cid: 'xyz001', url: '', cover_url: '' },
      { period: 'year', month: '', rank: 1, name: 'YEAR-001 石川澪', title: '石川澪 年榜', code: 'YEAR-001', cid: 'year001' }
    ]
  })

  assert.equal(movieEntries.length, 4) // year 行被过滤
  const works = worksFromJinjierMovies('石川澪', movieEntries, { start: '2024-01', end: '2024-12' })
  assert.equal(works.length, 2)
  assert.equal(works[0].display_code, 'MIDV-872')
  assert.equal(works[0].rank, 1)               // 取多月最佳排名
  assert.deepEqual(works[0].months, ['2024-09', '2024-10'])
  assert.equal(works[1].display_code, 'OAE-258')
})

test('jinjier movie matching honors the active range', () => {
  const movieEntries = entriesFromJinjierMovies({
    items: [
      { period: 'month', month: '2021-09', rank: 2, name: 'MIDE-974 石川澪', title: '石川澪', code: 'MIDE-974', cid: 'mide974' },
      { period: 'month', month: '2025-04', rank: 2, name: 'OAE-276 石川澪', title: '石川澪', code: 'OAE-276', cid: 'oae276' }
    ]
  })

  const works = worksFromJinjierMovies('石川澪', movieEntries, { start: '2025-01', end: '2025-12' })
  assert.equal(works.length, 1)
  assert.equal(works[0].display_code, 'OAE-276')
})

test('enrichJinjierWithMovies replaces synthetic works only when matches exist', () => {
  const actresses = [
    { name: '石川澪', works: [{ name: 'placeholder', rank: 1, months: ['2024-09'] }] },
    { name: '無人女優', works: [{ name: 'placeholder', rank: 9, months: ['2024-09'] }] }
  ]
  const movieEntries = entriesFromJinjierMovies({
    items: [
      { period: 'month', month: '2024-09', rank: 1, name: 'MIDV-872 石川澪', title: 'みおっち', code: 'MIDV-872', cid: 'midv872' }
    ]
  })

  const result = enrichJinjierWithMovies(actresses, movieEntries, { start: '2024-01', end: '2024-12' })
  assert.equal(result[0].works.length, 1)
  assert.equal(result[0].works[0].display_code, 'MIDV-872')
  // 没匹配上的女优保持原 works，避免详情页空白
  assert.equal(result[1].works[0].name, 'placeholder')
})

test('jinjier actress rows are mapped into person ranking entries', () => {
  const entries = entriesFromJinjierActresses({
    items: [
      { period: 'month', month: '2025-11', rank: 2, name: 'Actor X', note: '女优榜 - 2025年11月', icon_url: '', cover_url: '/x.jpg' },
      { period: 'month', month: '2025-11', rank: 3, name: 'Actor Z', note: '女优榜 - 2025年11月', cover_url: '/z-small.jpg', fanza_image_url: 'https://example.test/z.jpg', local_cover: '/data/covers/actresses/z.jpg' },
      { period: 'year', month: '', rank: 1, name: 'Actor Y', note: '女优榜 - 2025全年' }
    ]
  })

  assert.equal(entries.length, 2)
  assert.equal(entries[0].description, 'Actor X')
  assert.equal(entries[0].name, '女优榜 - 2025年11月 #2')
  assert.equal(entries[0].code, '2025-11-2')
  assert.equal(entries[1].cover, '/data/covers/actresses/z.jpg')
  assert.equal(entries[1].cover_url, 'https://example.test/z.jpg')
})
