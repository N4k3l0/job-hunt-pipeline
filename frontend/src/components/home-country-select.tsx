"use client";

import { ChevronDown, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
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
