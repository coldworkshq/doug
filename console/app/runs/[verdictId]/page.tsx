import { notFound, redirect } from "next/navigation";
import { parseRunId } from "@/lib/selection";

export const dynamic = "force-dynamic";

export default async function RunDetailRedirect({
  params,
}: {
  params: Promise<{ verdictId: string }>;
}) {
  const { verdictId } = await params;
  const id = parseRunId(verdictId);
  if (id === null) notFound();
  redirect(`/?run=${id}`);
}
