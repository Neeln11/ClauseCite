/**
 * PDF-space bounding boxes to CSS overlay rectangles.
 *
 * Stored boxes are in unrotated PDF user space (origin bottom-left, points).
 * pdf.js's `viewport.convertToViewportRectangle` maps that into viewport space
 * (origin top-left, CSS pixels) and applies the page's scale and rotation on the
 * way, which is exactly why the boxes are stored unrotated: the transform is the
 * viewer's business, not the extractor's.
 *
 * `convertToViewportRectangle` does not guarantee which corner comes first — for
 * a rotated page the y values swap — so the result is normalised rather than
 * assumed to be [left, top, right, bottom].
 */

import type { BBox } from '../types'

export interface ViewportLike {
  width: number
  height: number
  convertToViewportRectangle(rect: number[]): number[]
}

export interface OverlayRect {
  left: number
  top: number
  width: number
  height: number
}

/** Highlight rectangles for one page, in CSS pixels relative to the page's top-left. */
export function overlayRects(
  viewport: ViewportLike,
  boxes: BBox[],
  pageNumber: number,
): OverlayRect[] {
  const rects: OverlayRect[] = []

  for (const box of boxes) {
    if (box.page !== pageNumber) continue

    const [ax, ay, bx, by] = viewport.convertToViewportRectangle([box.x0, box.y0, box.x1, box.y1])
    if (![ax, ay, bx, by].every(Number.isFinite)) continue

    const left = Math.min(ax, bx)
    const top = Math.min(ay, by)
    const right = Math.max(ax, bx)
    const bottom = Math.max(ay, by)

    // Clamp to the page: a box that extends past the crop box would otherwise
    // paint over the viewer's chrome.
    const clampedLeft = Math.max(0, Math.min(left, viewport.width))
    const clampedTop = Math.max(0, Math.min(top, viewport.height))
    const width = Math.min(right, viewport.width) - clampedLeft
    const height = Math.min(bottom, viewport.height) - clampedTop

    // Sub-pixel slivers are extraction noise, not passages.
    if (width < 1 || height < 1) continue

    rects.push({
      left: round(clampedLeft),
      top: round(clampedTop),
      width: round(width),
      height: round(height),
    })
  }

  return rects
}

/** The pages a citation touches, in reading order. */
export function citedPages(boxes: BBox[], fallbackPage: number): number[] {
  const pages = [...new Set(boxes.map((box) => box.page))].sort((a, b) => a - b)
  return pages.length > 0 ? pages : [fallbackPage]
}

function round(value: number): number {
  return Math.round(value * 100) / 100
}
