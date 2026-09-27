"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function Connect() {
  const code = useSearchParams().get("code") ?? "";
  const [state, setState] = useState<"idle" | "working" | "done" | "error">("idle");
  const [message, setMessage] = useState("");
  const [grants, setGrants] = useState<Array<{ id: string; created_at: string; last_used_at: string }>>([]);

  async function refreshGrants() {
    const res = await fetch("/api/extension/pair/grants", { credentials: "same-origin" });
    if (res.ok) setGrants(await res.json());
  }

  useEffect(() => {
    let active = true;
    fetch("/api/extension/pair/grants", { credentials: "same-origin" })
      .then((res) => res.ok ? res.json() : [])
      .then((rows) => { if (active) setGrants(rows); });
    return () => { active = false; };
  }, []);

  async function approve() {
    setState("working");
    try {
      const res = await fetch("/api/extension/pair/approve", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_code: code }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Could not connect the extension");
      }
      setState("done");
      // The extension receives its credential when it polls; give that a moment.
      setTimeout(() => void refreshGrants(), 1500);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Connection failed");
      setState("error");
    }
  }

  async function revoke(id: string) {
    const res = await fetch(`/api/extension/pair/grants/${id}`, { method: "DELETE", credentials: "same-origin" });
    if (res.ok) await refreshGrants();
    else setMessage("Could not disconnect that extension");
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 py-12">
      {!code && (
        <Card>
          <CardHeader><CardTitle>Install the Applination extension</CardTitle></CardHeader>
          <CardContent className="space-y-5">
            <p>Download the current test version and install it in Chrome. You only need to do this once on each computer. Download a new ZIP when a newer version is available.</p>
            <a className={buttonVariants()} href="/api/extension/download" download>Download extension ZIP</a>
            <ol className="list-decimal space-y-2 pl-5">
              <li>Extract the ZIP. Keep the extracted <strong>applination-extension</strong> folder somewhere you will not delete it.</li>
              <li>Open <strong>chrome://extensions</strong> in Chrome and turn on <strong>Developer mode</strong>.</li>
              <li>Choose <strong>Load unpacked</strong> and select the extracted <strong>applination-extension</strong> folder, which contains <strong>manifest.json</strong>.</li>
              <li>Pin <strong>Applination Autofill</strong>, open its popup, and choose <strong>Connect account</strong>.</li>
              <li>Approve the pairing code on the Applination page that opens. Then open a job application. The extension detects its fields; choose <strong>Autofill application</strong> to generate a tailored resume and fill the form.</li>
            </ol>
            <p className="text-sm text-muted-foreground">For updates, download and extract the new ZIP over the same folder, then click Reload on chrome://extensions. Chrome does not update manually installed extensions automatically.</p>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader><CardTitle>{code ? "Connect the Applination extension" : "Connected extensions"}</CardTitle></CardHeader>
        <CardContent className="space-y-5">
          {!code ? (
            <p>After installing, choose <strong>Connect account</strong> in the extension popup. Your active connections appear below.</p>
          ) : state === "done" ? (
            <p>Connected. Return to the application tab and open the extension.</p>
          ) : (
            <>
              <p>The extension is requesting access to your application profile and saved answers. It can generate a tailored resume, fill the form, and track applications using your configured AI provider.</p>
              <p className="font-mono text-lg tracking-widest">{code || "No pairing code"}</p>
              <p>Only approve if you started this connection from the Applination extension.</p>
              {state === "error" && <p role="alert" className="text-destructive">{message}</p>}
              <Button onClick={approve} disabled={!/^[A-F0-9]{10}$/.test(code) || state === "working"}>
                {state === "working" ? "Connecting…" : "Connect extension"}
              </Button>
            </>
          )}
          {grants.length > 0 && (
            <div className="space-y-3 border-t pt-5">
              <h2 className="font-semibold">Connected extensions</h2>
              {grants.map((grant) => (
                <div key={grant.id} className="flex items-center justify-between gap-3 text-sm">
                  <span>Connected {new Date(grant.created_at).toLocaleDateString()} · Last used {new Date(grant.last_used_at).toLocaleDateString()}</span>
                  <Button variant="outline" size="sm" onClick={() => revoke(grant.id)}>Disconnect</Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function ExtensionConnectPage() {
  return <Suspense><Connect /></Suspense>;
}
