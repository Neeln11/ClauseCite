import { describe, expect, it } from 'vitest'

import type { BBox } from '../types'

import { citedPages, overlayRects, type ViewportLike } from './highlight'

/**
 * A stand-in for pdf.js's PageViewport at scale 1 on an A4 page.
 *
 * The real transform flips the y axis: PDF space has its origin bottom-left,
 * viewport space top-left. Reproducing that here is the point of the test — a
 * highlight that lands in the wrong half of the page is the classic symptom of
 * getting it wrong, and it is invisible until someone looks.
 */
function viewport(height = 842, width = 595): ViewportLike {
  return {
    width,
    height,
    convertToViewportRectangle: ([x0, y0, x1, y1]: number[]) => [
      x0 as number,
      height - (y1 as number),
      x1 as number,
      height - (y0 as number),
    ],
  }
}

const box = (overrides: Partial<BBox> = {}): BBox => ({
  page: 1,
  x0: 80,
  y0: 700,
  x1: 515,
  y1: 715,
  ...overrides,
})

describe('overlayRects', () => {
  it('flips PDF space into top-left viewport space', () => {
    const [rect] = overlayRects(viewport(), [box()], 1)
    // y1=715 from the bottom on an 842pt page is 127pt from the top.
    expect(rect).toEqual({ left: 80, top: 127, width: 435, height: 15 })
  })

  it('keeps only boxes belonging to the requested page', () => {
    const boxes = [box({ page: 1 }), box({ page: 2 }), box({ page: 2, y0: 600, y1: 615 })]
    expect(overlayRects(viewport(), boxes, 2)).toHaveLength(2)
  })

  it('normalises a rectangle whose corners arrive in the opposite order', () => {
    // A rotated page makes convertToViewportRectangle return y values swapped.
    const swapped: ViewportLike = {
      width: 595,
      height: 842,
      convertToViewportRectangle: () => [400, 300, 100, 120],
    }
    const [rect] = overlayRects(swapped, [box()], 1)
    expect(rect).toEqual({ left: 100, top: 120, width: 300, height: 180 })
  })

  it('clamps a box that extends beyond the page', () => {
    const overflowing: ViewportLike = {
      width: 595,
      height: 842,
      convertToViewportRectangle: () => [-40, -20, 900, 1000],
    }
    const [rect] = overlayRects(overflowing, [box()], 1)
    expect(rect).toEqual({ left: 0, top: 0, width: 595, height: 842 })
  })

  it('drops sub-pixel slivers, which are extraction noise rather than passages', () => {
    const sliver: ViewportLike = {
      width: 595,
      height: 842,
      convertToViewportRectangle: () => [100, 100, 100.4, 100.2],
    }
    expect(overlayRects(sliver, [box()], 1)).toEqual([])
  })

  it('skips a box that transforms to a non-finite rectangle', () => {
    const broken: ViewportLike = {
      width: 595,
      height: 842,
      convertToViewportRectangle: () => [Number.NaN, 0, 10, 10],
    }
    expect(overlayRects(broken, [box()], 1)).toEqual([])
  })

  it('returns nothing when the citation has no boxes at all', () => {
    expect(overlayRects(viewport(), [], 1)).toEqual([])
  })
})

describe('citedPages', () => {
  it('lists the distinct pages a passage spans, in reading order', () => {
    const boxes = [box({ page: 3 }), box({ page: 2 }), box({ page: 3, y0: 10, y1: 20 })]
    expect(citedPages(boxes, 2)).toEqual([2, 3])
  })

  it('falls back to the citation page when extraction produced no boxes', () => {
    expect(citedPages([], 7)).toEqual([7])
  })
})
