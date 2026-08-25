/** The Doug mark — Saint Bernard, barrel-brandy ears. Same geometry as the
 *  console and the landing page, so the brand reads as one dog. */
export function DougLogo({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-hidden="true"
      className="inline-block"
    >
      <circle cx="32" cy="30" r="21" fill="#fff" stroke="#111311" strokeWidth="3" />
      <path
        d="M12 28 C6 15, 19 8, 24 14 L20 29 Z"
        fill="#D1571E"
        stroke="#111311"
        strokeWidth="3"
        strokeLinejoin="round"
      />
      <path
        d="M52 28 C58 15, 45 8, 40 14 L44 29 Z"
        fill="#D1571E"
        stroke="#111311"
        strokeWidth="3"
        strokeLinejoin="round"
      />
      <path d="M32 9 A21 21 0 0 1 52 26 L41 31 A11 11 0 0 0 32 27 Z" fill="#D1571E" opacity=".9" />
      <circle cx="25" cy="29" r="2.7" fill="#111311" />
      <circle cx="39" cy="29" r="2.7" fill="#111311" />
      <ellipse cx="32" cy="38" rx="4.8" ry="3.8" fill="#111311" />
    </svg>
  );
}
