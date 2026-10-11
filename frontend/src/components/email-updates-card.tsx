"use client";

import { useState } from "react";
import { Bell, Eye, Loader2, Send } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import {
  useDigestPreview, useNotificationSettings, useSendTestDigest, useSetDigestForEveryone, useUpdateNotificationSettings,
} from "@/hooks/use-api";

// Matches the backend's DIGEST_HOUR_UTC default.
const SEND_HOUR_UTC = 7;

function localSendTime() {
  const when = new Date();
  when.setUTCHours(SEND_HOUR_UTC, 0, 0, 0);
  return when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function EmailUpdatesCard() {
  const toast = useToast();
  const { data: settings, isLoading } = useNotificationSettings();
  const update = useUpdateNotificationSettings();
  const forEveryone = useSetDigestForEveryone();
  const sendTest = useSendTestDigest();
  const [previewOpen, setPreviewOpen] = useState(false);
  const preview = useDigestPreview(previewOpen);

  const on = settings?.daily_email ?? false;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bell className="h-5 w-5" />
          Daily email
        </CardTitle>
        <CardDescription>
          Every morning, your best new matches, applications that need your answers, and follow-ups that are due. No
          email on days with nothing new.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading || !settings ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <>
            <label className="flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                role="switch"
                checked={on}
                disabled={update.isPending}
                onChange={(e) =>
                  update.mutate(e.target.checked, {
                    onSuccess: (data) =>
                      toast.success(data.daily_email ? "Daily email is on" : "Daily email is off"),
                    onError: (err) =>
                      toast.error("Couldn't save", { description: err instanceof Error ? err.message : undefined }),
                  })
                }
                className="h-4 w-4 accent-[var(--ds-accent)]"
              />
              <span className="text-sm">
                {on ? (
                  <>
                    Send it to <strong>{settings.email}</strong> around {localSendTime()} your time
                  </>
                ) : (
                  "Off"
                )}
              </span>
            </label>

            {!settings.email_configured && (
              <p className="text-xs text-muted-foreground">
                {settings.everyone === undefined
                  ? "Emails start once sending is set up for the app. Your setting is saved until then."
                  : "Set up LinkedIn job alerts below first: the same Gmail script sends this email."}
              </p>
            )}
            {settings.sends_from && (
              <p className="text-xs text-muted-foreground">
                It comes from {settings.sends_from}, sent by the Gmail script that reads your LinkedIn alerts.
              </p>
            )}
            {settings.everyone !== undefined && (
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  role="switch"
                  checked={settings.everyone}
                  disabled={forEveryone.isPending}
                  onChange={(e) =>
                    forEveryone.mutate(e.target.checked, {
                      onSuccess: (data) =>
                        toast.success(data.everyone ? "Every user gets it now" : "Only you get it now"),
                      onError: (err) =>
                        toast.error("Couldn't save", { description: err instanceof Error ? err.message : undefined }),
                    })
                  }
                  className="mt-0.5 h-4 w-4 accent-[var(--ds-accent)]"
                />
                <span className="text-sm">
                  Send it to every user
                  <span className="block text-xs text-muted-foreground">
                    {settings.everyone
                      ? "Everyone who has it switched on gets it."
                      : "Off while you try it: until you turn this on, only you get it."}
                  </span>
                </span>
              </label>
            )}

            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => setPreviewOpen(true)}>
                <Eye className="h-4 w-4" /> Preview today&apos;s email
              </Button>
              {settings.email_configured && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={sendTest.isPending}
                  onClick={() =>
                    sendTest.mutate(undefined, {
                      onSuccess: ({ sent_to, queued }) =>
                        queued
                          ? toast.success("Test email on its way", {
                              description: `Your Gmail script sends it to ${sent_to} within about 10 minutes.`,
                            })
                          : toast.success(`Test email sent to ${sent_to}`),
                      onError: (err) =>
                        toast.error("Couldn't send the test email", {
                          description: err instanceof Error ? err.message : undefined,
                        }),
                    })
                  }
                >
                  {sendTest.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  {settings.test_waiting ? "Test on its way" : "Send me a test"}
                </Button>
              )}
            </div>
          </>
        )}
      </CardContent>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="sm:max-w-[640px]">
          <DialogHeader>
            <DialogTitle>{preview.data?.subject ?? "Today's email"}</DialogTitle>
            <DialogDescription>
              {preview.data?.empty
                ? "Nothing new right now, so no email would go out today. This is what it looks like."
                : "What today's email would say if it went out now."}
            </DialogDescription>
          </DialogHeader>
          {preview.isLoading ? (
            <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : preview.isError ? (
            <p className="text-sm text-destructive">Couldn&apos;t load the preview.</p>
          ) : (
            <iframe
              title="Email preview"
              srcDoc={preview.data?.html}
              sandbox=""
              className="h-[60vh] w-full rounded-md border border-white/[0.08] bg-white"
            />
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
