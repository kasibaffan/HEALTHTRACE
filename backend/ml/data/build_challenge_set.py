"""Writes challenge_set.jsonl: hand-written FICTIONAL documents that do NOT come from the synthetic generator.
They probe whether the model survives wording it was not trained on. Small (n≈30), so scores are indicative only."""
import json
from pathlib import Path

ROWS = [
 ("CLINICAL_REPORT", "Seen today for review of knee pain. Mr Example reports the pain has gone on for about a year, worse on stairs. He did eight weeks of physio last winter and says it helped only slightly. Examination: swollen, a bit warm, grating on movement. Plan: discuss options, trial of topical gel, see again in a month."),
 ("CLINICAL_REPORT", "Discharge note. Admitted overnight with chest tightness; troponin repeat was reassuring and symptoms settled. Sent home on current meds, GP to follow up within one week. Advised to return if pain recurs."),
 ("CLINICAL_REPORT", "S: back pain radiating down left leg x 3 weeks. O: SLR positive at 40 degrees, reflexes normal. A: probable lumbar radiculopathy. P: NSAIDs, gentle exercise, reassess 4-6 wks, red flags explained."),
 ("CLINICAL_REPORT", "Follow-up visit. Blood pressure well controlled on amlodipine. No side effects. Discussed diet and salt intake. Next appointment in six months."),
 ("IMAGING_REPORT", "MRI right knee. Findings: tear of the medial meniscus posterior horn, cartilage thinning in the medial compartment, small effusion. Cruciate and collateral ligaments intact. Conclusion: degenerative medial meniscal tear with early osteoarthritis."),
 ("IMAGING_REPORT", "Chest radiograph PA view. Lungs are clear. Heart size is normal. No pleural effusion or pneumothorax. Bony thorax unremarkable. Radiologist: fictional reader."),
 ("IMAGING_REPORT", "CT abdomen and pelvis with contrast for abdominal pain. The liver, spleen and pancreas look normal. No bowel obstruction. Appendix not inflamed. No free fluid."),
 ("IMAGING_REPORT", "Ultrasound of the right shoulder: the supraspinatus tendon is thickened with a partial thickness tear. Subacromial bursa fluid present. Biceps tendon in groove."),
 ("LABORATORY_RESULT", "Blood tests collected 12/03/2025. HbA1c 58 mmol/mol (high). Fasting glucose 8.1. Cholesterol 5.9. Kidney function normal, eGFR 88. Lab comment: results consistent with suboptimal glycaemic control."),
 ("LABORATORY_RESULT", "FBC: Hb 11.2 L, WCC 7.4, Plt 250. Ferritin 9 L. B12 normal. Specimen received in good condition. Authorised by duty biochemist."),
 ("LABORATORY_RESULT", "Urine culture: more than 100,000 cfu/mL E. coli. Sensitive to nitrofurantoin and trimethoprim. Resistant to ampicillin. Report issued after 48 h incubation."),
 ("LABORATORY_RESULT", "Thyroid profile  TSH 5.8 mIU/L (0.4-4.0)  Free T4 12 pmol/L (9-19). Interpretation: borderline raised TSH, repeat in 6 weeks advised."),
 ("REFERRAL_ORDER", "Dear Mr Fictional, thank you for reviewing this woman with a painful, stiff hip who has not settled with exercise and analgesia. I would be grateful if you could consider her for joint replacement. X-rays attached."),
 ("REFERRAL_ORDER", "Please book: MRI lumbar spine, urgent. Indication: sciatica with foot weakness. Referrer to be notified of result. Order placed by the surgery on behalf of the patient."),
 ("REFERRAL_ORDER", "Request for physiotherapy: 6 sessions for rotator cuff tendinopathy, left shoulder. Please advise on home exercises. Patient is available weekday afternoons."),
 ("REFERRAL_ORDER", "Authorisation request: outpatient cardiology review and echocardiogram for new breathlessness on exertion. Supporting clinic letter enclosed."),
 ("CLAIM_BILLING", "Statement of account. Services 03/02/2025: office visit $145.00, X-ray $88.50, injection $60.00. Insurance paid $210.00. Balance due $83.50 by 15 April."),
 ("CLAIM_BILLING", "Explanation of benefits - this is not a bill. Provider charged $12,400. Plan allowed $7,950. You may owe $1,200 after deductible. Claim status: processed."),
 ("CLAIM_BILLING", "CLAIM FORM  Patient ID 55821  Procedure code 27447  Diagnosis M17.11  Charge 9800.00  Rendering provider NPI 1234567890  Submitted electronically."),
 ("CLAIM_BILLING", "Denied: service not covered, no prior authorisation on file. You can appeal within 180 days. Contact member services quoting reference on this letter."),
 ("POLICY_DOCUMENT", "Coverage determination guideline: knee replacement. Members qualify when there is radiographic evidence of advanced osteoarthritis, failure of at least three months of non-operative care, and functional impairment documented by the surgeon."),
 ("POLICY_DOCUMENT", "Our plan does not cover cosmetic procedures. Procedures must be medically necessary and provided by in-network clinicians unless prior approval is obtained. See Section 4 for the appeals process."),
 ("POLICY_DOCUMENT", "Utilisation management criteria - spinal injections. Authorisation may be granted if conservative therapy has been tried for six weeks, pain is radicular, and imaging supports the level. Repeat injections require documented benefit."),
 ("POLICY_DOCUMENT", "Guideline summary: indications, contraindications and documentation required for approval of outpatient MRI. Effective for requests received after 1 July. Replaces the earlier bulletin."),
 ("OTHER", "Hi all, just a reminder that the team lunch is moved to Thursday. Please let me know about dietary requirements. Thanks, Sam."),
 ("OTHER", "Quarterly sales summary: revenue up 4 percent on last year, driven by the northern region. Marketing spend held flat. Headcount unchanged."),
 ("OTHER", "How to reset your password: click the link on the login page, enter your email, and follow the instructions we send you. The link expires after one hour."),
 ("OTHER", "Welcome to our hospital volunteer programme! Volunteers help with wayfinding, reading to children and running the gift shop. Training takes place on the first Saturday of each month."),
 ("OTHER", "Chocolate chip cookies: cream butter and sugar, add eggs, fold in flour and chips, bake at 180 degrees for twelve minutes."),
 ("OTHER", "Orientation schedule for new starters: 9am welcome, 10am IT setup, 11am health and safety briefing, noon lunch with your buddy."),
]
out = Path(__file__).with_name("challenge_set.jsonl")
out.write_text("\n".join(json.dumps({"label": l, "text": t}) for l, t in ROWS) + "\n", encoding="utf-8")
print(f"wrote {len(ROWS)} rows to {out.name}")
