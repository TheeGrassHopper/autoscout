"use client";

import { useState } from "react";
import Link from "next/link";
import { apiForgotPassword } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await apiForgotPassword(email);
    } finally {
      setLoading(false);
      setSubmitted(true);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="text-2xl font-bold text-slate-900">AutoScout AI</div>
          <div className="text-sm text-slate-500 mt-1">Reset your password</div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          {submitted ? (
            <div className="text-center space-y-3">
              <div className="text-3xl">📬</div>
              <p className="text-sm text-slate-700 font-medium">Check your inbox</p>
              <p className="text-sm text-slate-500">
                If that email is registered, we sent a reset link. It expires in 1 hour.
              </p>
              <Link
                href="/login"
                className="block mt-4 text-sm text-slate-900 font-medium hover:underline"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <p className="text-sm text-slate-500">
                Enter your email and we'll send you a link to reset your password.
              </p>

              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-600">Email</label>
                <input
                  type="email"
                  required
                  autoFocus
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-slate-300"
                  placeholder="you@example.com"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-700 disabled:opacity-50 transition-colors"
              >
                {loading ? "Sending…" : "Send reset link"}
              </button>
            </form>
          )}
        </div>

        {!submitted && (
          <p className="text-center text-sm text-slate-500 mt-4">
            <Link href="/login" className="text-slate-900 font-medium hover:underline">
              Back to sign in
            </Link>
          </p>
        )}
      </div>
    </div>
  );
}
