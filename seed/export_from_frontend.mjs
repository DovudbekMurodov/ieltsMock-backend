/**
 * Dump the frontend's ES-module data files to JSON.
 *
 * The backend must not depend on the frontend repo at build time, so the
 * output is committed and this script is only re-run when the source data
 * changes.
 *
 *   node seed/export_from_frontend.mjs --src=../ieltsMock/src/data
 */
import { writeFile, mkdir } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(here, 'data')

const srcArg = process.argv.find((a) => a.startsWith('--src='))
if (!srcArg) {
  console.error('usage: node seed/export_from_frontend.mjs --src=<path to src/data>')
  process.exit(1)
}
const src = resolve(process.cwd(), srcArg.slice('--src='.length))

const exports_ = [
  ['readingTests.js', 'readingTests', 'reading.json'],
  ['listeningTests.js', 'listeningTests', 'listening.json'],
  ['writingTasks.js', 'writingTasks', 'writing.json'],
  ['speakingTopics.js', 'speakingTopics', 'speaking.json'],
  ['vocabulary.js', 'vocabularySections', 'vocabulary.json'],
]

await mkdir(outDir, { recursive: true })

for (const [file, exportName, outFile] of exports_) {
  const mod = await import(pathToFileURL(resolve(src, file)).href)
  const data = mod[exportName]
  if (!Array.isArray(data)) {
    console.error(`${file}: export "${exportName}" is not an array`)
    process.exit(1)
  }
  // JSON.stringify preserves \n\n, curly quotes, currency symbols and ** markers.
  await writeFile(resolve(outDir, outFile), JSON.stringify(data, null, 2) + '\n', 'utf8')
  console.log(`${outFile.padEnd(16)} ${String(data.length).padStart(3)} records`)
}
