/**
 * Upload dropzone.
 *
 * Client-side validation on extension and size is a courtesy, not a control: the
 * backend re-checks both, and additionally verifies the PDF magic bytes, because
 * a `.pdf` extension is a claim rather than evidence. Rejecting a 60 MB file here
 * saves the user a pointless upload; it is not what keeps the server safe.
 */

import { useRef, useState } from 'react'

import type { UploadState } from '../hooks/useDocuments'

const MAX_UPLOAD_MB = 25

interface Props {
  uploads: UploadState[]
  onUpload: (files: File[]) => void
  disabled?: boolean
}

export function DocumentUpload({ uploads, onUpload, disabled = false }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragging, setDragging] = useState(false)
  const [rejected, setRejected] = useState<string | null>(null)

  const accept = (fileList: FileList | null) => {
    if (!fileList) return
    const files = Array.from(fileList)
    const problems: string[] = []
    const allowed: File[] = []

    for (const file of files) {
      if (!file.name.toLowerCase().endsWith('.pdf')) {
        problems.push(`${file.name} is not a PDF`)
      } else if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
        problems.push(`${file.name} is over ${MAX_UPLOAD_MB} MB`)
      } else if (file.size === 0) {
        problems.push(`${file.name} is empty`)
      } else {
        allowed.push(file)
      }
    }

    setRejected(problems.length > 0 ? problems.join('. ') : null)
    if (allowed.length > 0) onUpload(allowed)
  }

  return (
    <div className="upload">
      <div
        className={`dropzone${dragging ? ' dropzone-active' : ''}${
          disabled ? ' dropzone-disabled' : ''
        }`}
        onDragOver={(event) => {
          event.preventDefault()
          if (!disabled) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          if (!disabled) accept(event.dataTransfer.files)
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          onChange={(event) => {
            accept(event.target.files)
            // Reset so re-selecting the same file still fires a change event.
            event.target.value = ''
          }}
        />
        <p className="dropzone-title">Drop contracts here</p>
        <p className="dropzone-hint">
          PDF with a text layer, up to {MAX_UPLOAD_MB} MB. Scanned files are rejected — there is no
          OCR in this version.
        </p>
        <button
          type="button"
          className="button button-secondary"
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
        >
          Choose files
        </button>
      </div>

      {rejected && (
        <p className="upload-rejected" role="alert">
          {rejected}
        </p>
      )}

      {uploads.length > 0 && (
        <ul className="upload-progress">
          {uploads.map((upload) => (
            <li key={upload.filename}>
              <span className="upload-name">{upload.filename}</span>
              <span className="progress-track">
                <span
                  className="progress-fill"
                  style={{ width: `${Math.round(upload.progress * 100)}%` }}
                />
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
