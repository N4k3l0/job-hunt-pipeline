"use client";

import Link from "next/link";
import { ArrowLeft, CheckCircle2, Copy, Download, Loader2 } from "lucide-react";
import { useExtensionInstalled } from "@/hooks/use-extension";
import { useToast } from "@/components/ui/toast";

const EXTENSIONS_PAGE = "chrome://extensions";

function Step({ number, title, children }: { number: number; title: string; children?: React.ReactNode }) {
  return (
    <li className="flex" style={{ gap: 14 }}>
      <span
        className="ds-mono flex items-center justify-center"
        style={{
          flex: "0 0 28px",
          height: 28,
          borderRadius: 999,
          background: "var(--ds-bg-elev-2)",
          border: "1px solid var(--ds-line)",
          fontSize: 13,
        }}
      >
        {number}
      </span>
      <div className="space-y-2" style={{ paddingTop: 3, minWidth: 0 }}>
        <div style={{ fontWeight: 500 }}>{title}</div>
        {children}
      </div>
    </li>
  );
}

export default function ExtensionPage() {
  const installed = useExtensionInstalled();
  const toast = useToast();

  async function copyAddress() {
    try {
      await navigator.clipboard.writeText(EXTENSIONS_PAGE);
      toast.success("Copied", { description: "Paste it into Chrome's address bar." });
    } catch {
      toast.error("Couldn't copy", { description: `Type ${EXTENSIONS_PAGE} into Chrome's address bar.` });
    }
  }

  return (
    <div className="ds-root ds-page-fade" style={{ background: "var(--ds-bg)" }}>
      <div className="space-y-6" style={{ maxWidth: 720, margin: "0 auto", paddingBottom: 64 }}>
        <Link href="/dashboard/auto-apply" className="ds-btn ghost" style={{ paddingLeft: 0, width: "fit-content" }}>
          <ArrowLeft className="h-3.5 w-3.5" /> Apply for me
        </Link>

        <div className="space-y-2">
          <h1 className="ds-h1">Chrome extension</h1>
          <p className="ds-muted" style={{ maxWidth: 600 }}>
            Once you approve an application&apos;s answers, the extension opens the company&apos;s form and fills it in:
            your answers, and your resume attached. You look it over and press Submit. It works on Greenhouse, Lever
            and Ashby forms.
          </p>
        </div>

        <div className="ds-card flex items-center" style={{ padding: 16, gap: 10, fontSize: 14 }}>
          {installed === null ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin ds-dim" /> Checking whether it&apos;s installed…
            </>
          ) : installed ? (
            <>
              <CheckCircle2 className="h-4 w-4 ds-accent-fg" />
              <span>
                Installed. Open an approved application in{" "}
                <Link href="/dashboard/auto-apply" className="ds-accent-fg">Apply for me</Link> and press Fill in the form.
              </span>
            </>
          ) : (
            <span>Not installed in this browser yet. It takes about two minutes.</span>
          )}
        </div>

        {!installed && (
          <section className="ds-card space-y-5" style={{ padding: 20 }}>
            <h2 className="ds-h3">Install it</h2>
            <ol className="space-y-5" style={{ listStyle: "none", padding: 0, margin: 0 }}>
              <Step number={1} title="Download the extension">
                <a href="/job-hunt-extension.zip" download className="ds-btn primary" style={{ width: "fit-content" }}>
                  <Download className="h-4 w-4" /> Download
                </a>
              </Step>
              <Step number={2} title="Unzip it">
                <p className="ds-muted" style={{ fontSize: 14 }}>
                  Double-click the downloaded file. You get a folder called job-hunt-extension.
                </p>
              </Step>
              <Step number={3} title="Open Chrome's extensions page">
                <p className="ds-muted" style={{ fontSize: 14 }}>
                  Chrome doesn&apos;t let websites link to it. Copy this address and paste it into the address bar:
                </p>
                <button type="button" className="ds-btn" onClick={copyAddress} style={{ width: "fit-content" }}>
                  <Copy className="h-4 w-4" /> <span className="ds-mono">{EXTENSIONS_PAGE}</span>
                </button>
              </Step>
              <Step number={4} title="Turn on Developer mode">
                <p className="ds-muted" style={{ fontSize: 14 }}>
                  It&apos;s the switch in the top right corner of that page.
                </p>
              </Step>
              <Step number={5} title="Press Load unpacked and choose the job-hunt-extension folder">
                <p className="ds-muted" style={{ fontSize: 14 }}>
                  Then come back to this page and reload it. It should say Installed.
                </p>
              </Step>
            </ol>
          </section>
        )}

        <section className="space-y-2" style={{ fontSize: 14 }}>
          <h2 className="ds-h3">What it can see and do</h2>
          <ul className="ds-muted space-y-1" style={{ paddingLeft: 18, listStyle: "disc" }}>
            <li>It only runs on this app and on Greenhouse, Lever and Ashby job pages.</li>
            <li>It fills in the answers you approved, and nothing else.</li>
            <li>It never presses Submit. When you do, it tells Job Hunt so the job moves to Applications.</li>
            <li>It works in Chrome, Edge, Brave and Arc on a computer, not on phones.</li>
          </ul>
        </section>
      </div>
    </div>
  );
}
