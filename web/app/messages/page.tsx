"use client";

import { useEffect, useState } from "react";
import { type QueuedMessage, approveMessage, getMessageQueue, skipMessage } from "@/lib/api";

const CLASS_BADGE: Record<string, string> = {
  great: "bg-emerald-100 text-emerald-800",
  fair: "bg-amber-100 text-amber-800",
  poor: "bg-red-100 text-red-800",
};
const CLASS_ICON: Record<string, string> = { great: "🔥", fair: "⚡", poor: "❌" };

function fmt(n?: number | null) {
  return n != null ? `$${n.toLocaleString()}` : "—";
}

// ── Message Card ──────────────────────────────────────────────────────────────

function MessageCard({
  msg,
  onApprove,
  onSkip,
}: {
  msg: QueuedMessage;
  onApprove: () => void;
  onSkip: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const copyMessage = async () => {
    await navigator.clipboard.writeText(msg.message_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${CLASS_BADGE[msg.deal_class]}`}>
              {CLASS_ICON[msg.deal_class]} {msg.total_score}/100
            </span>
            <span className="text-xs text-slate-400">{msg.year} {msg.make} {msg.model}</span>
          </div>
          <div className="font-semibold text-slate-900 truncate">{msg.title}</div>
          <div className="text-xs text-slate-400 mt-0.5">{msg.location}</div>
        </div>
        <div className="text-right flex-shrink-0">
          <div className="text-xl font-bold text-slate-900">{fmt(msg.asking_price)}</div>
          {msg.kbb_value && (
            <div className="text-xs text-slate-400">KBB ~{fmt(msg.kbb_value)}</div>
          )}
          {msg.savings != null && (
            <div className={`text-xs font-medium ${msg.savings > 0 ? "text-emerald-600" : "text-red-500"}`}>
              {msg.savings > 0 ? `▼ ${fmt(msg.savings)} below` : `▲ ${fmt(Math.abs(msg.savings))} above`}
            </div>
          )}
        </div>
      </div>

      {/* Message body */}
      <div className="px-6 py-4">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
          Drafted Message
        </div>
        <div className="bg-gray-50 rounded-lg p-4 text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
          {msg.message_text}
        </div>
      </div>

      {/* Actions */}
      <div className="px-6 py-4 border-t border-gray-100 flex items-center gap-3">
        <a
          href={msg.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-slate-500 hover:text-slate-800 underline-offset-2 hover:underline"
        >
          View Listing ↗
        </a>

        <div className="flex-1" />

        <button
          onClick={copyMessage}
          className="px-4 py-2 text-sm border border-gray-200 rounded-lg text-slate-600 hover:bg-gray-50 transition-colors"
        >
          {copied ? "✓ Copied!" : "Copy Message"}
        </button>

        <button
          onClick={onSkip}
          className="px-4 py-2 text-sm border border-gray-200 rounded-lg text-slate-500 hover:bg-gray-50 transition-colors"
        >
          Skip
        </button>

        <a
          href={msg.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onApprove}
          className="px-5 py-2 text-sm bg-emerald-600 text-white font-medium rounded-lg hover:bg-emerald-500 transition-colors"
        >
          Send Message ↗
        </a>
      </div>

      <div className="px-6 pb-3 text-xs text-slate-400">
        Drafted {new Date(msg.drafted_at).toLocaleString()}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function MessagesPage() {
  const [messages, setMessages] = useState<QueuedMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());

  const load = async () => {
    setLoading(true);
    try {
      const data = await getMessageQueue();
      setMessages(data);
    } catch {}
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, []);

  const handleApprove = async (id: number) => {
    await approveMessage(id);
    setDismissed((prev) => new Set([...prev, id]));
  };

  const handleSkip = async (id: number) => {
    await skipMessage(id);
    setDismissed((prev) => new Set([...prev, id]));
  };

  const visible = messages.filter((m) => !dismissed.has(m.id));

  return (
    <div className="p-8 space-y-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Message Queue</h1>
          <p className="text-sm text-slate-500 mt-1">
            {visible.length} message{visible.length !== 1 ? "s" : ""} waiting for review
          </p>
        </div>
        <button
          onClick={load}
          className="px-4 py-2 text-sm border border-gray-200 bg-white rounded-lg text-slate-600 hover:bg-gray-50 transition-colors"
        >
          ↻ Refresh
        </button>
      </div>

      {loading ? (
        <div className="text-center py-16 text-slate-400 text-sm">Loading…</div>
      ) : visible.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-16 text-center">
          <div className="text-4xl mb-3">💬</div>
          <div className="text-slate-600 font-medium">No messages in queue</div>
          <div className="text-slate-400 text-sm mt-1">
            Run the pipeline to find deals and generate messages.
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {visible.map((msg) => (
            <MessageCard
              key={msg.id}
              msg={msg}
              onApprove={() => handleApprove(msg.id)}
              onSkip={() => handleSkip(msg.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
