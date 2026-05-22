"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Send } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { env } from "@/lib/env";
import { nextBackoff, shouldRetry } from "@/lib/reconnect";
import type { ChatMessageOut } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";

type Frame =
  | { type: "message"; data: ChatMessageOut }
  | { type: "presence"; data: { online: string[] } }
  | { type: "typing"; data: { user_id: string; active: boolean } }
  | { type: "error"; data: { code: string; message: string } };

type ConnState = "connecting" | "open" | "reconnecting" | "closed";

export function ChatRoom({ courseId, token }: { courseId: string; token: string | null }) {
  const t = useT();
  const [messages, setMessages] = useState<ChatMessageOut[]>([]);
  const [draft, setDraft] = useState("");
  const [state, setState] = useState<ConnState>("connecting");
  const [online, setOnline] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const url = useMemo(() => {
    if (!token) return null;
    return `${env.WS_BASE_URL}/api/v1/chat/ws/${courseId}?token=${encodeURIComponent(token)}`;
  }, [courseId, token]);

  useEffect(() => {
    if (!url) {
      setState("closed");
      return;
    }
    let cancelled = false;
    let attempt = 0;
    let retryHandle: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (cancelled) return;
      setState(attempt === 0 ? "connecting" : "reconnecting");
      const ws = new WebSocket(url!);
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) {
          ws.close();
          return;
        }
        attempt = 0;
        setState("open");
      };
      ws.onmessage = (evt) => {
        try {
          const frame = JSON.parse(evt.data) as Frame;
          if (frame.type === "message") {
            setMessages((m) => [...m, frame.data]);
          } else if (frame.type === "presence") {
            setOnline(frame.data.online);
          }
        } catch {
          // swallow malformed frames
        }
      };
      ws.onclose = (evt) => {
        wsRef.current = null;
        if (cancelled) return;
        if (!shouldRetry(evt.code)) {
          setState("closed");
          return;
        }
        const delay = nextBackoff(attempt);
        attempt += 1;
        setState("reconnecting");
        retryHandle = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (retryHandle) clearTimeout(retryHandle);
      wsRef.current?.close();
    };
  }, [url]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length]);

  function send() {
    if (!draft.trim() || wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: "message", data: { body: draft } }));
    setDraft("");
  }

  const connected = state === "open";
  const statusLabel =
    state === "open"
      ? t("chat.connected", { n: online.length })
      : state === "reconnecting"
        ? t("chat.reconnecting")
        : state === "connecting"
          ? t("chat.connecting")
          : t("chat.disconnected");

  return (
    <div className="flex h-full flex-col">
      <div
        className={`flex items-center gap-2 border-b border-border/60 px-4 py-2 font-body text-xs ${
          connected ? "text-muted-foreground" : "text-destructive"
        }`}
        aria-live="polite"
      >
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            connected
              ? "bg-primary shadow-[0_0_6px_hsl(var(--primary)/0.5)]"
              : state === "reconnecting" || state === "connecting"
                ? "animate-pulse bg-primary/60"
                : "bg-destructive"
          }`}
          aria-hidden
        />
        {statusLabel}
      </div>
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="pt-10 text-center">
            <p className="font-display text-lg italic text-muted-foreground">{t("chat.empty")}</p>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className="flex gap-2">
            <Avatar className="h-7 w-7 border border-border/60">
              <AvatarImage src={m.author.avatar_url ?? undefined} alt={m.author.full_name} />
              <AvatarFallback>{m.author.full_name.slice(0, 1).toUpperCase()}</AvatarFallback>
            </Avatar>
            <div className="rounded-md border border-border/60 bg-card/60 px-3 py-2 text-sm">
              <div className="font-display text-xs font-medium text-primary">
                {m.author.full_name}
              </div>
              <p className="whitespace-pre-wrap font-body text-foreground/90">{m.body}</p>
            </div>
          </div>
        ))}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="flex gap-2 border-t border-border/60 p-3"
      >
        <Input
          placeholder={t("chat.placeholder")}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          maxLength={4000}
          aria-label={t("chat.messageAria")}
        />
        <Button
          type="submit"
          size="icon"
          aria-label={t("chat.send")}
          disabled={!connected || !draft.trim()}
        >
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}
