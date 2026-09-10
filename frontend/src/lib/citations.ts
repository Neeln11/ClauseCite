/**
 * Turning an answer string into renderable segments.
 *
 * The model emits `[1]` markers inline. The backend already drops markers it
 * could not resolve, but the frontend repeats the check rather than trusting it:
 * a chip the user cannot click breaks the only promise this product makes, so an
 * unresolvable marker is rendered as ordinary text instead.
 */

import type { Citation } from '../types'

export type AnswerSegment =
  | { kind: 'text'; text: string }
  | { kind: 'citation'; marker: number; citation: Citation }

// [1] and the comma form some models emit despite instructions: [1, 3]
const MARKER_RE = /\[(\d+(?:\s*,\s*\d+)*)\]/g

export function segmentAnswer(text: string, citations: Citation[]): AnswerSegment[] {
  const byMarker = new Map(citations.map((citation) => [citation.marker, citation]))
  const segments: AnswerSegment[] = []
  let cursor = 0

  const pushText = (value: string) => {
    if (!value) return
    const previous = segments[segments.length - 1]
    if (previous?.kind === 'text') previous.text += value
    else segments.push({ kind: 'text', text: value })
  }

  for (const match of text.matchAll(MARKER_RE)) {
    const index = match.index ?? 0
    pushText(text.slice(cursor, index))
    cursor = index + match[0].length

    const markers = match[1].split(',').map((part) => Number(part.trim()))
    const resolved = markers.filter((marker) => byMarker.has(marker))

    if (resolved.length === 0) {
      // Nothing to link to. Keep the original text so the answer still reads.
      pushText(match[0])
      continue
    }
    for (const marker of resolved) {
      segments.push({ kind: 'citation', marker, citation: byMarker.get(marker)! })
    }
  }

  pushText(text.slice(cursor))
  return segments
}

/** "ARTICLE 3 - TERMINATION > 3.2 Notice Period" -> "3.2 Notice Period" */
export function leafSection(sectionPath: string | null): string | null {
  if (!sectionPath) return null
  const parts = sectionPath.split('>')
  return parts[parts.length - 1]?.trim() || null
}

export function citationLabel(citation: Citation): string {
  const section = leafSection(citation.section_path)
  const where = `p.${citation.page}`
  return section ? `${citation.filename}, ${where}, ${section}` : `${citation.filename}, ${where}`
}
