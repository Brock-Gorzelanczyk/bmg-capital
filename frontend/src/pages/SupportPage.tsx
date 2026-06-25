import { useState } from "react";
import { BracketFrame, SectionLabel, BMGButton } from "@/components/design";
import { Mail, ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

const SUPPORT_EMAIL = "support@bmgcapital.io";
const MAILTO = `mailto:${SUPPORT_EMAIL}`;

const FAQ_ITEMS: { q: string; a: string }[] = [
  {
    q: "Account access",
    a: "Can't log in, password reset, or 2FA recovery — email us and we'll get you back in.",
  },
  {
    q: "Trading questions",
    a: "Questions about orders, fills, or how a specific strategy executes — we'll walk you through it.",
  },
  {
    q: "Billing",
    a: "Invoices, refunds, plan changes, or proration questions — we handle these directly.",
  },
  {
    q: "Bot configuration",
    a: "Tuning, allocation, or troubleshooting a specific bot's behavior — include the profile name in your email.",
  },
];

function FAQRow({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-t-dim last:border-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-3 py-3 text-left hover:bg-t-bg0/40 transition-colors px-4"
      >
        <span className="text-sm font-mono-t text-t-hi">{q}</span>
        {open ? (
          <ChevronDown size={14} className="text-t-faint shrink-0" />
        ) : (
          <ChevronRight size={14} className="text-t-faint shrink-0" />
        )}
      </button>
      {open && (
        <div className="px-4 pb-3 space-y-2">
          <p className="text-xs font-mono-t text-t-muted leading-relaxed">{a}</p>
          <a
            href={MAILTO}
            className="inline-flex items-center gap-1.5 text-[10px] font-mono-t uppercase tracking-[0.15em] text-[var(--bmg-green)] hover:underline"
          >
            <Mail size={11} /> Email support
          </a>
        </div>
      )}
    </div>
  );
}

export default function SupportPage() {
  return (
    <div className="min-h-full bg-t-bg0 px-4 py-6 md:py-10">
      <div className="max-w-2xl mx-auto space-y-6">
        <BracketFrame className="p-6 bg-t-bg1 border border-t-dim rounded-2xl">
          <div className="space-y-3">
            <SectionLabel>// SUPPORT</SectionLabel>
            <h1 className={cn("text-2xl font-bold font-mono-t text-t-hi tracking-tight")}>
              Need help?
            </h1>
            <p className="text-sm font-mono-t text-t-muted leading-relaxed">
              Email{" "}
              <a
                href={MAILTO}
                className="text-[var(--bmg-green)] hover:underline"
              >
                {SUPPORT_EMAIL}
              </a>{" "}
              — we respond within one business day.
            </p>
            <div className="pt-2">
              <a href={MAILTO}>
                <BMGButton variant="primary" size="md" type="button">
                  <Mail size={13} className="mr-2" />
                  Email Support
                </BMGButton>
              </a>
            </div>
          </div>
        </BracketFrame>

        <div className="bg-t-bg1 border border-t-dim rounded-2xl">
          <div className="px-4 py-3 border-b border-t-dim">
            <SectionLabel>// COMMON QUESTIONS</SectionLabel>
          </div>
          {FAQ_ITEMS.map((item) => (
            <FAQRow key={item.q} q={item.q} a={item.a} />
          ))}
        </div>

        <p className="text-[10px] font-mono-t text-t-faint text-center uppercase tracking-[0.15em]">
          // Self-serve help center coming later
        </p>
      </div>
    </div>
  );
}
