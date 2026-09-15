/**
 * Talking to the Job Hunt Chrome extension, which fills in application
 * forms. Its content script on this site answers window messages:
 * the page posts { jobHunt: "to-extension", requestId, type, ... } and gets
 * { jobHunt: "from-extension", requestId, ... } back. Without the
 * extension nothing answers, so every request has a timeout.
 */

import type { AutoApplyFill } from "@/lib/types";

type Reply = { ok?: boolean; error?: string; version?: string; type?: string };

export function askExtension(
  type: "ping" | "fill-form",
  extra: { application?: AutoApplyFill } = {},
  timeoutMs = 1500,
): Promise<Reply | null> {
  return new Promise((resolve) => {
    const requestId = Math.random().toString(36).slice(2);
    const finish = (reply: Reply | null) => {
      window.removeEventListener("message", onMessage);
      clearTimeout(timer);
      resolve(reply);
    };
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window || event.data?.jobHunt !== "from-extension") return;
      if (event.data.requestId === requestId) finish(event.data);
    };
    const timer = setTimeout(() => finish(null), timeoutMs);
    window.addEventListener("message", onMessage);
    window.postMessage({ jobHunt: "to-extension", requestId, type, ...extra }, window.location.origin);
  });
}
