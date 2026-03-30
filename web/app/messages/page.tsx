"use client";

import { useEffect, useState } from "react";
import { type QueuedMessage, approveMessage, getMessageQueue, skipMessage } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

const CLASS_BADGE: Record<string, string> = {
  great: "bg-emerald-100 text-emerald-800",
  fair: "bg-amber-100 text-amber-800",
  poor: "bg-red-100 text-red-800",
};

const CLASS_BORDER: Record<string, string> = {
  great: "border-l-emerald-500",
  fair: "border-l-amber-400",
  poor: "border-l-red-400",
};

const CLASS_ICON: Record<string, string> = { great: "🔥", fair: "⚡", poor: "❌" };

function fmt(n?: number | null) {
  return n != null ? `$${n.toLocaleString()}` : "—";
}

function daysSince(dateStr?: string | null): string {
  if (!dateStr) return "";
  const ms = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(ms / 86400000);
  if (days === 0) return "today";
  if (days === 1) return "1 day ago";
  return `${days} days ago`;
}

type TabKey = "drafted" | "sent" | "all";

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
  const [expanded, setExpanded] = useState(false);

  const copyMessage = async () => {
    await navigator.clipboard.writeText(msg.message_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const borderClass = CLASS_BORDER[msg.deal_class] ?? "border-l-slate-300";

  return (
    <div className={`bg-white rounded-xl shadow-sm border border-gray-100 border-l-4 ${borderClass} overflow-hidden`}>
      {/* Compact header row */}
      <div className="px-4 md:px-5 py-3 flex items-start gap-3">
        {/* Left: meta */}
        <div className="flex-1 min-w-0 space-y-0.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${CLASS_BADGE[msg.deal_class]}`}>
              {CLASS_ICON[msg.deal_class]} {msg.deal_class}
            </span>
            <span className="text-sm font-semibold text-slate-900 truncate">
              {msg.year} {msg.make} {msg.model}
            </span>
          </div>
          <div className="text-xs text-slate-400 truncate">{msg.title}</div>
          {msg.location && (
            <div className="text-xs text-slate-400">{msg.location}</div>
          )}
        </div>

        {/* Right: price + savings */}
        <div className="text-right flex-shrink-0">
          <div className="text-base font-bold text-slate-900">{fmt(msg.asking_price)}</div>
          {msg.savings != null && (
            <div className={`text-xs font-medium ${msg.savings > 0 ? "text-emerald-600" : "text-red-500"}`}>
              {msg.savings > 0
                ? `▼ ${fmt(msg.savings)} below`
                : `▲ ${fmt(Math.abs(msg.savings))} above`}
            </div>
          )}
          {msg.kbb_value && (
            <div className="text-xs text-slate-400">KBB ~{fmt(msg.kbb_value)}</div>
          )}
        </div>
      </div>

      {/* Message text */}
      <div className="px-4 md:px-5 pb-3">
        <div
          className={`bg-gray-50 rounded-lg p-3 text-sm text-slate-700 leading-relaxed whitespace-pre-wrap ${
            expanded ? "" : "line-clamp-3"
          }`}
        >
          {msg.message_text}
        </div>
        {msg.message_text.length > 200 && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-xs text-blue-500 hover:text-blue-700 mt-1"
          >
            {expanded ? "Show less" : "Show more"}
          </button>
        )}
      </div>

      {/* Action row */}
      <div className="px-4 md:px-5 py-3 border-t border-gray-100 flex flex-wrap items-center gap-2">
        <a
          href={msg.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-slate-500 hover:text-slate-800 underline-offset-2 hover:underline"
        >
          View Listing ↗
        </a>

        <div className="flex-1" />

        <span className="text-xs text-slate-400">{daysSince(msg.drafted_at)}</span>

        <button
          onClick={copyMessage}
          className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg text-slate-600 hover:bg-gray-50 transition-colors"
        >
          {copied ? "✓ Copied" : "Copy"}
        </button>

        <button
          onClick={onSkip}
          className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg text-slate-500 hover:bg-gray-50 transition-colors"
        >
          Skip
        </button>

        <a
          href={msg.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onApprove}
          className="px-4 py-1.5 text-xs bg-emerald-600 text-white font-semibold rounded-lg hover:bg-emerald-500 transition-colors"
        >
          Send Message →
        </a>
      </div>
    </div>
  );
}

// ── Empty State ───────────────────────────────────────────────────────────────

function EmptyState({ tab }: { tab: TabKey }) {
  const content: Record<TabKey, { icon: string; title: string; subtitle: string }> = {
    drafted: {
      icon: "✍️",
      title: "No drafted messages",
      subtitle: "Run the pipeline to find deals and generate outreach messages.",
    },
    sent: {
      icon: "📤",
      title: "No sent messages yet",
      subtitle: "Approve a drafted message to mark it as sent.",
    },
    all: {
      icon: "💬",
      title: "No messages at all",
      subtitle: "Run the pipeline to find deals and generate messages.",
    },
  };
  const { icon, title, subtitle } = content[tab];
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-16 text-center">
      <div className="text-4xl mb-3">{icon}</div>
      <div className="text-slate-600 font-medium">{title}</div>
      <div className="text-slate-400 text-sm mt-1">{subtitle}</div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function MessagesPage() {
  const [messages, setMessages] = useState<QueuedMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const [activeTab, setActiveTab] = useState<TabKey>("drafted");

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
    setDismissed((prev) => new Set(Array.from(prev).concat(id)));
  };

  const handleSkip = async (id: number) => {
    await skipMessage(id);
    setDismissed((prev) => new Set(Array.from(prev).concat(id)));
  };

  const visible = messages.filter((m) => !dismissed.has(m.id));

  const draftedMessages = visible.filter(
    (m) => m.status === "pending" || m.status === "drafted"
  );
  const sentMessages = visible.filter(
    (m) => m.status === "approved" || m.status === "sent"
  );

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: "drafted", label: "Drafted", count: draftedMessages.length },
    { key: "sent", label: "Sent", count: sentMessages.length },
    { key: "all", label: "All", count: visible.length },
  ];

  const tabMessages: Record<TabKey, QueuedMessage[]> = {
    drafted: draftedMessages,
    sent: sentMessages,
    all: visible,
  };

  const currentMessages = tabMessages[activeTab];

  return (
    <div className="p-4 md:p-8 space-y-4 md:space-y-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Outreach Hub</h1>
          <p className="text-sm text-slate-500 mt-1">
            {visible.length} message{visible.length !== 1 ? "s" : ""} total
          </p>
        </div>
        <button
          onClick={load}
          className="px-4 py-2 text-sm border border-gray-200 bg-white rounded-lg text-slate-600 hover:bg-gray-50 transition-colors"
        >
          ↻ Refresh
        </button>
      </div>

      {/* Status tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-xl p-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === tab.key
                ? "bg-white shadow-sm text-slate-900"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab.label}
            <span className={`inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 rounded-full text-xs font-bold ${
              activeTab === tab.key
                ? "bg-slate-900 text-white"
                : "bg-slate-200 text-slate-600"
            }`}>
              {tab.count}
            </span>
          </button>
        ))}
      </div>

      {/* Content */}
      {loading ? (
        <div className="text-center py-16 text-slate-400 text-sm">Loading…</div>
      ) : currentMessages.length === 0 ? (
        <EmptyState tab={activeTab} />
      ) : (
        <div className="space-y-3">
          {currentMessages.map((msg) => (
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
