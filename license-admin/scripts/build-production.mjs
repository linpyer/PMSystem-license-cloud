import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const expected = Object.freeze({
  NODE_ENV: 'production',
  VITE_API_BASE_URL: 'https://license.aixcc.top/api/v1',
  VITE_APP_ENVIRONMENT: 'production',
  VITE_APP_ENV_LABEL: '生产环境',
  VITE_APP_TITLE: 'PMSystem授权管理',
  VITE_BASE_PATH: '/admin/',
})

for (const [key, value] of Object.entries(expected)) {
  const configured = process.env[key]
  if (configured !== undefined && configured !== value) {
    throw new Error(`Production build refused: ${key} must equal ${JSON.stringify(value)}`)
  }
}

const environment = { ...process.env, ...expected }
const npmCli = process.env.npm_execpath
const command = npmCli ? process.execPath : 'npm'
const arguments_ = npmCli ? [npmCli, 'run', 'build:app'] : ['run', 'build:app']
const result = spawnSync(command, arguments_, {
  cwd: process.cwd(),
  env: environment,
  stdio: 'inherit',
})
if (result.error) throw result.error
if (result.status !== 0) process.exit(result.status ?? 1)

const distRoot = resolve(process.cwd(), 'dist')
const textFiles = []
function collectTextFiles(directory) {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name)
    if (statSync(path).isDirectory()) collectTextFiles(path)
    else if (/\.(?:css|html|js|json|map|txt)$/i.test(name)) textFiles.push(path)
  }
}
collectTextFiles(distRoot)

const output = textFiles.map((path) => readFileSync(path, 'utf8')).join('\n')
const forbidden = [
  ['开发环境', /开发环境/u],
  ['localhost', /localhost/iu],
  ['127.0.0.1', /127\.0\.0\.1/u],
  ['direct production server IP', /47\.98\.206\.68/u],
  ['development or test secret marker', /(?:dev(?:elopment)?[-_ ]?(?:secret|key)|test-password)/iu],
  ['test account marker', /(?:test@example\.com|admin123)/iu],
]
for (const [label, pattern] of forbidden) {
  if (pattern.test(output)) throw new Error(`Production build refused: dist contains ${label}`)
}

for (const required of ['生产环境', 'https://license.aixcc.top/api/v1']) {
  if (!output.includes(required)) {
    throw new Error(`Production build refused: dist is missing ${JSON.stringify(required)}`)
  }
}

console.log(`Production admin guard passed (${textFiles.length} generated text files checked).`)
