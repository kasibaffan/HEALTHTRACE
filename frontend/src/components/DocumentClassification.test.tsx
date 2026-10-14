import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { DocumentClassification } from './DocumentClassification'
import { api } from '../services/api'
import type { DocumentClassification as Classification, DocumentFile } from '../types'

vi.mock('../services/api', () => ({ api: { reviewClassification: vi.fn(), retryClassification: vi.fn(), structuredFields: vi.fn() } }))

const review = vi.mocked(api.reviewClassification)
const retry = vi.mocked(api.retryClassification)

const base: Classification = {
  status: 'CLASSIFIED', label: 'CLAIM_BILLING', score: 0.83, lowConfidence: false, modelVersion: 'v-test', classifiedAt: null,
  reviewedLabel: null, reviewedBy: null, reviewedAt: null, effectiveLabel: 'CLAIM_BILLING',
}
const doc = (c: Partial<Classification> = {}, status: DocumentFile['status'] = 'PROCESSED'): DocumentFile =>
  ({ id: 'd1', name: 'Statement.txt', type: 'Supporting', pages: 1, content: [], uploaded: true, size: 10, status, classification: { ...base, ...c } })

beforeEach(() => { review.mockReset(); retry.mockReset(); vi.mocked(api.structuredFields).mockReset() })
afterEach(cleanup)

describe('DocumentClassification', () => {
  it('renders nothing while the document is still processing or has no classification payload', () => {
    const { container, rerender } = render(<DocumentClassification doc={doc({}, 'PROCESSING')} onChanged={() => {}} />)
    expect(container.firstChild).toBeNull()
    rerender(<DocumentClassification doc={{ ...doc(), classification: undefined }} onChanged={() => {}} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows the suggestion as unverified and never renders the score as a percentage', () => {
    const { container } = render(<DocumentClassification doc={doc()} onChanged={() => {}} />)
    expect(screen.getByText('Claim or billing document')).toBeTruthy()
    expect(screen.getByText('Not verified')).toBeTruthy()
    expect(container.textContent).not.toMatch(/%|83/)
    expect(screen.queryByText(/low model score/i)).toBeNull()
  })

  it('flags low-scoring suggestions', () => {
    render(<DocumentClassification doc={doc({ lowConfidence: true })} onChanged={() => {}} />)
    expect(screen.getByText(/low model score/i)).toBeTruthy()
  })

  it('shows the human-reviewed type and who set it', () => {
    render(<DocumentClassification doc={doc({ reviewedLabel: 'REFERRAL_ORDER', reviewedBy: { id: 'u1', fullName: 'Rita Reviewer' } })} onChanged={() => {}} />)
    expect(screen.getByText(/Referral or order/)).toBeTruthy()
    expect(screen.getByText(/Rita Reviewer/)).toBeTruthy()
    expect(screen.getByText('Change reviewed type')).toBeTruthy()
  })

  it('lets a reviewer correct the type and reports the change', async () => {
    review.mockResolvedValue(base)
    const onChanged = vi.fn()
    render(<DocumentClassification doc={doc()} onChanged={onChanged} />)
    fireEvent.click(screen.getByRole('button', { name: /review document type for Statement.txt/i }))
    fireEvent.change(screen.getByLabelText('Document type'), { target: { value: 'IMAGING_REPORT' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1))
    expect(review).toHaveBeenCalledWith('d1', 'IMAGING_REPORT')
    expect(screen.queryByLabelText('Document type')).toBeNull()
  })

  it('keeps the form open and shows the server error when saving fails (e.g. no permission)', async () => {
    review.mockRejectedValue(new Error('You do not have permission to do that.'))
    const onChanged = vi.fn()
    render(<DocumentClassification doc={doc()} onChanged={onChanged} />)
    fireEvent.click(screen.getByRole('button', { name: /review document type/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect((await screen.findByRole('alert')).textContent).toContain('permission')
    expect(screen.getByLabelText('Document type')).toBeTruthy()
    expect(onChanged).not.toHaveBeenCalled()
  })

  it('clears a reviewer correction', async () => {
    review.mockResolvedValue(base)
    const onChanged = vi.fn()
    render(<DocumentClassification doc={doc({ reviewedLabel: 'OTHER' })} onChanged={onChanged} />)
    fireEvent.click(screen.getByRole('button', { name: 'Clear reviewer type' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(review).toHaveBeenCalledWith('d1', null)
  })

  it('shows an unavailable state with a retry that succeeds', async () => {
    retry.mockResolvedValue(base)
    const onChanged = vi.fn()
    render(<DocumentClassification doc={doc({ status: 'UNAVAILABLE', label: null, effectiveLabel: null })} onChanged={onChanged} />)
    expect(screen.getByRole('status').textContent).toMatch(/unavailable/i)
    expect(screen.getByRole('status').textContent).toMatch(/still processed/i)
    fireEvent.click(screen.getByRole('button', { name: 'Retry suggestion' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(retry).toHaveBeenCalledWith('d1')
  })

  it('surfaces a failed retry', async () => {
    retry.mockRejectedValue(new Error('Cannot reach the HealthTrace API.'))
    render(<DocumentClassification doc={doc({ status: 'ERROR', label: null })} onChanged={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Retry suggestion' }))
    expect((await screen.findByRole('alert')).textContent).toContain('Cannot reach')
    expect(screen.getByRole('button', { name: 'Retry suggestion' })).toBeTruthy()
  })

  it('explains documents without readable text and does not guess a type', () => {
    render(<DocumentClassification doc={doc({ status: 'NO_TEXT', label: null })} onChanged={() => {}} />)
    expect(screen.getByText(/No readable text/)).toBeTruthy()
    expect(screen.queryByText('Not verified')).toBeNull()
  })
})

describe('ExtractedFields', () => {
  it('loads rule-based fields on demand and shows the notice, and reports load failures', async () => {
    const fields = vi.mocked(api.structuredFields)
    fields.mockResolvedValueOnce({ documentId: 'd1', method: 'rule-based', notice: 'Deterministic; not ML.', dates: [{ page: 1, text: '03/04/2025', isoDate: null, ambiguous: true }],
      labResults: [{ page: 2, text: 'Sodium 139 mmol/L', testName: 'Sodium', value: 139, unit: 'mmol/L', flag: 'h' }] })
    const { container } = render(<DocumentClassification doc={doc()} onChanged={() => {}} />)
    const details = container.querySelector('details') as HTMLDetailsElement
    details.open = true
    fireEvent(details, new Event('toggle'))
    expect(await screen.findByText(/Sodium 139 mmol\/L \(H\)/)).toBeTruthy()
    expect(screen.getByText(/ambiguous/)).toBeTruthy()
    expect(screen.getByText('Deterministic; not ML.')).toBeTruthy()
    cleanup()
    fields.mockRejectedValue(new Error('boom'))
    const again = render(<DocumentClassification doc={doc()} onChanged={() => {}} />)
    const d2 = again.container.querySelector('details') as HTMLDetailsElement
    d2.open = true
    fireEvent(d2, new Event('toggle'))
    expect((await screen.findByRole('alert')).textContent).toContain('boom')
  })
})
