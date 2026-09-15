"use client";

import { useState } from "react";
import { Briefcase, GraduationCap, Loader2, Pencil, Plus, X } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import {
  useAddSkill, useDeleteSkill, useDeleteWorkHistory, useSaveWorkHistory, useSkills, useWorkHistory,
  type WorkHistoryInput,
} from "@/hooks/use-api";
import type { SkillCategory, WorkHistoryEntry } from "@/lib/types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthLabel(iso: string | null) {
  if (!iso) return null;
  const [year, month] = iso.split("-");
  return `${MONTHS[Number(month) - 1] ?? ""} ${year}`.trim();
}

const toMonthInput = (iso: string | null) => (iso ? iso.slice(0, 7) : "");
const fromMonthInput = (value: string) => (value ? `${value}-01` : null);

const errorText = (e: unknown) => (e instanceof Error ? e.message : undefined);

const fieldStyle =
  "block w-full rounded-md border border-white/[0.08] bg-transparent px-3 py-2 text-sm focus:border-[var(--ds-accent-edge)] focus:outline-none";

function RoleForm({
  entry,
  onDone,
  onChanged,
}: {
  entry?: WorkHistoryEntry;
  onDone: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const save = useSaveWorkHistory();
  const [title, setTitle] = useState(entry?.title ?? "");
  const [company, setCompany] = useState(entry?.company ?? "");
  const [start, setStart] = useState(toMonthInput(entry?.start_date ?? null));
  const [end, setEnd] = useState(toMonthInput(entry?.end_date ?? null));
  const [current, setCurrent] = useState(entry ? !entry.end_date : false);
  const [highlights, setHighlights] = useState((entry?.bullets ?? []).join("\n"));

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const data: WorkHistoryInput = {
      title: title.trim(),
      company: company.trim(),
      start_date: fromMonthInput(start),
      end_date: current ? null : fromMonthInput(end),
      bullets: highlights.split("\n").map((line) => line.trim()).filter(Boolean),
    };
    save.mutate(
      { id: entry?.id, data },
      {
        onSuccess: () => {
          toast.success(entry ? "Role updated" : "Role added");
          onChanged();
          onDone();
        },
        onError: (e) => toast.error("Couldn't save this role", { description: errorText(e) }),
      },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg border border-white/[0.08] p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="role-title">Job title</Label>
          <Input id="role-title" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={255} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="role-company">Company</Label>
          <Input id="role-company" value={company} onChange={(e) => setCompany(e.target.value)} required maxLength={255} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="role-start">Started</Label>
          <input id="role-start" type="month" value={start} onChange={(e) => setStart(e.target.value)} className={fieldStyle} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="role-end">Ended</Label>
          <input
            id="role-end"
            type="month"
            value={current ? "" : end}
            onChange={(e) => setEnd(e.target.value)}
            disabled={current}
            className={fieldStyle}
          />
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input type="checkbox" checked={current} onChange={(e) => setCurrent(e.target.checked)} />
            I work here now
          </label>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="role-highlights">What you did</Label>
        <textarea
          id="role-highlights"
          value={highlights}
          onChange={(e) => setHighlights(e.target.value)}
          rows={4}
          placeholder="One achievement per line"
          className={`${fieldStyle} resize-y`}
        />
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={save.isPending}>
          {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          {entry ? "Save changes" : "Add role"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

function RoleRow({ entry, onChanged }: { entry: WorkHistoryEntry; onChanged: () => void }) {
  const toast = useToast();
  const remove = useDeleteWorkHistory();
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);

  if (editing) return <RoleForm entry={entry} onDone={() => setEditing(false)} onChanged={onChanged} />;

  const dates = [monthLabel(entry.start_date), entry.end_date ? monthLabel(entry.end_date) : "Present"]
    .filter(Boolean)
    .join(" — ");

  return (
    <div className="rounded-lg border border-white/[0.06] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-sm font-semibold">{entry.title}</h4>
          <p className="text-sm text-muted-foreground">{entry.company}</p>
          {(entry.start_date || entry.end_date) && <p className="mt-0.5 text-xs text-muted-foreground">{dates}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {confirming ? (
            <>
              <span className="text-xs text-muted-foreground">Remove this role?</span>
              <Button
                size="sm"
                variant="outline"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(entry.id, {
                    onSuccess: () => {
                      toast.success("Role removed");
                      onChanged();
                    },
                    onError: (e) => toast.error("Couldn't remove this role", { description: errorText(e) }),
                  })
                }
              >
                Remove
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>Keep</Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="ghost" onClick={() => setEditing(true)} aria-label={`Edit ${entry.title}`}>
                <Pencil className="h-3.5 w-3.5" /> Edit
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(true)} aria-label={`Remove ${entry.title}`}>
                <X className="h-3.5 w-3.5" />
              </Button>
            </>
          )}
        </div>
      </div>
      {entry.bullets && entry.bullets.length > 0 && (
        <ul className="mt-2 space-y-1">
          {entry.bullets.map((b, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-foreground/70">
              <span className="mt-0.5 shrink-0 text-muted-foreground">-</span>
              {b}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function WorkHistoryCard({ onChanged }: { onChanged: () => void }) {
  const { data: workHistory } = useWorkHistory();
  const [adding, setAdding] = useState(false);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GraduationCap className="h-5 w-5" />
          Work History
        </CardTitle>
        <CardDescription>
          Read from your resume. Fix anything it got wrong: your most recent role sets the level of jobs you&apos;re
          matched with.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {(workHistory ?? []).map((entry) => (
          <RoleRow key={entry.id} entry={entry} onChanged={onChanged} />
        ))}
        {!workHistory?.length && !adding && (
          <p className="py-2 text-center text-sm text-muted-foreground">No roles yet. Upload a resume or add one.</p>
        )}
        {adding ? (
          <RoleForm onDone={() => setAdding(false)} onChanged={onChanged} />
        ) : (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            <Plus className="h-4 w-4" /> Add a role
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

const CATEGORIES: { value: SkillCategory; label: string }[] = [
  { value: "technical", label: "Technical" },
  { value: "tool", label: "Tool" },
  { value: "domain", label: "Industry" },
  { value: "soft", label: "Soft skill" },
];

export function SkillsCard({ onChanged }: { onChanged: () => void }) {
  const toast = useToast();
  const { data: skills } = useSkills();
  const add = useAddSkill();
  const remove = useDeleteSkill();
  const [name, setName] = useState("");
  const [category, setCategory] = useState<SkillCategory>("technical");

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const skill_name = name.trim();
    if (!skill_name) return;
    add.mutate(
      { skill_name, category },
      {
        onSuccess: () => {
          setName("");
          onChanged();
        },
        onError: (e) => toast.error("Couldn't add this skill", { description: errorText(e) }),
      },
    );
  };

  const groups = CATEGORIES.map((c) => ({ ...c, skills: (skills ?? []).filter((s) => s.category === c.value) }));
  const uncategorized = (skills ?? []).filter((s) => !CATEGORIES.some((c) => c.value === s.category));
  if (uncategorized.length) groups.push({ value: "technical", label: "Other", skills: uncategorized });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Briefcase className="h-5 w-5" />
          Skills
        </CardTitle>
        <CardDescription>Jobs are matched against these. Remove any that are wrong, and add what&apos;s missing.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!skills?.length && <p className="text-sm text-muted-foreground">No skills yet. Upload a resume or add them here.</p>}
        {groups.map((group) =>
          group.skills.length ? (
            <div key={group.label}>
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">{group.label}</p>
              <div className="flex flex-wrap gap-1.5">
                {group.skills.map((s) => (
                  <Badge key={s.id} variant="secondary" className="gap-1 pr-1 text-xs">
                    {s.skill_name}
                    <button
                      type="button"
                      aria-label={`Remove ${s.skill_name}`}
                      disabled={remove.isPending}
                      onClick={() =>
                        remove.mutate(s.id, {
                          onSuccess: onChanged,
                          onError: (e) => toast.error("Couldn't remove this skill", { description: errorText(e) }),
                        })
                      }
                      className="rounded p-0.5 opacity-60 hover:bg-white/[0.08] hover:opacity-100"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            </div>
          ) : null,
        )}
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Add a skill, e.g. Python"
            maxLength={255}
            className="max-w-xs"
            aria-label="Skill name"
          />
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as SkillCategory)}
            aria-label="Skill type"
            className="h-9 rounded-md border border-white/[0.08] bg-transparent px-2 text-sm"
          >
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
          <Button type="submit" size="sm" disabled={add.isPending || !name.trim()}>
            {add.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
