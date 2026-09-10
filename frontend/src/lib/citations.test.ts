import { describe, expect, it } from 'vitest'

import type { Citation } from '../types'

import { citationLabel, leafSection, segmentAnswer } from './citations'

function citation(marker: number, overrides: Partial<Citation> = {}): Citation {
  return {
    marker,
    chunk_id: `chunk-${marker}`,
    document_id: 'doc-1',
    filename: 'Henderson_Commercial_Lease.pdf',
    page: 4,
    section_path: 'ARTICLE 3 - TERMINATION > 3.2 Notice Period',
    bbox: [],
    snippet: 'Either party may terminate this agreement upon ninety (90) days...',
    score: 0.81,
    ...overrides,
  }
}

describe('segmentAnswer', () => {
  it('splits text around a marker and resolves it to its citation', () => {
    const segments = segmentAnswer('The notice period is ninety days [1].', [citation(1)])
    expect(segments).toHaveLength(3)
    expect(segments[0]).toEqual({ kind: 'text', text: 'The notice period is ninety days ' })
    expect(segments[1]).toMatchObject({ kind: 'citation', marker: 1 })
    expect(segments[2]).toEqual({ kind: 'text', text: '.' })
  })

  it('emits one chip per marker in an adjacent run', () => {
    const segments = segmentAnswer('Both agree [1][3].', [citation(1), citation(3)])
    const markers = segments.filter((s) => s.kind === 'citation').map((s) => s.marker)
    expect(markers).toEqual([1, 3])
  })

  it('splits the comma form some models emit', () => {
    const segments = segmentAnswer('See [1, 3] for detail.', [citation(1), citation(3)])
    const markers = segments.filter((s) => s.kind === 'citation').map((s) => s.marker)
    expect(markers).toEqual([1, 3])
  })

  it('renders an unresolvable marker as plain text rather than a dead chip', () => {
    // The model cited a seventh source when six were supplied. A chip the user
    // cannot click is worse than no chip.
    const segments = segmentAnswer('Ninety days [7].', [citation(1)])
    expect(segments.every((segment) => segment.kind === 'text')).toBe(true)
    expect(segments.map((s) => (s.kind === 'text' ? s.text : '')).join('')).toBe('Ninety days [7].')
  })

  it('keeps resolvable markers when a run mixes valid and invalid ones', () => {
    const segments = segmentAnswer('Both [1][9].', [citation(1)])
    const markers = segments.filter((s) => s.kind === 'citation').map((s) => s.marker)
    expect(markers).toEqual([1])
  })

  it('returns a single text segment when there are no markers', () => {
    expect(segmentAnswer('The documents provided don\'t cover this.', [])).toEqual([
      { kind: 'text', text: "The documents provided don't cover this." },
    ])
  })

  it('handles a marker at the very start of the answer', () => {
    const segments = segmentAnswer('[1] states the notice period.', [citation(1)])
    expect(segments[0]).toMatchObject({ kind: 'citation', marker: 1 })
  })
})

describe('leafSection', () => {
  it('takes the deepest heading from a section path', () => {
    expect(leafSection('ARTICLE 3 - TERMINATION > 3.2 Notice Period')).toBe('3.2 Notice Period')
  })

  it('passes a single-level path through', () => {
    expect(leafSection('ARTICLE 3 - TERMINATION')).toBe('ARTICLE 3 - TERMINATION')
  })

  it('returns null when there is no section path', () => {
    expect(leafSection(null)).toBeNull()
  })
})

describe('citationLabel', () => {
  it('reads filename, page, and section', () => {
    expect(citationLabel(citation(1))).toBe(
      'Henderson_Commercial_Lease.pdf, p.4, 3.2 Notice Period',
    )
  })

  it('omits the section when the document had no detectable headings', () => {
    expect(citationLabel(citation(1, { section_path: null }))).toBe(
      'Henderson_Commercial_Lease.pdf, p.4',
    )
  })
})
