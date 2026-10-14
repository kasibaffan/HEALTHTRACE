export type FindingStatus = 'match' | 'missing' | 'conflict'
export type ReviewAction = 'accept' | 'override' | 'request-evidence'

export interface DocumentPage { number: number; heading: string; lines: string[] }
export type ClassificationStatus = 'NOT_RUN' | 'CLASSIFIED' | 'NO_TEXT' | 'UNAVAILABLE' | 'DISABLED' | 'ERROR'
/** ML document-type SUGGESTION plus any human correction. `score` is an uncalibrated model output and must not be shown as a percentage. */
export interface DocumentClassification {
  status: ClassificationStatus
  label: string | null
  score: number | null
  lowConfidence: boolean
  modelVersion: string | null
  classifiedAt: string | null
  reviewedLabel: string | null
  reviewedBy: { id: string; fullName: string } | null
  reviewedAt: string | null
  effectiveLabel: string | null
}
/** Rule-based (not ML) dates and lab-style results with page and character span. */
export interface StructuredFields {
  documentId: string
  method: string
  notice: string
  dates: { page: number; text: string; isoDate: string | null; ambiguous: boolean }[]
  labResults: { page: number; text: string; testName: string; value: number; unit: string; flag: string | null }[]
}
export interface DocumentFile {
  id: string
  name: string
  type: string
  pages: number
  content: DocumentPage[]
  uploaded: boolean
  size: number | null
  status?: 'UPLOADED' | 'PROCESSING' | 'PROCESSED' | 'FAILED'
  progress?: number
  error?: string | null
  classification?: DocumentClassification
}

export interface Evidence {
  id: string
  documentId: string
  documentName: string
  page: number
  text: string
  highlight: string | null
  evidenceType: string
  verified: boolean
  supports: string[]
  note: string | null
  factSummary: string | null
  usedBy: string[]
  findingIds: string[]
  confidence?: number | null
}

export interface Fact {
  id: string
  name: string
  label: string
  value: number | string
  unit: string | null
  confidence: number
  sourceEvidenceIds: string[]
}

export interface Rule {
  id: string
  criterionId: string
  expression: string
  operator: string
  threshold: number | string | null
  unit: string | null
  actual: number | string | null
  result: boolean | null
  evaluation: string
}

export interface PolicyCriterion {
  id: string
  title: string
  requirement: string
  ruleId: string
  sourceEvidenceId?: string
  sourceDocumentName?: string | null
  sourcePage?: number | null
  sourceText?: string | null
}
export interface Policy { name: string; version: string; description: string; criteria: PolicyCriterion[] }

export interface ReviewRecord { reviewer: string; action: ReviewAction; reason: string | null; timestamp: string }

export interface Finding {
  id: string
  caseId: string
  criterionId: string
  criterion: string
  requirement: string
  status: FindingStatus
  severity: 'low' | 'medium' | 'high'
  factId: string | null
  factIds: string[]
  ruleId: string
  evidenceIds: string[]
  reviewedEvidenceIds: string[]
  explanation: string
  searchedDocuments: string[]
  expectedEvidence: string | null
  suggestedAction: string | null
  review: ReviewRecord | null
  version: number
}

export interface AuditEvent {
  id: string
  caseId: string
  timestamp: string
  actor: string
  action: string
  target: string
  reason: string | null
}

export interface TimelineEvent { id: string; date: string; label: string; detail: string; evidenceId: string; documentId?: string; documentName?: string; page?: number }

export interface CaseSummary {
  id: string
  caseNumber: string
  patient: string
  condition: string
  procedure: string
  status: string
  complexity: number
  missingEvidence: number
  conflicts: number
  openable: boolean
  updated: string
}
export interface CaseDetail extends CaseSummary {
  policyName: string
  payer: string
  dateOfBirth: string
  memberId: string
  requestedOn: string
  documents: DocumentFile[]
  summary: string
}

export interface ChainNode {
  id: string
  kind: 'finding' | 'policy' | 'rule' | 'requirement' | 'fact' | 'evidence' | 'document' | 'search' | 'outcome'
  title: string
  subtitle: string | null
  tone: 'neutral' | FindingStatus
  lane: 'A' | 'B' | null
  metadata: Record<string, string>
  documentId: string | null
  page: number | null
  evidenceId: string | null
}

export interface EvidenceChain {
  finding: Finding
  criterion: PolicyCriterion
  rule: Rule
  facts: Fact[]
  evidence: Evidence[]
  reviewedEvidence: Evidence[]
  chain: ChainNode[]
  laneLabels: Record<string, string>
}

export interface DashboardStats {
  activeCases: number
  needsReview: number
  missingEvidence: number
  conflicts: number
  humanReviewsToday: number
  recentCases: CaseSummary[]
}
