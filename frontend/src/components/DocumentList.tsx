/**
 * The document list, which doubles as the retrieval scope control.
 *
 * Selecting nothing means "search everything" rather than "search nothing": the
 * empty selection is the common case, and making the user tick four boxes before
 * their first question would be a tax on the default path. `document_ids: null`
 * is what the API expects for it.
 *
 * Only `ready` documents are selectable. Offering a pending one implies it would
 * be searched, and it would not be.
 */

import type { DocumentSummary } from '../types'

interface Props {
  documents: DocumentSummary[]
  loading: boolean
  selectedIds: string[]
  onToggle: (id: string) => void
  onSelectAll: () => void
  onClearSelection: () => void
  onOpen: (document: DocumentSummary) => void
  onDelete: (id: string) => void
}

const STATUS_LABEL: Record<DocumentSummary['status'], string> = {
  pending: 'Queued',
  processing: 'Indexing',
  ready: 'Ready',
  failed: 'Failed',
}

export function DocumentList({
  documents,
  loading,
  selectedIds,
  onToggle,
  onSelectAll,
  onClearSelection,
  onOpen,
  onDelete,
}: Props) {
  const readyCount = documents.filter((document) => document.status === 'ready').length
  const allSelected = selectedIds.length === 0 || selectedIds.length === readyCount

  if (loading) {
    return <p className="panel-empty">Loading documents…</p>
  }

  if (documents.length === 0) {
    return (
      <p className="panel-empty">
        No documents yet. Upload a contract above, or run <code>python scripts/seed.py</code> to
        load the sample set.
      </p>
    )
  }

  return (
    <div className="doc-list">
      <div className="doc-list-head">
        {/* Deliberately terser than the composer's label, which spells out the
            same scope in a sentence. Two identical sentences on one screen read
            as a bug. */}
        <span className="doc-scope">
          {selectedIds.length === 0
            ? `All ${readyCount} document${readyCount === 1 ? '' : 's'}`
            : `${selectedIds.length} of ${readyCount} selected`}
        </span>
        {selectedIds.length === 0 ? (
          readyCount > 1 && (
            <button type="button" className="text-button" onClick={onSelectAll}>
              Select
            </button>
          )
        ) : (
          <button type="button" className="text-button" onClick={onClearSelection}>
            Clear
          </button>
        )}
      </div>

      <ul>
        {documents.map((document) => {
          const ready = document.status === 'ready'
          const checked = ready && (selectedIds.length === 0 || selectedIds.includes(document.id))
          return (
            <li key={document.id} className={`doc${ready ? '' : ' doc-unready'}`}>
              <label className="doc-check">
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={!ready}
                  onChange={() => onToggle(document.id)}
                  aria-label={`Include ${document.filename} in searches`}
                />
              </label>

              <div className="doc-body">
                <button
                  type="button"
                  className="doc-name"
                  onClick={() => onOpen(document)}
                  disabled={!ready}
                  title={ready ? 'Open in the viewer' : STATUS_LABEL[document.status]}
                >
                  {document.filename}
                </button>
                <p className="doc-meta">
                  <span className={`pill pill-${document.status}`}>
                    {document.status === 'processing' || document.status === 'pending' ? (
                      <span className="spinner" aria-hidden="true" />
                    ) : null}
                    {STATUS_LABEL[document.status]}
                  </span>
                  {document.page_count !== null && <span>{document.page_count} pages</span>}
                  {document.byte_size !== null && <span>{formatBytes(document.byte_size)}</span>}
                </p>
                {document.status === 'failed' && document.error_message && (
                  <p className="doc-error">{document.error_message}</p>
                )}
              </div>

              <button
                type="button"
                className="icon-button doc-delete"
                onClick={() => onDelete(document.id)}
                aria-label={`Delete ${document.filename}`}
                title="Delete"
              >
                ✕
              </button>
            </li>
          )
        })}
      </ul>

      {!allSelected && (
        <p className="doc-list-note">
          Narrowing the scope raises precision when you know which contract holds the answer.
        </p>
      )}
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
