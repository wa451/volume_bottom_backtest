import JobPage from "@/components/job";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <JobPage key={id} id={id} />;
}
