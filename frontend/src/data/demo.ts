export const GOLDEN_PATH = [
  { title: 'Open case HT-10482', body: 'John Anderson - Knee Osteoarthritis - prior authorization for an Advanced Knee Intervention.' },
  { title: 'Click WHY? on a MATCH', body: '8 weeks of physiotherapy against a 6 week policy requirement. See the full evidence chain.' },
  { title: 'Inspect the missing MRI', body: 'The system shows exactly which documents were searched and refuses to invent evidence.' },
  { title: 'Compare the conflict', body: 'The referral says 4 weeks, the clinical notes say 8. Nothing is auto-resolved.' },
  { title: 'Act as the reviewer', body: 'Accept, override with a reason, or request evidence.' },
  { title: 'Open the Audit Trail', body: 'Every AI step, rule evaluation, and human action is recorded.' },
]

export const PIPELINE = [
  { step: 'Extract', detail: 'AI reads documents and pulls out facts' },
  { step: 'Trace', detail: 'Each fact is tied to its exact source text' },
  { step: 'Validate', detail: 'Deterministic rules check policy criteria' },
  { step: 'Review', detail: 'A human accepts, overrides, or requests evidence' },
  { step: 'Audit', detail: 'Every step is recorded for accountability' },
]
