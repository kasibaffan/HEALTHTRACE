/** Mirrors backend app/ml/labels.py. Identifiers are stored server-side; names are display text only. */
export const DOCUMENT_TYPES: { value: string; name: string }[] = [
  { value: 'CLINICAL_REPORT', name: 'Clinical report' },
  { value: 'IMAGING_REPORT', name: 'Imaging report' },
  { value: 'LABORATORY_RESULT', name: 'Laboratory result' },
  { value: 'REFERRAL_ORDER', name: 'Referral or order' },
  { value: 'CLAIM_BILLING', name: 'Claim or billing document' },
  { value: 'POLICY_DOCUMENT', name: 'Policy document' },
  { value: 'OTHER', name: 'Other or unknown' },
]

export const documentTypeName = (value: string | null | undefined): string => DOCUMENT_TYPES.find((t) => t.value === value)?.name ?? 'Unknown'
