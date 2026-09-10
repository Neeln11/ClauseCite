/**
 * Layout and the small amount of state that spans panels.
 *
 * Three panes: documents, conversation, and the viewer. The viewer only exists
 * once a citation has been clicked, which is both the lazy-loading strategy for
 * pdf.js and the right default — the layout gives the conversation all the room
 * until there is a reason to split it.
 */

import { lazy, Suspense, useCallback, useMemo, useState } from 'react'

import { AIProviderPanel } from './components/AIProviderPanel'
import { ChatPanel } from './components/ChatPanel'
import { DocumentList } from './components/DocumentList'
import { DocumentUpload } from './components/DocumentUpload'
import { useChatStream } from './hooks/useChatStream'
import { useDocuments } from './hooks/useDocuments'
import type { Citation, DocumentSummary } from './types'
import type { ProviderStatus } from './api/client'

// pdf.js is around a megabyte of JavaScript plus its worker. Splitting the viewer
// out keeps it out of the initial load, so a session that never opens a source
// never pays for the ability to — and the app is interactive sooner for everyone.
const PdfViewer = lazy(() =>
  import('./components/PdfViewer').then((module) => ({ default: module.PdfViewer })),
)

export default function App() {
  const documents = useDocuments()
  const chat = useChatStream()

  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null)
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null)

  const readyDocuments = useMemo(
    () => documents.documents.filter((document) => document.status === 'ready'),
    [documents.documents],
  )

  const toggleSelection = useCallback(
    (id: string) => {
      setSelectedIds((current) => {
        // An empty selection means "all", so the first click has to start from
        // the full set and remove one, not start from nothing and add one.
        if (current.length === 0) {
          return readyDocuments.filter((document) => document.id !== id).map((d) => d.id)
        }
        const next = current.includes(id)
          ? current.filter((value) => value !== id)
          : [...current, id]
        // Selecting everything is the same thing as selecting nothing; collapse
        // it so the label reads "all documents" rather than "4 of 4".
        return next.length === readyDocuments.length ? [] : next
      })
    },
    [readyDocuments],
  )

  const scopeLabel = useMemo(() => {
    const count = selectedIds.length === 0 ? readyDocuments.length : selectedIds.length
    if (readyDocuments.length === 0) return 'No documents indexed yet'
    if (selectedIds.length === 0) {
      return `Searching all ${count} document${count === 1 ? '' : 's'}`
    }
    return `Searching ${count} selected document${count === 1 ? '' : 's'}`
  }, [readyDocuments.length, selectedIds.length])

  const openDocument = useCallback((document: DocumentSummary) => {
    // Opening from the list has no cited passage, so it is a citation-shaped
    // object with no boxes: the viewer's own fallback path handles it.
    setActiveCitation({
      marker: 0,
      chunk_id: `document-${document.id}`,
      document_id: document.id,
      filename: document.filename,
      page: 1,
      section_path: null,
      bbox: [],
      snippet: 'Opened from the document list — no passage is highlighted.',
      score: null,
    })
  }, [])

  const removeDocument = useCallback(
    (id: string) => {
      void documents.remove(id)
      setSelectedIds((current) => current.filter((value) => value !== id))
      setActiveCitation((current) => (current?.document_id === id ? null : current))
    },
    [documents],
  )

  return (
    <div className={`app${activeCitation ? ' app-split' : ''}`}>
      <header className="masthead">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <h1>ClauseCite</h1>
            <p>Ask your contracts. Get cited answers.</p>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {providerStatus && (
            <span
              className={`masthead-mode-badge masthead-mode-badge--${providerStatus.mode}`}
              title={providerStatus.message}
            >
              {providerStatus.mode === 'llm' ? '✦ AI' : '⊘ Offline'}
            </span>
          )}
          <p className="masthead-note">
            {providerStatus?.mode === 'llm'
              ? 'Answers combine your documents with AI knowledge.'
              : 'Answers come only from your documents. Every claim is citable.'}
          </p>
        </div>
      </header>

      <aside className="panel" aria-label="Documents">
        <h2 className="panel-title">Documents</h2>
        <DocumentUpload uploads={documents.uploads} onUpload={(files) => void documents.upload(files)} />
        {documents.error && (
          <p className="panel-error" role="alert">
            {documents.error}
            <button type="button" className="text-button" onClick={documents.clearError}>
              Dismiss
            </button>
          </p>
        )}
        <DocumentList
          documents={documents.documents}
          loading={documents.loading}
          selectedIds={selectedIds}
          onToggle={toggleSelection}
          onSelectAll={() => setSelectedIds([])}
          onClearSelection={() => setSelectedIds([])}
          onOpen={openDocument}
          onDelete={removeDocument}
        />
        <AIProviderPanel onStatusChange={setProviderStatus} />
      </aside>

      <main className="main">
        <ChatPanel
          messages={chat.messages}
          streaming={chat.streaming}
          scopeLabel={scopeLabel}
          hasReadyDocuments={readyDocuments.length > 0}
          activeChunkId={activeCitation?.chunk_id ?? null}
          onAsk={(question) => void chat.ask(question, selectedIds)}
          onStop={chat.stop}
          onReset={() => {
            chat.reset()
            setActiveCitation(null)
          }}
          onSelectCitation={setActiveCitation}
        />
      </main>

      {activeCitation && (
        <Suspense
          fallback={
            <section className="viewer" aria-label="Document viewer">
              <div className="viewer-placeholder">Loading viewer…</div>
            </section>
          }
        >
          {/* Keyed on the passage: selecting a different citation remounts the
              viewer, which resets its page and zoom and replays the highlight
              animation without a single reset effect. */}
          <PdfViewer
            key={activeCitation.chunk_id}
            citation={activeCitation}
            onClose={() => setActiveCitation(null)}
          />
        </Suspense>
      )}
    </div>
  )
}
