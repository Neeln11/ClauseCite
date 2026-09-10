/**
 * Copy pdf.js runtime assets into public/pdfjs so they are served from our own
 * origin.
 *
 * pdf.js fetches these lazily rather than bundling them: font data for the
 * standard-14 fonts a PDF is allowed to reference without embedding, character
 * maps for CJK encodings, and wasm decoders for JPEG2000/JBIG2 images. Left
 * unconfigured it falls back to substituted metrics and logs warnings, and the
 * usual "fix" is to point it at a CDN — which is a third-party request on every
 * document view and breaks entirely offline.
 *
 * Runs from postinstall, and again before dev/build so a wiped public/ heals
 * itself.
 */

import { cp, mkdir, readdir } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const source = join(here, '..', 'node_modules', 'pdfjs-dist')
const target = join(here, '..', 'public', 'pdfjs')

const ASSETS = ['standard_fonts', 'cmaps', 'wasm', 'iccs']

async function main() {
  try {
    await readdir(source)
  } catch {
    console.warn('[pdfjs-assets] pdfjs-dist not installed yet; skipping.')
    return
  }

  await mkdir(target, { recursive: true })

  for (const asset of ASSETS) {
    const from = join(source, asset)
    try {
      await readdir(from)
    } catch {
      continue // Not every pdfjs release ships every directory.
    }
    await cp(from, join(target, asset), { recursive: true })
  }

  console.log(`[pdfjs-assets] copied ${ASSETS.join(', ')} -> public/pdfjs`)
}

await main()
