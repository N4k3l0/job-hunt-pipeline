import { redirect } from "next/navigation";

/** Apply for me's list is part of Applications now. */
export default function AutoApplyPage() {
  redirect("/dashboard/applications");
}
