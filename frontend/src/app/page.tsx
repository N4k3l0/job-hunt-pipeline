"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, Check } from "lucide-react";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api-client";

import "./homepage.css";

/**
 * Marketing homepage. Two responsibilities:
 *
 * 1. If the URL has a magic-link hash (#access_token=…) we forward to
 *    /auth/callback so the existing handler can land the session.
 * 2. Otherwise render the editorial landing page from the v2 design
 *    handoff. The dashboard CTA sends users into /dashboard; middleware
 *    handles the auth gate from there.
 */
export default function Home() {
  const [magicLink, setMagicLink] = useState(false);

  useEffect(() => {
    const hash = window.location.hash || "";
    if (hash.includes("access_token") || hash.includes("error_description")) {
      setMagicLink(true);
      window.location.replace(`/auth/callback${hash}`);
      return;
    }
    document.body.dataset.page = "home";
    return () => {
      delete document.body.dataset.page;
    };
  }, []);

  if (magicLink) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Redirecting…
      </div>
    );
  }

  return (
    <div className="hp">
      <TopBar />
      <Hero />
      <ProductStill />
      <HowItWorks />
      <Scoring />
      <FounderNote />
      <Invite />
      <Footer />
    </div>
  );
}

/* ---------- Top bar ---------- */
function TopBar() {
  return (
    <header className="hp-top">
      <Link href="/" className="hp-brand">
        <span className="hp-brand-mark">J</span>
        <span>Job Hunt</span>
      </Link>
      <nav className="hp-top-nav">
        <a href="#how">How it works</a>
        <a href="#scoring">The matcher</a>
        <a href="#note">From the maker</a>
      </nav>
      <Link href="/dashboard" className="hp-top-cta">
        Open dashboard
        <ArrowUpRight size={12} strokeWidth={2} />
      </Link>
    </header>
  );
}

/* ---------- Hero ---------- */
function Hero() {
  return (
    <section className="hp-hero">
      <div className="hp-status-strip">
        <span className="hp-dot" />
        <span className="hp-mono">CURRENTLY INVITE-ONLY · TUNING THE MATCHER</span>
      </div>

      <h1 className="hp-hero-title">
        Job hunting,<br />
        <span className="hp-accent-italic">scored.</span>
      </h1>

      <p className="hp-hero-lede">
        A private inbox for people serious about their next role. Every posting gets a number from{" "}
        <span className="hp-mono hp-accent-text">0 to 100</span>, with a breakdown that tells you{" "}
        <em>why</em> it matched, not just that it did. New jobs every morning. For many of them, the app
        fills in the application form for you.
      </p>

      <InviteForm placeholder="you@work.com" formKey="hero" />
    </section>
  );
}

