"use client";

import { use } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Printer, Loader2 } from "lucide-react";
import {
  useTailoredApplication,
  useProfile,
  useCurrentUser,
  useWorkHistory,
  useSkills,
} from "@/hooks/use-api";

/**
 * Print-friendly resume view. Replaces the WeasyPrint-generated PDF the
 * backend used to produce — Vercel's serverless Python runtime can't ship
 * the cairo/pango libs WeasyPrint needs, so we render the same content as
 * a clean HTML page and let the user "Save as PDF" from the browser print
 * dialog (Cmd+P → Save as PDF).
 */
export default function PrintResumePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: tailored, isLoading } = useTailoredApplication(id);
  const { data: profile } = useProfile();
  const { data: user } = useCurrentUser();
  const { data: workHistory } = useWorkHistory();
  const { data: skills } = useSkills();

  if (isLoading || !tailored) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // The tailored resume JSON has the AI-selected experience + bullets. Fall
  // back to the user's master work history for any roles the AI didn't include.
  const tailoredJson = (tailored as any).tailored_resume_json as
    | {
        tailored_summary?: string;
        selected_experience?: Array<{
          company: string;
          title: string;
          dates?: string;
          bullets?: string[];
        }>;
        highlighted_skills?: string[];
      }
    | undefined;

  const summary = tailored.tailored_summary ?? tailoredJson?.tailored_summary ?? "";
  const experience = tailoredJson?.selected_experience ?? [];
  const highlightedSkills = tailoredJson?.highlighted_skills ?? [];
  const allSkills = (skills ?? []).map((s: any) => s.skill_name).filter(Boolean);

  // Display name + contact: pull from currentUser + profile.
  const displayName = user?.name || user?.email?.split("@")[0] || "—";
  const links = profile?.links ?? {};
  const linkedinUrl = links.linkedin;
  const portfolioUrl = links.portfolio;

  return (
    <>
      {/* Toolbar — only visible on screen, hidden when printing */}
      <div className="print:hidden flex items-center justify-between gap-3 max-w-[8.5in] mx-auto mb-4">
        <Button variant="ghost" size="sm" render={<Link href="/dashboard/review" />}>
          <ArrowLeft className="h-4 w-4" />
          Back to review
        </Button>
        <div className="flex items-center gap-2">
          <p className="hidden sm:block text-xs text-muted-foreground">
            Press <kbd className="font-mono rounded border border-white/10 px-1.5 py-0.5 text-[10px]">⌘P</kbd> →
            choose <span className="font-medium text-foreground">Save as PDF</span>
          </p>
          <Button size="sm" onClick={() => window.print()}>
            <Printer className="h-4 w-4" />
            Print / save PDF
          </Button>
        </div>
      </div>

      {/* The resume itself — styled for both screen and print. The .resume-page
          class drives the print-only layout adjustments. */}
      <article className="resume-page max-w-[8.5in] mx-auto bg-white text-zinc-900 px-12 py-12 shadow-2xl shadow-black/40 print:shadow-none print:py-0">
        <header className="border-b border-zinc-300 pb-4 mb-6">
          <h1 className="font-display text-4xl font-semibold text-zinc-900 leading-none tracking-tight">
            {displayName}
          </h1>
          {profile?.headline && (
            <p className="text-base text-zinc-700 mt-2">{profile.headline}</p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-600">
            {user?.email && <span>{user.email}</span>}
            {linkedinUrl && (
              <a href={linkedinUrl} className="text-zinc-700 underline-offset-2 hover:underline">
                {linkedinUrl.replace(/^https?:\/\//, "")}
              </a>
            )}
            {portfolioUrl && (
              <a href={portfolioUrl} className="text-zinc-700 underline-offset-2 hover:underline">
                {portfolioUrl.replace(/^https?:\/\//, "")}
              </a>
            )}
          </div>
        </header>

        {summary && (
          <section className="mb-6">
            <h2 className="text-[11px] uppercase tracking-[0.15em] font-semibold text-zinc-500 mb-2">
              Summary
            </h2>
            <p className="text-sm leading-relaxed text-zinc-800">{summary}</p>
          </section>
        )}

        {experience.length > 0 && (
          <section className="mb-6">
            <h2 className="text-[11px] uppercase tracking-[0.15em] font-semibold text-zinc-500 mb-3">
              Experience
            </h2>
            <div className="space-y-5">
              {experience.map((role, i) => (
                <div key={`${role.company}-${i}`}>
                  <div className="flex items-baseline justify-between gap-2 mb-1">
                    <p className="text-sm font-semibold text-zinc-900">
                      {role.title}
                      <span className="font-normal text-zinc-700"> · {role.company}</span>
                    </p>
                    {role.dates && (
                      <p className="text-xs text-zinc-500 font-mono shrink-0">{role.dates}</p>
                    )}
                  </div>
                  {role.bullets && role.bullets.length > 0 && (
                    <ul className="space-y-1 mt-1.5">
                      {role.bullets.map((b, bi) => (
                        <li key={bi} className="text-sm text-zinc-800 leading-snug pl-4 -indent-4">
                          <span className="text-zinc-500">— </span>
                          {b}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {(highlightedSkills.length > 0 || allSkills.length > 0) && (
          <section>
            <h2 className="text-[11px] uppercase tracking-[0.15em] font-semibold text-zinc-500 mb-2">
              Skills
            </h2>
            <p className="text-sm text-zinc-800 leading-relaxed">
              {(highlightedSkills.length > 0 ? highlightedSkills : allSkills.slice(0, 20)).join(" · ")}
            </p>
          </section>
        )}

        {/* Master work history fallback — shown when tailored AI didn't pick any
            experience (e.g. profile not yet parsed). Hidden if AI did its job. */}
        {experience.length === 0 && workHistory && workHistory.length > 0 && (
          <section className="mt-6">
            <h2 className="text-[11px] uppercase tracking-[0.15em] font-semibold text-zinc-500 mb-3">
              Experience (untailored)
            </h2>
            <div className="space-y-4">
              {workHistory.map((entry: any) => (
                <div key={entry.id}>
                  <p className="text-sm font-semibold text-zinc-900">
                    {entry.title} · {entry.company}
                  </p>
                  {entry.bullets?.length > 0 && (
                    <ul className="space-y-1 mt-1">
                      {entry.bullets.map((b: string, i: number) => (
                        <li key={i} className="text-sm text-zinc-800 leading-snug pl-4 -indent-4">
                          <span className="text-zinc-500">— </span>
                          {b}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}
      </article>

      {/* Print-only page setup. Tells the browser to use letter paper and
          minimal margins, hides everything not in the .resume-page article,
          and switches the dashboard background to white so colors don't
          bleed into the print. */}
      <style>{`
        @media print {
          @page { size: letter; margin: 0.75in; }
          body, html { background: white !important; }
          body::before { display: none !important; }
          .resume-page {
            box-shadow: none !important;
            padding: 0 !important;
            max-width: none !important;
          }
          /* Sidebar + chrome don't make sense on paper */
          [data-slot="sidebar"], header[role="region"], nav, button {
            display: none !important;
          }
        }
      `}</style>
    </>
  );
}
