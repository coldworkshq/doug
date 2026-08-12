import type { DocsStatus } from "@/lib/docs-nav";

const LABEL: Record<DocsStatus, string> = {
  available: "Available",
  preview: "Preview",
  planned: "Planned",
};

const TONE: Record<DocsStatus, string> = {
  available: "bg-clear/10 text-clear",
  preview: "bg-warn/10 text-warn",
  planned: "bg-sheen/10 text-sheen",
};

const DOT: Record<DocsStatus, string> = {
  available: "bg-clear",
  preview: "bg-warn",
  planned: "bg-sheen",
};

/** The pill next to an H1 — "this claim is live," "this is a preview," or
 *  "this doesn't exist yet." Every doc page carries one except Introduction
 *  and Changelog, which aren't claims about the product. */
export function StatusBadge({ status }: { status: DocsStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 font-mono text-[11px] font-medium tracking-wide uppercase ${TONE[status]}`}
    >
      {LABEL[status]}
    </span>
  );
}

/** The sidebar's small status dot. Renders nothing for an undefined status —
 *  the gh-pages source it's ported from gave Introduction and Changelog an
 *  "available" dot anyway (their entries just never carry a badge in the
 *  actual content), which is a stray signal this codebase's own standing
 *  rule ("don't claim something the UI can't back up") argues for dropping
 *  rather than porting faithfully. */
export function StatusDot({ status }: { status?: DocsStatus }) {
  if (!status) return null;
  return (
    <span
      className={`size-1.5 shrink-0 rounded-full ${DOT[status]}`}
      aria-hidden="true"
    />
  );
}
