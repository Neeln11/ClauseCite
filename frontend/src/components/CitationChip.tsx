/**
 * An inline `[n]` chip.
 *
 * Hovering (or focusing — this has to work from the keyboard) reveals the source
 * and a snippet, so a reader can sanity-check a claim without leaving the answer.
 * Clicking opens the PDF at the cited page with the passage highlighted, which is
 * the whole point of the product.
 */

import { citationLabel } from '../lib/citations'
import type { Citation } from '../types'

interface Props {
  citation: Citation
  marker: number
  active: boolean
  onSelect: (citation: Citation) => void
}

export function CitationChip({ citation, marker, active, onSelect }: Props) {
  return (
    <span className="chip-wrap">
      <button
        type="button"
        className={`chip${active ? ' chip-active' : ''}`}
        onClick={() => onSelect(citation)}
        aria-label={`Source ${marker}: ${citationLabel(citation)}. Open in the document viewer.`}
      >
        {marker}
      </button>
      <span role="tooltip" className="chip-tooltip">
        <span className="chip-tooltip-source">{citationLabel(citation)}</span>
        <span className="chip-tooltip-snippet">{citation.snippet}</span>
        <span className="chip-tooltip-hint">Click to open the highlighted passage</span>
      </span>
    </span>
  )
}
