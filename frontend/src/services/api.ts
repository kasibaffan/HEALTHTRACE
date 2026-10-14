import type { AuditEvent, CaseDetail, CaseSummary, DashboardStats, DocumentClassification, DocumentFile, StructuredFields, Evidence, EvidenceChain, Fact, Finding, Policy, ReviewAction, Rule, TimelineEvent } from '../types'

const BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? '').replace(/\/$/, '')
let accessToken: string | null = null
let refreshPromise: Promise<AuthSession | null> | null = null
let unauthorizedHandler: (() => void) | null = null

export interface AuthSession {
  accessToken: string
  expiresIn: number
  user: { id: string; fullName: string; email: string; avatarUrl: string | null }
  organization: { id: string; name: string; slug: string }
  role: string
  permissions: string[]
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

export function setUnauthorizedHandler(handler: (() => void) | null) { unauthorizedHandler = handler }
export function setAccessToken(token: string | null) { accessToken = token }

async function raw<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
  let res: Response
  try {
    const headers = new Headers(init.headers)
    if (authenticated && accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
    res = await fetch(`${BASE}/api${path}`, { ...init, headers, credentials: 'include' })
  } catch {
    throw new ApiError('Cannot reach the HealthTrace API. Make sure the backend is running on port 8000.', 0)
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = body.detail.map((e: { msg?: string }) => e.msg).filter(Boolean).join(' ')
      if (body.code === 'validation_error' && body.fields && typeof body.fields === 'object') {
        const fieldErrors = Object.entries(body.fields as Record<string, unknown>).map(([field, message]) => `${field}: ${String(message)}`)
        if (fieldErrors.length) detail = fieldErrors.join(' ')
      }
    } catch { /* preserve the status fallback */ }
    if ([502, 503, 504].includes(res.status)) detail = 'The review service is unreachable. Start the backend on port 8000 and retry.'
    throw new ApiError(detail, res.status)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

async function refreshSession(): Promise<AuthSession | null> {
  if (!refreshPromise) {
    refreshPromise = raw<AuthSession>('/auth/refresh', { method: 'POST' }, false)
      .then((session) => { accessToken = session.accessToken; return session })
      .catch(() => { accessToken = null; return null })
      .finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  try { return await raw<T>(path, init) }
  catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401 || path === '/auth/refresh' || path === '/auth/login' || path === '/auth/register') throw error
    const session = await refreshSession()
    if (!session) {
      unauthorizedHandler?.()
      throw error
    }
    try { return await raw<T>(path, init) }
    catch (retryError) {
      if (retryError instanceof ApiError && retryError.status === 401) {
        accessToken = null
        unauthorizedHandler?.()
      }
      throw retryError
    }
  }
}

const json = (method: string, body?: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
type Page<T> = { items: T[]; total: number; page: number; pageSize: number }
const pageItems = <T>(page: Page<T> | T[]): T[] => Array.isArray(page) ? page : page.items
const status = (value: string) => value.toLowerCase()

function caseSummary(c: any): CaseSummary {
  const labels: Record<string, string> = { NEEDS_REVIEW: 'Needs Review', IN_REVIEW: 'In Review', COMPLETED: 'Review Complete', WAITING_FOR_EVIDENCE: 'Awaiting Evidence', READY_FOR_DECISION: 'Ready for Decision' }
  return { id: c.id, caseNumber: c.caseNumber, patient: c.patientReference, condition: c.condition, procedure: c.requestedProcedure,
    status: labels[c.status] ?? c.status.replaceAll('_', ' '), complexity: c.reviewComplexity ?? 0, missingEvidence: c.missingEvidence ?? 0, conflicts: c.conflicts ?? 0,
    openable: true, updated: c.updatedAt }
}
function findingModel(f: any): Finding {
  const state = f.status === 'INCONCLUSIVE' ? 'conflict' : status(f.status)
  const actions: Record<string, ReviewAction> = { ACCEPTED: 'accept', OVERRIDDEN: 'override', REQUESTED_EVIDENCE: 'request-evidence' }
  return { ...f, status: state as Finding['status'], review: f.review ? { ...f.review, action: actions[f.review.action] ?? f.review.action } : null }
}
function documentModel(d: any, content: DocumentFile['content'] = []): DocumentFile {
  return { id: d.id, name: d.filename, type: d.docType || d.fileType, pages: d.pageCount || content.length, content, uploaded: true, size: d.fileSize,
    status: d.status, progress: d.progress, error: d.error, classification: d.classification }
}
function evidenceModel(e: any): Evidence {
  return { ...e, id: e.id, highlight: e.highlight ?? null, note: e.note ?? null, factSummary: e.factSummary ?? null, supports: [],
    usedBy: e.usedBy ?? [], findingIds: e.findingIds ?? [] }
}
function timelineModel(t: any): TimelineEvent {
  const evidence = t.evidence
  return { id: t.id, date: t.date, label: t.label, detail: t.detail, evidenceId: evidence?.id ?? '', documentId: evidence?.documentId, documentName: evidence?.documentName, page: evidence?.page }
}

async function resolveCaseId(input: string): Promise<string> {
  if (/^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(input)) return input
  const cases = pageItems(await request<Page<any>>(`/cases?search=${encodeURIComponent(input)}&pageSize=100`))
  const found = cases.find((c: any) => c.caseNumber === input)
  if (!found) throw new ApiError(`Case ${input} was not found in this workspace.`, 404)
  return found.id
}

export const CASE_ID = 'HT-10482'

export const api = {
  login: async (email: string, password: string) => { const s = await request<AuthSession>('/auth/login', json('POST', { email, password })); accessToken = s.accessToken; return s },
  register: async (fullName: string, email: string, password: string, confirmPassword: string, organizationName?: string) => {
    const s = await request<AuthSession>('/auth/register', json('POST', { fullName, email, password, confirmPassword, organizationName: organizationName || undefined })); accessToken = s.accessToken; return s
  },
  restoreSession: refreshSession,
  logout: async () => { try { await request('/auth/logout', json('POST')) } finally { accessToken = null } },
  health: () => request<{ status: 'healthy' | 'degraded'; api: 'up'; database: 'up' | 'down'; websocket: { status: 'up' | 'starting'; connections: number }; apiKeyRequired: boolean }>('/health'),
  dashboard: async (): Promise<DashboardStats> => {
    const d: any = await request('/dashboard')
    return { activeCases: d.totalCases, needsReview: d.casesNeedingReview, missingEvidence: d.missingEvidence, conflicts: d.openConflicts,
      humanReviewsToday: d.humanReviewsToday, recentCases: (d.recentCases ?? []).map(caseSummary) }
  },
  loadDemo: async (): Promise<CaseDetail> => {
    let c: any
    try { c = await request('/cases/demo', json('POST')) }
    catch (e) {
      if (!(e instanceof ApiError) || e.status !== 409) throw e
      const found: any = pageItems(await request<Page<any>>(`/cases?search=${CASE_ID}&pageSize=100`)).find((x: any) => x.caseNumber === CASE_ID)
      if (!found) throw e
      c = await request(`/cases/${found.id}`)
    }
    if (!c.documents) c = await request(`/cases/${c.id}`)
    return caseDetailModel(c)
  },
  cases: async (page = 1, search = ''): Promise<Page<CaseSummary>> => {
    const params = new URLSearchParams({ page: String(page), pageSize: '25' })
    if (search.trim()) params.set('search', search.trim())
    const result = await request<Page<any>>(`/cases?${params.toString()}`)
    return { ...result, items: result.items.map(caseSummary) }
  },
  caseDetail: async (id: string): Promise<CaseDetail> => caseDetailModel(await request(`/cases/${await resolveCaseId(id)}`)),
  findings: async (id: string): Promise<Finding[]> => (await request<any[]>(`/cases/${await resolveCaseId(id)}/findings`)).map(findingModel),
  facts: async (id: string): Promise<Fact[]> => {
    const findings = await api.findings(id)
    const chains = await Promise.all(findings.map((f) => request<EvidenceChain>(`/findings/${f.id}/evidence-chain`)))
    return chains.flatMap((c) => c.facts)
  },
  evidence: async (id: string): Promise<Evidence[]> => pageItems(await request<Page<any>>(`/cases/${await resolveCaseId(id)}/evidence?pageSize=100`)).map(evidenceModel),
  documents: async (id: string): Promise<DocumentFile[]> => {
    const caseId = await resolveCaseId(id)
    const docs = pageItems(await request<Page<any>>(`/cases/${caseId}/documents?pageSize=100`))
    return Promise.all(docs.map(async (d: any) => {
      const detail: any = await request(`/documents/${d.id}`)
      const content = (detail.pages ?? []).map((p: any) => ({ number: p.number, heading: p.heading, lines: p.lines }))
      return documentModel(d, content)
    }))
  },
  documentContext: async (documentId: string) => {
    const detail: any = await request(`/documents/${documentId}`)
    const [documents, evidence] = await Promise.all([api.documents(detail.caseId), api.evidence(detail.caseId)])
    return { documents, evidence }
  },
  timeline: async (id: string): Promise<TimelineEvent[]> => (await request<any[]>(`/cases/${await resolveCaseId(id)}/timeline`)).map(timelineModel),
  audit: async (id: string): Promise<AuditEvent[]> => pageItems(await request<Page<any>>(`/cases/${await resolveCaseId(id)}/audit?pageSize=100`)),
  policy: async (): Promise<Policy> => {
    const policies: any[] = await request('/policies')
    const p = policies.find((x) => x.status === 'ACTIVE') ?? policies[0]
    if (!p) throw new ApiError('No policy is configured for this workspace.', 404)
    return { name: p.name, version: p.version, description: p.description ?? '', criteria: (p.rules ?? []).map((r: any) => ({
      id: r.code, title: r.findingTitle || r.name, requirement: r.requirement, ruleId: r.id,
      sourceDocumentName: r.sourceDocumentName ?? null, sourcePage: r.sourcePage ?? null, sourceText: r.sourceText ?? null,
    })) }
  },
  rules: async (): Promise<Rule[]> => {
    const policies: any[] = await request('/policies')
    const p = policies.find((x) => x.status === 'ACTIVE') ?? policies[0]
    return (p?.rules ?? []).map((r: any) => ({ id: r.id, criterionId: r.code, expression: r.expression, operator: r.operator, threshold: r.threshold, unit: r.unit, actual: null, result: null, evaluation: '' }))
  },
  chain: (findingId: string) => request<EvidenceChain>(`/findings/${findingId}/evidence-chain`),
  recordOpened: (findingId: string) => request<void>(`/findings/${findingId}/opened`, { method: 'POST' }).catch(() => undefined),
  review: async (findingId: string, action: ReviewAction, reason?: string, expectedVersion?: number) =>
    findingModel(await request<any>(`/findings/${findingId}/${action}`, json('POST', { reason: reason || null, expectedVersion }))),
  reviewClassification: (documentId: string, label: string | null) =>
    request<DocumentClassification>(`/documents/${documentId}/classification`, json('PATCH', { label })),
  structuredFields: (documentId: string) => request<StructuredFields>(`/documents/${documentId}/structured-fields`),
  retryClassification: (documentId: string) => request<DocumentClassification>(`/documents/${documentId}/classification/retry`, { method: 'POST' }),
  upload: async (file: File, caseId = CASE_ID) => {
    const form = new FormData(); form.append('file', file)
    const id = await resolveCaseId(caseId)
    const d: any = await request(`/cases/${id}/documents`, { method: 'POST', body: form })
    return documentModel(d)
  },
}

function caseDetailModel(c: any): CaseDetail {
  return { ...caseSummary(c), policyName: c.policyName ?? '', payer: '', dateOfBirth: '', memberId: c.memberReference ?? '', requestedOn: c.requestedOn ?? '',
    documents: (c.documents ?? []).map((d: any) => documentModel(d)), summary: c.summary ?? '' }
}
