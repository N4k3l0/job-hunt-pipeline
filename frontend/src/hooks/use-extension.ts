"use client";

import { useEffect, useState } from "react";
import { askExtension } from "@/lib/extension";

/** Whether the Job Hunt extension is installed: null while checking. */
export function useExtensionInstalled(): boolean | null {
  const [installed, setInstalled] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    // The extension also says hello when it loads, which can be after this page.
    const onMessage = (event: MessageEvent) => {
      if (event.source === window && event.data?.jobHunt === "from-extension" && event.data.type === "hello") {
        setInstalled(true);
      }
    };
    window.addEventListener("message", onMessage);
    askExtension("ping").then((reply) => {
      if (active) setInstalled((current) => current || Boolean(reply?.ok));
    });
    return () => {
      active = false;
      window.removeEventListener("message", onMessage);
    };
  }, []);

  return installed;
}
