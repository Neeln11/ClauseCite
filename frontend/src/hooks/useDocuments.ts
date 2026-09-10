/**
 * Document list state, with polling while anything is still ingesting.
 *
 * Upload returns 202 and ingestion runs in the background, so the list has to be
 * refreshed to see a document reach `ready`. Polling only runs while at least one
 * document is pending or processing — an idle tab makes no requests, which keeps
 * the network panel honest and costs nothing when scaled to zero.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, deleteDocument, listDocuments, uploadDocument } from '../api/client'
import type { DocumentSummary } from '../types'

const POLL_INTERVAL_MS = 1500

export interface UploadState {
  filename: string
  progress: number
}

export function useDocuments() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploads, setUploads] = useState<UploadState[]>([])

  // A ref, not state: the polling effect reads it without wanting to re-subscribe
  // every time the list changes.
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const next = await listDocuments()
      if (!mounted.current) return
      setDocuments(next)
      setError(null)
    } catch (caught) {
      if (!mounted.current) return
      setError(caught instanceof ApiError ? caught.detail : 'Could not load documents.')
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    // The lint rule cannot see through the async function: `refresh` awaits the
    // network before it touches state, so nothing is set synchronously here and
    // no cascading render occurs. Fetching the initial list on mount is exactly
    // the "subscribe to an external system" case the rule is meant to allow.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh()
  }, [refresh])

  const ingesting = documents.some(
    (document) => document.status === 'pending' || document.status === 'processing',
  )

  useEffect(() => {
    if (!ingesting) return
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [ingesting, refresh])

  const upload = useCallback(
    async (files: File[]) => {
      setError(null)
      for (const file of files) {
        setUploads((current) => [...current, { filename: file.name, progress: 0 }])
        const track = (progress: number) =>
          setUploads((current) =>
            current.map((entry) =>
              entry.filename === file.name ? { ...entry, progress } : entry,
            ),
          )
        try {
          await uploadDocument(file, track)
        } catch (caught) {
          setError(
            caught instanceof ApiError
              ? `${file.name}: ${caught.detail}`
              : `${file.name}: upload failed.`,
          )
        } finally {
          setUploads((current) => current.filter((entry) => entry.filename !== file.name))
        }
      }
      // One refresh after the batch; polling takes over from here.
      await refresh()
    },
    [refresh],
  )

  const remove = useCallback(
    async (id: string) => {
      // Optimistic: the row disappears immediately, and a failed delete restores
      // it on the next refresh rather than leaving the UI stuck.
      setDocuments((current) => current.filter((document) => document.id !== id))
      try {
        await deleteDocument(id)
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.detail : 'Could not delete the document.')
      }
      await refresh()
    },
    [refresh],
  )

  return {
    documents,
    loading,
    error,
    uploads,
    ingesting,
    refresh,
    upload,
    remove,
    clearError: useCallback(() => setError(null), []),
  }
}
