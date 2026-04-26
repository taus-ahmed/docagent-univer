"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import TemplateEditor from "@/components/templates/TemplateEditor";

function EditPage() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id");
  return <TemplateEditor templateId={id ? Number(id) : undefined} />;
}

export default function EditTemplatePage() {
  return (
    <Suspense>
      <EditPage />
    </Suspense>
  );
}
