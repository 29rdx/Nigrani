/** The Nigrani mark: a heartbeat line in a rounded square. */
export default function Logo({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="Nigrani" style={{ flex: 'none' }}>
      <defs><linearGradient id="nigrani-logo" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#6b93ff" /><stop offset="1" stopColor="#2f5fe3" /></linearGradient></defs>
      <rect width="32" height="32" rx="8" fill="url(#nigrani-logo)" />
      <path d="M5 16.5h5.2l2.6-6.4 4.4 11.6 2.8-5.2H27" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
