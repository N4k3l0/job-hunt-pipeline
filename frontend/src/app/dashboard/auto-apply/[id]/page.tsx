"use client";

import { use } from "react";
import { ApplicationWorkspace } from "@/components/application-workspace";

export default function AutoApplicationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <ApplicationWorkspace id={id} />;
}
