import { notFound, redirect } from "next/navigation";
import { parseRunId } from "@/lib/selection";

export const dynamic = "force-dynamic";

export default async function RunDetailRedirect({
  params,
  searchParams,
}: {
  params: Promise<{ verdictId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { verdictId } = await params;
  const id = parseRunId(verdictId);
  if (id === null) notFound();

  // Preserve any scope/view query that arrived with the deep link
  // (/runs/1?tenant=…); drop a stale `run` in favour of the path id.
  const incoming = await searchParams;
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(incoming)) {
    if (key === "run" || value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) q.append(key, item);
    } else {
      q.set(key, value);
    }
  }
  q.set("run", String(id));
  redirect(`/?${q.toString()}`);
}
