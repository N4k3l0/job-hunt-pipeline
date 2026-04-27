"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

/**
 * Tiny page-load fade. Re-keys on path change so the inner content re-mounts
 * and replays the fade animation. Two-phase render avoids hydration mismatch:
 * we render the children plain on the server / first paint, then opt into the
 * animation only after mount.
 */
export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [animated, setAnimated] = useState(false);
  const lastPath = useRef(pathname);

  useEffect(() => {
    if (lastPath.current !== pathname) {
      lastPath.current = pathname;
    }
    setAnimated(true);
  }, [pathname]);

  return (
    <div key={pathname} className={animated ? "page-in" : ""}>
      {children}
    </div>
  );
}
