/** The HEALTH TRACE mark: a trace crossing a detection ring. */
export function Logo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="#0f1621" />
      <rect x="0.5" y="0.5" width="31" height="31" rx="7.5" fill="none" stroke="rgb(142 170 205 / 0.18)" />
      <circle cx="16" cy="16" r="9.5" fill="none" stroke="#2a3a4d" strokeWidth="1.5" />
      <path d="M5 16h6.5l2.2-5 4.2 10 2.3-5H27" fill="none" stroke="#56dcc8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
