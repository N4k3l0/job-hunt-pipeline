"use client";

import { useState } from "react";
import { ChevronDown, CheckCircle2, Globe, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useUpdateProfile } from "@/hooks/use-api";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { COUNTRY_OPTIONS } from "@/lib/countries";

// "Worldwide" is a job preference, not a place someone lives.
const LIVING_OPTIONS = COUNTRY_OPTIONS.filter((c) => c.code !== "WW");

export function HomeCountrySelect({
  value,
  onChange,
  disabled,
}: {
  value: string | null;
  onChange: (code: string) => void;
  disabled?: boolean;
}) {
  const selected = LIVING_OPTIONS.find((c) => c.code === value);
  const groups = LIVING_OPTIONS.reduce<Record<string, typeof LIVING_OPTIONS>>((acc, c) => {
    (acc[c.group] ??= []).push(c);
    return acc;
  }, {});

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="outline" size="sm" disabled={disabled} aria-label="Country you live in">
            {selected ? selected.name : "Select a country"}
            <ChevronDown className="h-4 w-4" />
          </Button>
        }
      />
      <DropdownMenuContent align="start" className="max-h-[340px] overflow-y-auto w-[260px]">
        {Object.entries(groups).map(([group, items]) => (
          <div key={group} className="px-1">
            <div className="px-2 py-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
              {group}
            </div>
            {items.map((c) => (
              <DropdownMenuItem
                key={c.code}
                onClick={() => onChange(c.code)}
                className="flex items-center gap-2"
              >
                {c.code === value && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />}
                {c.name}
              </DropdownMenuItem>
            ))}
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const PROMPT_DISMISSED_KEY = "home-country-prompt-dismissed";

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(PROMPT_DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

/** Non-blocking bar asking an existing user where they live. */
export function HomeCountryPrompt() {
  const toast = useToast();
  const updateProfile = useUpdateProfile();
  const [country, setCountry] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(readDismissed);

  if (dismissed) return null;

  function dismiss() {
    try {
      window.localStorage.setItem(PROMPT_DISMISSED_KEY, "1");
    } catch {
      // Storage blocked; the prompt just returns next visit.
    }
    setDismissed(true);
  }

  async function save() {
    if (!country) return;
    try {
      await updateProfile.mutateAsync({ home_country: country });
      toast.success("Saved", { description: "Remote jobs you can't apply to from there are now hidden." });
    } catch (e) {
      toast.error("Couldn't save", { description: e instanceof Error ? e.message : "Try again in a moment." });
    }
  }

  return (
    <div
      className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3"
      style={{ borderColor: "var(--ds-line)", background: "var(--ds-bg-elev-1)" }}
    >
      <Globe className="h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-[200px] flex-1 text-sm">
        <span className="font-medium">Where do you live?</span>{" "}
        <span className="text-muted-foreground">
          Some remote jobs only hire in certain countries. We&apos;ll hide the ones that don&apos;t include yours.
        </span>
      </div>
      <HomeCountrySelect value={country} onChange={setCountry} />
      <Button size="sm" onClick={save} disabled={!country || updateProfile.isPending}>
        {updateProfile.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
      </Button>
      <Button size="sm" variant="ghost" onClick={dismiss} aria-label="Dismiss">
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
}