/* ---------- Email form (used in hero and invite card) ---------- */
function InviteForm({ placeholder, formKey }: { placeholder: string; formKey: "hero" | "invite" }) {
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    const trimmed = email.trim();
    if (!trimmed) {
      toast.error("Add your email first.");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/api/v1/invite-requests", { email: trimmed, source: formKey });
      setSuccess(true);
    } catch (err) {
      const invalid = (err as { status?: number }).status === 422;
      toast.error(invalid ? "That email doesn't look right." : "Couldn't reach the server", {
        description: invalid ? "Check it and try again." : "Try again in a moment.",
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className={`hp-email-form${formKey === "invite" ? " hp-invite-form" : ""}`} onSubmit={onSubmit}>
      <div className="hp-email-input-wrap">
        <span className="hp-email-prefix hp-mono">→</span>
        <input
          type="email"
          required
          placeholder={placeholder}
          aria-label="Email address"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={success}
        />
        <button type="submit" className="hp-email-cta" disabled={submitting || success}>
          Request invite
          <ArrowRight size={14} strokeWidth={2} />
        </button>
      </div>
      {formKey === "hero" && !success && (
        <div className="hp-email-meta hp-mono">
          <span>We read every request</span>
          <span className="hp-faint">·</span>
          <span>No marketing, ever</span>
        </div>
      )}
      <div className={`hp-email-success hp-mono${success ? " hp-on" : ""}`}>
        <Check size={14} strokeWidth={2.2} />
        Got it. We&apos;ll reply by hand.
      </div>
    </form>
  );
}

/* ---------- Product still (mini dashboard preview) ---------- */
function ProductStill() {
  return (
    <section className="hp-product-still">
      <div className="hp-caption">
        <span className="hp-mono hp-caption-eyebrow">FIG. 01 · YOUR INBOX, ONE WEEKDAY MORNING</span>
        <p>
          Not a job board. Not an aggregator. A column of postings, ranked by how well they fit
          the version of you we&apos;ve already learned. The top match leads. The rest follow in score order.
        </p>
      </div>

      <div className="hp-screenshot-frame">
        <div className="hp-screenshot-chrome">
          <div className="hp-chrome-dots">
            <span /><span /><span />
          </div>
          <div className="hp-chrome-url hp-mono">jobhuntpipeline.app/dashboard/jobs</div>
          <span style={{ width: 30 }} />
        </div>
        <div className="hp-screenshot-body">
          <aside className="hp-mini-sidebar">
            <div className="hp-mini-brand">
              <div className="hp-mini-mark">J</div>
              <span>Job Hunt</span>
            </div>
            <div className="hp-mini-section-label">PIPELINE</div>
            <div className="hp-mini-nav-list">
              <div className="hp-mini-nav hp-active"><span>Inbox</span><span className="hp-mono hp-dim-num">287</span></div>
              <div className="hp-mini-nav"><span>Review Queue</span><span className="hp-mono hp-dim-num">5</span></div>
              <div className="hp-mini-nav"><span>Applications</span><span className="hp-mono hp-dim-num">12</span></div>
              <div className="hp-mini-nav"><span>Analytics</span></div>
            </div>
          </aside>
          <main className="hp-mini-main">
            <MiniHeader />
            <MiniChips />
            <MiniEditorial />
            <MiniList />
          </main>
        </div>
      </div>
    </section>
  );
}

function MiniHeader() {
  return (
    <div className="hp-mini-header">
      <h2>
        Inbox <span className="hp-mono hp-accent-text">· 287</span>{" "}
        <span className="hp-mono hp-dim-num">scored</span>
      </h2>
      <p>
        Last sweep <span className="hp-mono hp-fg">06:04 UTC</span> · 23 new in the past 24h
      </p>
    </div>
  );
}

function MiniChips() {
  const chips: Array<{ label: string; count: number; on?: boolean }> = [
    { label: "All", count: 287, on: true },
    { label: "Top matches", count: 14 },
    { label: "New today", count: 23 },
    { label: "Remote · US", count: 96 },
    { label: "Europe", count: 41 },
  ];
  return (
    <div className="hp-mini-chips">
      {chips.map((c) => (
        <span key={c.label} className={`hp-mini-chip${c.on ? " hp-on" : ""}`}>
          {c.label} <span className="hp-mono hp-num">{c.count}</span>
        </span>
      ))}
    </div>
  );
}

function MiniEditorial() {
  const r = 35;
  const C = 2 * Math.PI * r;
  const offset = C * (1 - 94 / 100);
  return (
    <div className="hp-mini-editorial">
      <div className="hp-mini-editorial-top">
        <span className="hp-mono hp-mini-overline">◆ TOP MATCH · LIVE</span>
        <span className="hp-mono hp-dim-num">12m ago</span>
      </div>
      <div className="hp-mini-editorial-body">
        <div className="hp-mini-editorial-text">
          <div className="hp-mini-company">Linear</div>
          <div className="hp-mini-title">Senior Product Designer, Issue Tracking</div>
          <p className="hp-mini-summary">
            Linear is hiring a senior designer to own the issue tracking surfaces, the core of
            the product. You&apos;ll partner with two PMs and four engineers on the surfaces where
            users spend 80% of their day.
          </p>
        </div>
        <div className="hp-mini-score-ring">
          <svg viewBox="0 0 80 80" width="76" height="76">
            <circle cx="40" cy="40" r={r} stroke="var(--line-strong)" strokeWidth="3" fill="none" />
            <circle
              cx="40"
              cy="40"
              r={r}
              stroke="var(--accent)"
              strokeWidth="3"
              fill="none"
              strokeDasharray={C}
              strokeDashoffset={offset}
              transform="rotate(-90 40 40)"
              strokeLinecap="round"
            />
          </svg>
          <div className="hp-mini-score-num hp-mono hp-accent-text">94</div>
        </div>
      </div>
      <div className="hp-mini-breakdown">
        {[
          { label: "TITLE", value: 96 },
          { label: "SKILLS", value: 94 },
          { label: "SENIORITY", value: 92 },
          { label: "SALARY", value: 88 },
        ].map((a) => (
          <div key={a.label} className="hp-mini-axis">
            <div className="hp-mini-axis-label hp-mono">{a.label}</div>
            <div className="hp-mini-axis-value hp-mono hp-accent-text">
              {a.value}<span className="hp-faint">/100</span>
            </div>
            <div className="hp-mini-axis-bar"><span style={{ width: `${a.value}%` }} /></div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MiniList() {
  const rows = [
    { score: 92, title: "Founding Designer", meta: "Replicate · Remote, US/EU · $170k-$230k · 38m ago" },
    { score: 89, title: "Staff Product Designer, Observability", meta: "Vercel · Remote · $190k-$245k · 1h ago" },
    { score: 87, title: "Senior Product Designer, Billing UX", meta: "Stripe · Remote, US/CA/UK · $185k-$240k · 2h ago" },
    { score: 76, title: "Product Designer, Insights", meta: "Sentry · Remote · $150k-$190k · 10h ago" },
    { score: 71, title: "Senior Product Designer", meta: "Coda · Remote, US · $165k-$205k · 21h ago" },
  ];
  return (
    <>
      <div className="hp-mini-list-header hp-mono">
        <span>REST OF INBOX · 54</span>
        <span className="hp-faint">SORTED BY SCORE</span>
      </div>
      <div className="hp-mini-rows">
        {rows.map((r) => (
          <div key={r.title} className="hp-mini-row">
            <div className={`hp-mini-row-score hp-mono${r.score >= 80 ? " hp-accent-text" : ""}`}>
              {r.score}
            </div>
            <div>
              <div className="hp-mini-row-title">{r.title}</div>
              <div className="hp-mini-row-meta">{r.meta}</div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

/* ---------- How it works ---------- */
function HowItWorks() {
  const steps = [
    {
      num: "01",
      title: "Upload your resume. Set what you want.",
      body: (
        <>
          We read your resume once and pull out your roles, skills and level. Then you confirm a few
          things: the titles you want, where you can work, remote or office, and your salary floor. It
          takes a few minutes.
        </>
      ),
    },
    {
      num: "02",
      title: "The matcher sweeps every morning.",
      body: (
        <>
          Around six in the morning UTC, we check company careers pages and a set of job boards, score
          every new posting against your profile, and put them in your inbox. The best match comes first.
          The rest follow in score order.
        </>
      ),
    },
    {
      num: "03",
      title: "Apply without the busywork.",
      body: (
        <>
          When a job is worth it, press <em>Apply for me</em>. The app writes a resume for that job, reads
          the company&apos;s application form, answers what your profile already answers, and leaves the
          rest to you. You check everything before it goes. After you apply, it can find the hiring manager
          and draft a short note.
        </>
      ),
    },
  ];
  return (
    <section id="how" className="hp-how">
      <div className="hp-section-eyebrow hp-mono">
        <span className="hp-dot" />
        <span>HOW IT WORKS</span>
      </div>
      <h2 className="hp-section-title">Three steps to your first scored inbox.</h2>
      <p className="hp-section-lede">
        The product is a loop. The first half is the matcher; the second half is what you do with what it finds.
        Setup takes a few minutes, and your first scored matches show up straight away.
      </p>
      <ol className="hp-steps">
        {steps.map((s) => (
          <li key={s.num} className="hp-step">
            <span className="hp-step-num hp-mono">{s.num}</span>
            <div className="hp-step-body">
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

/* ---------- Scoring (the six parts of a score) ---------- */
function Scoring() {
  // What the scorer actually weighs (services/scoring/scorer.py). Salary and
  // sponsorship are filters, not parts of the score: see the note below.
  const axes = [
    { n: "01", title: "Title match", body: "How closely the job title matches the roles you want, including ones named differently at different companies." },
    { n: "02", title: "Skills overlap", body: "The skills on your resume against the ones the posting asks for." },
    { n: "03", title: "Seniority", body: "Your level against the level the posting is hiring for." },
    { n: "04", title: "Geo fit", body: "Where the job can hire from, against where you live and where you can work." },
    { n: "05", title: "Remote policy", body: "Remote, hybrid or in an office, against what you want." },
    { n: "06", title: "Industry", body: "The field the company works in, against the fields on your resume." },
  ];
  return (
    <section id="scoring" className="hp-scoring">
      <div className="hp-scoring-grid">
        <div className="hp-scoring-intro">
          <div className="hp-section-eyebrow hp-mono">
            <span className="hp-dot" />
            <span>THE MATCHER · 6 AXES</span>
          </div>
          <h2 className="hp-section-title">
            Other tools say <span className="hp-strike">good fit / not&nbsp;a&nbsp;fit</span>.<br />
            We say <em>why</em>.
          </h2>
          <p className="hp-section-lede">
            Every posting in your inbox carries a number out of a hundred and a breakdown across six axes.
            The number is the headline. The axes tell you what&apos;s driving it: where the job fits, where it
            falls short, and what&apos;s worth a conversation anyway.
          </p>
          <p className="hp-section-lede hp-faint">
            Salary and visa sponsorship aren&apos;t scored. They&apos;re filters: when a posting pays below your
            floor, or won&apos;t sponsor a visa you need, it never reaches your inbox.
          </p>
          <p className="hp-section-lede hp-faint">
            Scores follow fixed rules, so the same posting and the same profile always get the same number. You
            can rate jobs good or bad without seeing their scores, and we check the matcher against your ratings
            before we change it.
          </p>
        </div>
        <ul className="hp-axes">
          {axes.map((a) => (
            <li key={a.n} className="hp-axis">
              <span className="hp-axis-num hp-mono">{a.n}</span>
              <div>
                <h4>{a.title}</h4>
                <p>{a.body}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ---------- Founder note ---------- */
function FounderNote() {
  return (
    <section id="note" className="hp-note">
      <div className="hp-note-eyebrow">A NOTE FROM THE MAKER</div>
      <div className="hp-note-body">
        <p>
          I built this because I was the user. I&apos;d spent six weeks on LinkedIn, Indeed, and three
          aggregators trying to find roles that fit, and what I kept noticing was that <em>nothing
          was scoring anything</em>. The signal was there. Every posting carried enough structure to
          score against my resume, and no product was doing the work.
        </p>
        <p>
          So I built a private matcher for myself, started forwarding the inbox to friends, and the
          same thing happened to them: they stopped scrolling job boards. They opened one tab, read
          seven postings, and shut it. That&apos;s the product.
        </p>
        <p>
          It started in tech. It&apos;s now in finance, ops, marketing, design. The matcher doesn&apos;t care
          about your industry, just the structure underneath. If you&apos;re tired of the noise, write me.
        </p>
        <div className="hp-note-sig">
          <div className="hp-sig-name">Olalekan Oderinlo</div>
          <div className="hp-sig-meta hp-mono">Lagos · Maker, Job Hunt</div>
        </div>
      </div>
    </section>
  );
}

/* ---------- Invite card ---------- */
function Invite() {
  const stats: Array<{ n: string; l: string; accent?: boolean }> = [
    { n: "Free", l: "DURING BETA", accent: true },
    { n: "13", l: "JOB SOURCES" },
    { n: "6", l: "SCORING AXES" },
    { n: "06:00", l: "DAILY SWEEP · UTC" },
  ];
  return (
    <section id="invite" className="hp-invite">
      <div className="hp-invite-card">
        <div className="hp-invite-status">
          <span className="hp-dot hp-pulse" />
          <span className="hp-mono">STATUS · INVITE-ONLY · BETA</span>
        </div>
        <h2 className="hp-invite-title">
          Free during beta.<br />
          <span className="hp-dim">Pricing decided once the matcher&apos;s tuned.</span>
        </h2>
        <p className="hp-invite-lede">
          We&apos;re keeping it invite-only until the matcher&apos;s accuracy is somewhere we&apos;re proud of.
          If you write us, we read every reply. If you&apos;re the right fit, we send you a link the same week.
        </p>
        <InviteForm placeholder="your@email.com" formKey="invite" />
        <div className="hp-invite-meta">
          {stats.map((s) => (
            <div key={s.l} className="hp-invite-stat">
              <div className={`hp-invite-stat-n hp-mono${s.accent ? " hp-accent-text" : ""}`}>{s.n}</div>
              <div className="hp-invite-stat-l hp-mono">{s.l}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------- Footer ---------- */
function Footer() {
  return (
    <footer className="hp-footer">
      <div className="hp-footer-grid">
        <div className="hp-footer-brand">
          <Link href="/" className="hp-brand">
            <span className="hp-brand-mark">J</span>
            <span>Job Hunt</span>
          </Link>
          <p className="hp-footer-line">Invite-only. Made by Olalekan Oderinlo in Lagos.</p>
        </div>
        <div className="hp-footer-links">
          <a href="#invite" className="hp-footer-link">
            <span className="hp-mono hp-mono-accent">→</span>
            Request an invite
          </a>
        </div>
      </div>
      <div className="hp-footer-meta hp-mono">
        <span>v0.4 · beta</span>
        <span className="hp-faint">·</span>
        <span>Daily sweep 06:00 UTC</span>
        <span className="hp-faint">·</span>
        <span>13 sources</span>
      </div>
    </footer>
  );
}
