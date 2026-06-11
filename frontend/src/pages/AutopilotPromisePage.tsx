import { Link } from "react-router-dom";
import {
  Eye,
  RotateCcw,
  SlidersHorizontal,
  Shield,
  Bell,
  MessageCircleOff,
  FileText,
  Moon,
  Scale,
  Lock,
  ArrowRight,
} from "lucide-react";

const PRINCIPLES = [
  {
    number: 1,
    title: "Transparency",
    icon: Eye,
    body: "Every automated action has a plain-English rationale. No black boxes.",
  },
  {
    number: 2,
    title: "Reversibility",
    icon: RotateCcw,
    body: "Where physically possible, every action is reversible. Paper trades can be reverted; real money transfers cannot.",
  },
  {
    number: 3,
    title: "User Control",
    icon: SlidersHorizontal,
    body: "Every automation is tunable, pauseable, and kill-switchable. You're always in control.",
  },
  {
    number: 4,
    title: "Guardrails",
    icon: Shield,
    body: "Hard limits protect you and can't be disabled — only tightened. No automation can exceed your risk limits.",
  },
  {
    number: 5,
    title: "No Surprises",
    icon: Bell,
    body: "Your daily digest + in-app feed provide a complete picture every day. Nothing happens silently.",
  },
  {
    number: 6,
    title: "No Advice",
    icon: MessageCircleOff,
    body: "BMG executes your rules. It doesn't tell you what to do. Every automation reflects choices you made.",
  },
  {
    number: 7,
    title: "Audit Trail",
    icon: FileText,
    body: "A complete, permanent, exportable log of every action. You own your data.",
  },
  {
    number: 8,
    title: "Quiet Hours",
    icon: Moon,
    body: "Notifications absolutely respect your quiet hours (9PM–7AM by default). Guardrail trips are the only exception.",
  },
  {
    number: 9,
    title: "Compliance",
    icon: Scale,
    body: "Every automated action is checked against regulatory rules before execution. Pattern day trader detection, wash-sale prevention built in.",
  },
  {
    number: 10,
    title: "Privacy",
    icon: Lock,
    body: "AI rationale is generated using only your data. We never use other users' information to reason about your account.",
  },
];

const IN_PRACTICE = [
  "Every action has plain-English rationale",
  "Every action is reversible where physically possible",
  "Global kill switch always 1 tap away",
  "Hard guardrails can only be tightened, never removed",
  "Morning digest = full picture, every day",
  "AI rationale never invented — references real data",
  "Quiet hours: 9PM–7AM, absolutely respected",
  "Complete audit log, exportable, permanent",
  "Every action checked against regulatory rules",
  "AI rationale never sees other users' data",
];

export default function AutopilotPromisePage() {
  return (
    <div className="pb-16 max-w-4xl mx-auto space-y-12">

      {/* Hero */}
      <div className="text-center pt-6 space-y-3">
        <div className="inline-flex items-center gap-2 bg-[#4ade80]/10 border border-[#4ade80]/20 text-[#4ade80] text-xs px-3 py-1 rounded-full font-semibold tracking-wide uppercase">
          <Shield size={12} />
          Ethical Principles
        </div>
        <h1 className="text-4xl font-bold text-[var(--text-primary)] tracking-tight">
          The BMG Autonomy Promise
        </h1>
        <p className="text-[var(--text-tertiary)] text-base max-w-lg mx-auto">
          Every automated action. Total transparency.
        </p>
      </div>

      {/* Principles grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {PRINCIPLES.map(({ number, title, icon: Icon, body }) => (
          <div
            key={number}
            className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-5 flex gap-4 group hover:border-[#4ade80]/30 transition-colors duration-200"
          >
            {/* Number */}
            <div className="shrink-0 w-10 text-right">
              <span className="font-mono text-4xl font-bold text-[#4ade80] leading-none">
                {number}
              </span>
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1.5">
                <Icon size={16} className="text-[#4ade80] shrink-0" />
                <span className="text-[var(--text-primary)] font-semibold text-sm">
                  {title}
                </span>
              </div>
              <p className="text-[var(--text-tertiary)] text-sm leading-relaxed">
                {body}
              </p>
            </div>
          </div>
        ))}
      </div>

      {/* What this means in practice */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-[var(--border-subtle)]">
          <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">
            What this means in practice
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-0 divide-y md:divide-y-0 md:divide-x divide-[var(--border-subtle)]">
          {[0, 1, 2].map((col) => (
            <ul key={col} className="px-6 py-5 space-y-3">
              {IN_PRACTICE.slice(
                col * Math.ceil(IN_PRACTICE.length / 3),
                col === 2
                  ? undefined
                  : (col + 1) * Math.ceil(IN_PRACTICE.length / 3)
              ).map((item) => (
                <li key={item} className="flex items-start gap-2.5">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#4ade80] shrink-0" />
                  <span className="text-[var(--text-secondary)] text-sm leading-snug">
                    {item}
                  </span>
                </li>
              ))}
            </ul>
          ))}
        </div>
      </div>

      {/* Activity log CTA */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-6 py-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <p className="text-[var(--text-primary)] font-semibold text-sm mb-1">
            Not just words — see every action BMG has taken for you
          </p>
          <p className="text-[var(--text-tertiary)] text-xs">
            A permanent, exportable record of every automation, every rationale, every outcome.
          </p>
        </div>
        <Link
          to="/autopilot/activity"
          className="shrink-0 inline-flex items-center gap-2 px-4 py-2 bg-[#4ade80]/10 hover:bg-[#4ade80]/20 border border-[#4ade80]/30 text-[#4ade80] text-sm font-semibold rounded-lg transition-colors"
        >
          View your activity log
          <ArrowRight size={14} />
        </Link>
      </div>

      {/* Footer note */}
      <p className="text-center text-[var(--text-tertiary)] text-xs">
        These principles are the foundation of BMG's autonomous engine.{" "}
        <Link
          to="/autopilot/activity"
          className="text-[#4ade80] hover:underline"
        >
          View your activity log →
        </Link>
      </p>
    </div>
  );
}
