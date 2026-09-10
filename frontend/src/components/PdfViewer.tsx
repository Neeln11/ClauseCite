/**
 * The citation viewer: the cited page, with the supporting passage highlighted.
 *
 * Design decisions worth knowing:
 *
 * - **One page at a time**, opened directly at the cited page. A scrolling
 *   multi-page canvas means rendering pages nobody asked for, and "scroll to the
 *   citation" is strictly worse than "already be at the citation".
 * - **Highlights live in an overlay div**, not painted on the canvas, so they
 *   survive re-render, zoom, and page changes without redrawing the page.
 * - **Coordinates are transformed at render time** from stored PDF space via
 *   `viewport.convertToViewportRectangle`. Storing viewport coordinates would
 *   bake in one particular zoom level.
 * - **Degrade, don't disappear**: if extraction produced no boxes for this page,
 *   the page still opens and the snippet is shown in a banner. A viewer that
 *   refuses to open is a worse failure than one that cannot draw a rectangle.
 * - **Lazy**: this component is only mounted once a citation is clicked, so the
 *   ~1 MB of pdf.js and the document bytes are never fetched in sessions that
 *   never open a source.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

import { documentFileUrl } from '../api/client'
import { citationLabel } from '../lib/citations'
import { citedPages, overlayRects, type OverlayRect } from '../lib/highlight'
import type { Citation } from '../types'

pdfjs.GlobalWorkerOptions.workerSrc = workerSrc

// Served from our own origin by scripts/copy-pdfjs-assets.mjs. Defined once at
// module scope: a fresh object each render would make react-pdf refetch the file.
const PDF_OPTIONS = {
  standardFontDataUrl: '/pdfjs/standard_fonts/',
  cMapUrl: '/pdfjs/cmaps/',
  cMapPacked: true,
  wasmUrl: '/pdfjs/wasm/',
  iccUrl: '/pdfjs/iccs/',
} as const

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3] as const
const FIT_ZOOM_INDEX = 2

interface Props {
  citation: Citation
  onClose: () => void
}

export function PdfViewer({ citation, onClose }: Props) {
  const [numPages, setNumPages] = useState<number | null>(null)
  const [pageNumber, setPageNumber] = useState(citation.page)
  const [zoomIndex, setZoomIndex] = useState(FIT_ZOOM_INDEX)
  const [rects, setRects] = useState<OverlayRect[]>([])
  const [pageSize, setPageSize] = useState<{ width: number; height: number } | null>(null)
  const [containerWidth, setContainerWidth] = useState(0)
  const [loadError, setLoadError] = useState<string | null>(null)

  const frameRef = useRef<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const fileUrl = useMemo(() => documentFileUrl(citation.document_id), [citation.document_id])
  const pages = useMemo(() => citedPages(citation.bbox, citation.page), [citation])

  // Note: App keys this component on the citation, so selecting a different
  // passage remounts it. That is deliberate — it is React's own answer to
  // "reset state when a prop changes", and it means page number, zoom, and the
  // highlight's entrance animation all start fresh with no reset effect to
  // maintain. The highlight replays its pulse simply by being newly mounted.

  useLayoutEffect(() => {
    const element = frameRef.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setContainerWidth(entry.contentRect.width)
    })
    observer.observe(element)
    setContainerWidth(element.clientWidth)
    return () => observer.disconnect()
  }, [])

  const zoom = ZOOM_STEPS[zoomIndex] ?? 1
  // Fit-to-width, minus the padding the page sits in.
  const renderWidth = containerWidth > 0 ? Math.max(240, (containerWidth - 32) * zoom) : 0

  const handlePageLoad = useCallback(
    (page: { getViewport: (params: { scale: number }) => unknown }) => {
      const base = page.getViewport({ scale: 1 }) as { width: number }
      if (!base.width || renderWidth <= 0) return
      const scale = renderWidth / base.width
      const viewport = page.getViewport({ scale }) as {
        width: number
        height: number
        convertToViewportRectangle(rect: number[]): number[]
      }
      setPageSize({ width: viewport.width, height: viewport.height })
      setRects(overlayRects(viewport, citation.bbox, pageNumber))
    },
    [citation.bbox, pageNumber, renderWidth],
  )

  const goTo = useCallback(
    (target: number) => {
      if (!numPages) return
      const clamped = Math.min(Math.max(1, target), numPages)
      setPageNumber(clamped)
      setRects([])
      scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    },
    [numPages],
  )

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      else if (event.key === 'ArrowRight' || event.key === 'PageDown') goTo(pageNumber + 1)
      else if (event.key === 'ArrowLeft' || event.key === 'PageUp') goTo(pageNumber - 1)
      else return
      event.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [goTo, onClose, pageNumber])

  const hasHighlightHere = rects.length > 0
  const otherCitedPages = pages.filter((page) => page !== pageNumber)

  return (
    <section className="viewer" aria-label="Document viewer">
      <header className="viewer-head">
        <div className="viewer-title">
          <h2 title={citation.filename}>{citation.filename}</h2>
          <p>{citationLabel(citation)}</p>
        </div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close viewer">
          ✕
        </button>
      </header>

      <div className="viewer-toolbar">
        <div className="pager">
          <button
            type="button"
            className="icon-button"
            onClick={() => goTo(pageNumber - 1)}
            disabled={pageNumber <= 1}
            aria-label="Previous page"
          >
            ‹
          </button>
          <span className="pager-label">
            {pageNumber}
            <span className="pager-total"> / {numPages ?? '…'}</span>
          </span>
          <button
            type="button"
            className="icon-button"
            onClick={() => goTo(pageNumber + 1)}
            disabled={numPages !== null && pageNumber >= numPages}
            aria-label="Next page"
          >
            ›
          </button>
        </div>

        <div className="viewer-toolbar-right">
          {pageNumber !== citation.page && (
            <button type="button" className="text-button" onClick={() => goTo(citation.page)}>
              Back to citation
            </button>
          )}
          <div className="pager">
            <button
              type="button"
              className="icon-button"
              onClick={() => setZoomIndex((index) => Math.max(0, index - 1))}
              disabled={zoomIndex === 0}
              aria-label="Zoom out"
            >
              −
            </button>
            <span className="pager-label">{Math.round(zoom * 100)}%</span>
            <button
              type="button"
              className="icon-button"
              onClick={() => setZoomIndex((index) => Math.min(ZOOM_STEPS.length - 1, index + 1))}
              disabled={zoomIndex === ZOOM_STEPS.length - 1}
              aria-label="Zoom in"
            >
              +
            </button>
          </div>
        </div>
      </div>

      {!hasHighlightHere && !loadError && (
        // Fallback for the case where extraction produced no rectangles for this
        // page: show the passage as text so the citation still resolves.
        <p className="viewer-fallback">
          <strong>Cited passage</strong>
          <span>{citation.snippet}</span>
          {otherCitedPages.length > 0 && (
            <span className="viewer-fallback-hint">
              This passage continues on page {otherCitedPages.join(', ')}.
            </span>
          )}
        </p>
      )}

      <div className="viewer-scroll" ref={scrollRef}>
        <div className="viewer-frame" ref={frameRef}>
          {loadError ? (
            <p className="viewer-error" role="alert">
              {loadError}
            </p>
          ) : (
            renderWidth > 0 && (
              <Document
                file={fileUrl}
                options={PDF_OPTIONS}
                onLoadSuccess={({ numPages: total }) => {
                  setNumPages(total)
                  setLoadError(null)
                }}
                onLoadError={(error: Error) =>
                  setLoadError(
                    `This document could not be opened (${error.message}). It may still be ingesting.`,
                  )
                }
                loading={<div className="viewer-placeholder">Loading document…</div>}
                error={
                  <p className="viewer-error" role="alert">
                    This document could not be opened.
                  </p>
                }
              >
                <div className="page-stack" style={pageSize ? { width: pageSize.width } : undefined}>
                  <Page
                    key={`${pageNumber}-${renderWidth}`}
                    pageNumber={pageNumber}
                    width={renderWidth}
                    onLoadSuccess={handlePageLoad}
                    renderTextLayer
                    renderAnnotationLayer={false}
                    loading={<div className="viewer-placeholder">Rendering page…</div>}
                  />
                  {pageSize && (
                    <div
                      key={`${pageNumber}-${rects.length}`}
                      className="highlight-layer"
                      style={{ width: pageSize.width, height: pageSize.height }}
                      aria-hidden="true"
                    >
                      {rects.map((rect, index) => (
                        <span
                          className="highlight"
                          key={index}
                          style={{
                            left: rect.left,
                            top: rect.top,
                            width: rect.width,
                            height: rect.height,
                            animationDelay: `${Math.min(index * 26, 320)}ms`,
                          }}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </Document>
            )
          )}
        </div>
      </div>
    </section>
  )
}
