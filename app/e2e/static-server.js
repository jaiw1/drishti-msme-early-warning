// A plain static server for the e2e suite, standing in for nginx.
//
// `vite preview` cannot serve this build to a browser: Vite 5.4.21 answers **404** to any
// request carrying `Sec-Fetch-Dest: script`, which is exactly what a browser sends for the
// bundle's own module script. The document loads, the script 404s, React never mounts, and
// every spec fails with "#login-username not found". Reproduce it with:
//
//   curl -o /dev/null -w '%{http_code}' -H 'Sec-Fetch-Dest: script' <asset-url>   # 404
//   curl -o /dev/null -w '%{http_code}'                             <asset-url>   # 200
//
// That is a preview-server behaviour, not an app fault — the deployed bundle sits behind
// nginx. So the suite runs against this instead: static files, SPA fallback per sub-path,
// and /api proxied to uvicorn so cookies stay same-origin and CSRF works.

import http from 'node:http'
import { createReadStream, existsSync, statSync } from 'node:fs'
import { extname, join, normalize, resolve } from 'node:path'

const ROOT = resolve(process.argv[2] || 'dist')
const BASE = process.env.E2E_BASE || '/drishti'
const PORT = Number(process.env.E2E_PORT || 4173)
const API = process.env.E2E_API || 'http://127.0.0.1:8001'

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon',
  '.woff2': 'font/woff2', '.txt': 'text/plain; charset=utf-8',
}

const send = (res, code, body, type = 'text/plain') =>
  res.writeHead(code, { 'content-type': type, 'cache-control': 'no-store' }).end(body)

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`)

  if (url.pathname.startsWith('/api')) {
    const proxied = http.request(
      API + req.url,
      { method: req.method, headers: { ...req.headers, host: new URL(API).host } },
      (upstream) => {
        res.writeHead(upstream.statusCode, upstream.headers)
        upstream.pipe(res)
      },
    )
    proxied.on('error', (e) => send(res, 502, `upstream: ${e.message}`))
    req.pipe(proxied)
    return
  }

  // Everything below BASE is the app; strip the prefix and resolve inside dist/.
  const rel = url.pathname.startsWith(BASE) ? url.pathname.slice(BASE.length) : url.pathname
  const safe = normalize(rel).replace(/^(\.\.[/\\])+/, '')
  let file = join(ROOT, safe)

  if (existsSync(file) && statSync(file).isFile()) {
    res.writeHead(200, {
      'content-type': TYPES[extname(file)] || 'application/octet-stream',
      'cache-control': 'no-store',
    })
    createReadStream(file).pipe(res)
    return
  }
  // SPA fallback: any unknown path under the base is a client route.
  file = join(ROOT, 'index.html')
  if (!existsSync(file)) return send(res, 404, 'no build in ' + ROOT)
  res.writeHead(200, { 'content-type': TYPES['.html'], 'cache-control': 'no-store' })
  return createReadStream(file).pipe(res)
})

server.listen(PORT, () => {
  process.stdout.write(`static server: http://127.0.0.1:${PORT}${BASE}/ (root ${ROOT}, /api -> ${API})\n`)
})
