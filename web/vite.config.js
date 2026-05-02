import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const ROOT_DIR = path.resolve(__dirname, '..')
const DATA_DIR = path.resolve(__dirname, '..', 'data')
const RAW_DIR = path.resolve(DATA_DIR, 'raw')
const CRAWLER_DIR = path.resolve(ROOT_DIR, 'crawler')
const RANKING_FILE = path.resolve(DATA_DIR, 'ranking.json')
const MIME_TYPES = {
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif'
}

function sendJson(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.setHeader('Cache-Control', 'no-cache')
  res.end(JSON.stringify(body))
}

function runCommand(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd || ROOT_DIR,
      stdio: ['ignore', 'pipe', 'pipe']
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', chunk => {
      stdout += chunk.toString()
    })
    child.stderr.on('data', chunk => {
      stderr += chunk.toString()
    })
    child.on('error', reject)
    child.on('close', code => {
      if (code === 0) {
        resolve({ stdout, stderr })
        return
      }
      const err = new Error(`${command} ${args.join(' ')} failed with ${code}`)
      err.stdout = stdout
      err.stderr = stderr
      reject(err)
    })
  })
}

function parseMonths(value) {
  return String(value || '')
    .split(',')
    .map(month => month.trim())
    .filter(month => /^\d{4}-\d{2}$/.test(month))
    .filter((month, index, arr) => arr.indexOf(month) === index)
}

function delay(ms) {
  return new Promise(resolve => {
    setTimeout(resolve, ms)
  })
}

function compactError(value) {
  const text = String(value || '')
  const lines = text
    .split('\n')
    .filter(line => line.includes('[INFO]') || line.includes('[WARNING]') || line.includes('RuntimeError:') || line.includes('GraphQL'))
  return (lines.join('\n') || text).slice(0, 1200)
}

// FANZA 月度接口仅保留近 5 个月窗口；unavailable 占位文件视为"未完成"，
// 仅在 TTL 内沿用，过期后下次请求会自动重抓，以便窗口前移时及时补到新数据。
const UNAVAILABLE_TTL_HOURS = 24

function readPayload(rawFile) {
  try {
    return JSON.parse(fs.readFileSync(rawFile, 'utf-8'))
  } catch {
    return null
  }
}

function decideFetch(rawFile, force) {
  if (force) return { fetch: true, reason: 'force' }
  if (!fs.existsSync(rawFile)) return { fetch: true, reason: 'missing' }
  const payload = readPayload(rawFile)
  if (!payload) return { fetch: true, reason: 'corrupt' }
  if (!payload.unavailable) return { fetch: false, reason: 'cached' }

  // unavailable / 未完成：基于 fetched_at 判断是否到了重试时机
  const ts = new Date(payload.fetched_at)
  const ageH = Number.isNaN(ts.getTime())
    ? Infinity
    : (Date.now() - ts.getTime()) / 3.6e6
  return ageH >= UNAVAILABLE_TTL_HOURS
    ? { fetch: true, reason: 'retry-unavailable' }
    : { fetch: false, reason: 'unavailable-cooldown', age_hours: Number(ageH.toFixed(1)) }
}

async function ensureRankingMonths(months, { force = false } = {}) {
  const cached = []                // 已缓存有效数据，沿用
  const cooldown = []              // 已知 unavailable，TTL 内不重试
  const crawled = []               // 本次抓到有效数据
  const stillUnavailable = []      // 本次抓完仍 unavailable
  const failed = []                // 子进程异常

  let dirty = false                // 是否需要重跑 aggregator

  for (const month of months) {
    const rawFile = path.join(RAW_DIR, `${month}.json`)
    const decision = decideFetch(rawFile, force)

    if (!decision.fetch) {
      if (decision.reason === 'unavailable-cooldown') {
        cooldown.push({ month, age_hours: decision.age_hours })
      } else {
        cached.push(month)
      }
      continue
    }

    try {
      await runCommand('python3', ['crawl_fanza.py', '--month', month], { cwd: CRAWLER_DIR })
      const after = readPayload(rawFile)
      if (after && after.unavailable) {
        stillUnavailable.push(month)
      } else {
        crawled.push(month)
      }
      dirty = true
    } catch (err) {
      failed.push({
        month,
        error: compactError(err.stderr || err.message)
      })
    }
    await delay(1500)
  }

  if (dirty) {
    await runCommand('python3', ['aggregator.py'], { cwd: CRAWLER_DIR })
  }

  let ranking = null
  if (fs.existsSync(RANKING_FILE)) {
    ranking = JSON.parse(fs.readFileSync(RANKING_FILE, 'utf-8'))
  }

  return {
    ok: failed.length === 0,
    cached,
    cooldown,
    crawled,
    still_unavailable: stillUnavailable,
    failed,
    // 兼容旧字段名
    existing: cached,
    ranking
  }
}

// dev 模式下挂载 /data/ → 项目根的 data 目录，无需污染 public/dist
const serveDataPlugin = {
  name: 'serve-root-data',
  configureServer(server) {
    server.middlewares.use('/api/ensure-ranking', (req, res) => {
      const url = new URL(req.url || '/', 'http://127.0.0.1')
      const months = parseMonths(url.searchParams.get('months'))
      if (!months.length) {
        sendJson(res, 400, { ok: false, error: '缺少有效月份参数' })
        return
      }
      const force = url.searchParams.get('force') === '1'

      ensureRankingMonths(months, { force })
        .then(result => {
          sendJson(res, result.ok ? 200 : 500, result)
        })
        .catch(err => {
          sendJson(res, 500, {
            ok: false,
            error: err.stderr || err.message
          })
        })
    })

    server.middlewares.use('/data', (req, res, next) => {
      const reqPath = decodeURIComponent((req.url || '/').split('?')[0])
      const filePath = path.join(DATA_DIR, reqPath)
      if (!filePath.startsWith(DATA_DIR)) return next()
      fs.stat(filePath, (err, stat) => {
        if (err || !stat.isFile()) return next()
        res.setHeader('Content-Type', MIME_TYPES[path.extname(filePath).toLowerCase()] || 'application/octet-stream')
        res.setHeader('Cache-Control', 'no-cache')
        res.setHeader('Access-Control-Allow-Origin', '*')
        fs.createReadStream(filePath).pipe(res)
      })
    })
  }
}

export default defineConfig({
  plugins: [vue(), serveDataPlugin],
  base: './',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    fs: { allow: ['..'] }
  }
})
