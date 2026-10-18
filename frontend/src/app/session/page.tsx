import { redirect } from "next/navigation";
export default async function SessionPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>;
}) {
  const { id } = await searchParams;
  redirect(id ? `/?id=${encodeURIComponent(id)}` : "/");
}
