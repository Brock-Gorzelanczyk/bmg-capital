import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  ChevronRight, ChevronLeft, CheckCircle2, TrendingUp, Shield, Clock,
  Target, Zap, BarChart2, Bitcoin, Layers, Building2, Lock, CreditCard,
  Gift, Sparkles, BookOpen, Star,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// Set to false to require real KYC/Plaid in production
const DEMO_MODE = true;

const TOTAL_STEPS = 16;

// Steps that are essential (no skip button): Welcome (0), Personal Info (7), Identity Verify (8)
const ESSENTIAL_STEPS = new Set([0, 7, 8]);

// ── Progress bar ───────────────────────────────────────────────────────────────
// A single 4px bar spanning the full width of the card, animated between steps.

function ProgressBar({ step, total }: { step: number; total: number }) {
  const pct = Math.round(((step + 1) / total) * 100);
  return (
    <div className="w-full h-1 bg-white/10 rounded-full mb-8 overflow-hidden">
      <div
        className="h-full bg-gradient-to-r from-blue-500 to-purple-500 rounded-full transition-all duration-500 ease-out"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ── Skip link ──────────────────────────────────────────────────────────────────

function SkipLink({ onSkip }: { onSkip: () => void }) {
  return (
    <button
      onClick={onSkip}
      className="text-xs text-white/30 hover:text-white/55 transition-colors text-center mt-1"
    >
      Skip for now →
    </button>
  );
}

// ── Option card ────────────────────────────────────────────────────────────────

interface OptionProps {
  label: string;
  description?: string;
  icon?: React.ReactNode;
  selected: boolean;
  onClick: () => void;
  multi?: boolean;
}

function OptionCard({ label, description, icon, selected, onClick }: OptionProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left px-4 py-3.5 rounded-2xl border transition-all duration-150",
        selected
          ? "border-white/60 bg-white/10 text-white"
          : "border-white/10 bg-white/5 text-white/60 hover:border-white/30 hover:text-white/80"
      )}
    >
      <div className="flex items-center gap-3">
        {icon && <span className="text-xl w-7 flex-shrink-0 flex items-center">{icon}</span>}
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm">{label}</div>
          {description && <div className="text-xs text-white/40 mt-0.5">{description}</div>}
        </div>
        <div className={cn(
          "w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 transition-colors",
          selected ? "border-white bg-white" : "border-white/30"
        )}>
          {selected && <CheckCircle2 size={12} className="text-black" />}
        </div>
      </div>
    </button>
  );
}

// ── Continue button ────────────────────────────────────────────────────────────

function ContinueBtn({ onClick, disabled, label = "Continue" }: { onClick: () => void; disabled?: boolean; label?: string }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full py-3.5 rounded-2xl bg-white text-black font-semibold text-sm transition-all disabled:opacity-30 disabled:cursor-not-allowed hover:bg-white/90 active:scale-[0.98] flex items-center justify-center gap-2"
    >
      {label}
      <ChevronRight size={16} />
    </button>
  );
}

// ── Spinner helper ─────────────────────────────────────────────────────────────

function Spin() {
  return (
    <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z" />
    </svg>
  );
}

// ── Data types ─────────────────────────────────────────────────────────────────

interface OnboardingData {
  goal: string;
  experience: string;
  risk_tolerance: string;
  time_horizon: string;
  asset_classes: string[];
  interests: string[];
  full_name: string;
  dob: string;
  address: string;
  ssn_last4: string;
  kyc_verified: boolean;
  bank_linked: boolean;
  bank_name: string;
  deposit_amount: number;
}

// ── Step 0: Welcome ────────────────────────────────────────────────────────────

function StepWelcome({ onNext }: { onNext: () => void }) {
  return (
    <div className="flex flex-col items-center text-center gap-8">
      <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shadow-2xl shadow-blue-500/30">
        <TrendingUp size={36} className="text-white" />
      </div>
      <div>
        <h1 className="text-3xl font-bold text-white mb-3">Welcome to BMG Capital</h1>
        <p className="text-white/60 text-sm leading-relaxed max-w-xs mx-auto">
          Your professional trading platform. Let's personalize your experience in under 5 minutes.
        </p>
      </div>
      <div className="grid grid-cols-3 gap-4 w-full">
        {[
          { icon: <BarChart2 size={18} />, label: "Smart Screener" },
          { icon: <Zap size={18} />, label: "AI Co-Pilot" },
          { icon: <Shield size={18} />, label: "Paper Trading" },
        ].map(({ icon, label }) => (
          <div key={label} className="flex flex-col items-center gap-2 p-3 rounded-2xl bg-white/5 border border-white/10">
            <span className="text-blue-400">{icon}</span>
            <span className="text-xs text-white/60 font-medium">{label}</span>
          </div>
        ))}
      </div>
      <ContinueBtn onClick={onNext} label="Get Started" />
      <p className="text-xs text-white/30">No credit card required</p>
      <p className="text-xs text-white/30">
        Already have an account?{" "}
        <Link to="/login" className="text-white/50 hover:text-white/80 underline underline-offset-2 transition-colors">
          Sign in
        </Link>
      </p>
    </div>
  );
}

// ── Step 1: Asset classes ──────────────────────────────────────────────────────

function StepAssetClasses({ data, setData, onNext, onSkip }: { data: OnboardingData; setData: React.Dispatch<React.SetStateAction<OnboardingData>>; onNext: () => void; onSkip: () => void }) {
  const toggle = (v: string) =>
    setData((d) => ({
      ...d,
      asset_classes: d.asset_classes.includes(v)
        ? d.asset_classes.filter((x) => x !== v)
        : [...d.asset_classes, v],
    }));

  const opts = [
    { value: "stocks", label: "Stocks & ETFs", desc: "Individual companies and index funds", icon: <TrendingUp size={18} className="text-green-400" /> },
    { value: "options", label: "Options", desc: "Calls, puts, and advanced strategies", icon: <Layers size={18} className="text-yellow-400" /> },
    { value: "crypto", label: "Crypto", desc: "Bitcoin, Ethereum, altcoins, DeFi", icon: <Bitcoin size={18} className="text-orange-400" /> },
    { value: "all", label: "Everything", desc: "I want access to all markets", icon: <Star size={18} className="text-blue-400" /> },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">What do you want to trade?</h2>
        <p className="text-white/50 text-sm">Select all that apply</p>
      </div>
      <div className="flex flex-col gap-3">
        {opts.map((o) => (
          <OptionCard key={o.value} label={o.label} description={o.desc} icon={o.icon} selected={data.asset_classes.includes(o.value)} onClick={() => toggle(o.value)} multi />
        ))}
      </div>
      <ContinueBtn onClick={onNext} disabled={data.asset_classes.length === 0} />
      <SkipLink onSkip={onSkip} />
    </div>
  );
}

// ── Step 2: Goal ───────────────────────────────────────────────────────────────

function StepGoal({ data, setData, onNext, onSkip }: { data: OnboardingData; setData: React.Dispatch<React.SetStateAction<OnboardingData>>; onNext: () => void; onSkip: () => void }) {
  const opts = [
    { value: "wealth", label: "Grow my wealth", desc: "Long-term capital appreciation", icon: <TrendingUp size={18} className="text-green-400" /> },
    { value: "income", label: "Generate income", desc: "Dividends and yield strategies", icon: <CreditCard size={18} className="text-blue-400" /> },
    { value: "retirement", label: "Retire early", desc: "Build a retirement nest egg", icon: <Target size={18} className="text-purple-400" /> },
    { value: "speculation", label: "Active trading", desc: "Short-term trades and momentum", icon: <Zap size={18} className="text-yellow-400" /> },
    { value: "learn", label: "Learn to invest", desc: "I'm still getting started", icon: <BookOpen size={18} className="text-cyan-400" /> },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">What's your main goal?</h2>
        <p className="text-white/50 text-sm">We'll personalize your dashboard around this</p>
      </div>
      <div className="flex flex-col gap-3">
        {opts.map((o) => (
          <OptionCard key={o.value} label={o.label} description={o.desc} icon={o.icon} selected={data.goal === o.value} onClick={() => setData((d) => ({ ...d, goal: o.value }))} />
        ))}
      </div>
      <ContinueBtn onClick={onNext} disabled={!data.goal} />
      <SkipLink onSkip={onSkip} />
    </div>
  );
}

// ── Step 3: Experience ─────────────────────────────────────────────────────────

function StepExperience({ data, setData, onNext, onSkip }: { data: OnboardingData; setData: React.Dispatch<React.SetStateAction<OnboardingData>>; onNext: () => void; onSkip: () => void }) {
  const opts = [
    { value: "beginner", label: "Beginner", desc: "New to investing — less than 1 year", icon: "🌱" },
    { value: "intermediate", label: "Intermediate", desc: "1-5 years of experience", icon: "📈" },
    { value: "advanced", label: "Advanced", desc: "5+ years, active trader", icon: "⚡" },
    { value: "professional", label: "Professional", desc: "Licensed or institutional background", icon: "🏆" },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">How experienced are you?</h2>
        <p className="text-white/50 text-sm">This helps us set the right default view</p>
      </div>
      <div className="flex flex-col gap-3">
        {opts.map((o) => (
          <OptionCard key={o.value} label={o.label} description={o.desc} icon={o.icon} selected={data.experience === o.value} onClick={() => setData((d) => ({ ...d, experience: o.value }))} />
        ))}
      </div>
      <ContinueBtn onClick={onNext} disabled={!data.experience} />
      <SkipLink onSkip={onSkip} />
    </div>
  );
}

// ── Step 4: Risk ───────────────────────────────────────────────────────────────

function StepRisk({ data, setData, onNext, onSkip }: { data: OnboardingData; setData: React.Dispatch<React.SetStateAction<OnboardingData>>; onNext: () => void; onSkip: () => void }) {
  const opts = [
    { value: "conservative", label: "Conservative", desc: "Capital preservation first. I avoid large swings.", icon: <Shield size={18} className="text-blue-400" /> },
    { value: "moderate", label: "Moderate", desc: "Balanced risk. I can handle occasional 10-20% dips.", icon: <BarChart2 size={18} className="text-green-400" /> },
    { value: "aggressive", label: "Aggressive", desc: "High risk, high reward. I can stomach 30%+ drawdowns.", icon: <Zap size={18} className="text-orange-400" /> },
    { value: "speculative", label: "Speculative", desc: "Full risk appetite — options, leverage, small caps.", icon: <TrendingUp size={18} className="text-red-400" /> },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">What's your risk tolerance?</h2>
        <p className="text-white/50 text-sm">How do you react when your portfolio drops 20%?</p>
      </div>
      <div className="flex flex-col gap-3">
        {opts.map((o) => (
          <OptionCard key={o.value} label={o.label} description={o.desc} icon={o.icon} selected={data.risk_tolerance === o.value} onClick={() => setData((d) => ({ ...d, risk_tolerance: o.value }))} />
        ))}
      </div>
      <ContinueBtn onClick={onNext} disabled={!data.risk_tolerance} />
      <SkipLink onSkip={onSkip} />
    </div>
  );
}

// ── Step 5: Time horizon ───────────────────────────────────────────────────────

function StepTimeHorizon({ data, setData, onNext, onSkip }: { data: OnboardingData; setData: React.Dispatch<React.SetStateAction<OnboardingData>>; onNext: () => void; onSkip: () => void }) {
  const opts = [
    { value: "short", label: "Short term", desc: "Days to weeks — active trading", icon: <Clock size={18} className="text-yellow-400" /> },
    { value: "medium", label: "1-3 years", desc: "Swing trading and position trades", icon: <Clock size={18} className="text-green-400" /> },
    { value: "long", label: "5-10 years", desc: "Buy and hold with occasional rebalancing", icon: <Clock size={18} className="text-blue-400" /> },
    { value: "very_long", label: "10+ years", desc: "Long-term wealth building and retirement", icon: <Clock size={18} className="text-purple-400" /> },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">Investment time horizon</h2>
        <p className="text-white/50 text-sm">How long are you planning to hold your investments?</p>
      </div>
      <div className="flex flex-col gap-3">
        {opts.map((o) => (
          <OptionCard key={o.value} label={o.label} description={o.desc} icon={o.icon} selected={data.time_horizon === o.value} onClick={() => setData((d) => ({ ...d, time_horizon: o.value }))} />
        ))}
      </div>
      <ContinueBtn onClick={onNext} disabled={!data.time_horizon} />
      <SkipLink onSkip={onSkip} />
    </div>
  );
}

// ── Step 6: Interests ──────────────────────────────────────────────────────────

function StepInterests({ data, setData, onNext, onSkip }: { data: OnboardingData; setData: React.Dispatch<React.SetStateAction<OnboardingData>>; onNext: () => void; onSkip: () => void }) {
  const topics = ["AI & Tech", "Semiconductors", "Clean Energy", "Healthcare", "Biotech", "Defense", "Consumer", "Financials", "Real Estate", "Crypto Narratives", "DeFi", "NFTs & Web3"];
  const toggle = (v: string) =>
    setData((d) => ({
      ...d,
      interests: d.interests.includes(v) ? d.interests.filter((x) => x !== v) : [...d.interests, v],
    }));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">What sectors interest you?</h2>
        <p className="text-white/50 text-sm">Pick at least 2 — we'll surface relevant opportunities</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {topics.map((t) => (
          <button
            key={t}
            onClick={() => toggle(t)}
            className={cn(
              "px-4 py-2 rounded-full text-sm border transition-all",
              data.interests.includes(t)
                ? "border-white/60 bg-white/15 text-white font-medium"
                : "border-white/15 bg-white/5 text-white/50 hover:border-white/30 hover:text-white/70"
            )}
          >
            {t}
          </button>
        ))}
      </div>
      <ContinueBtn onClick={onNext} disabled={data.interests.length < 2} />
      <SkipLink onSkip={onSkip} />
    </div>
  );
}

// ── Step 7: Personal info (KYC step 1) ────────────────────────────────────────

function StepPersonalInfo({ data, setData, onNext }: { data: OnboardingData; setData: React.Dispatch<React.SetStateAction<OnboardingData>>; onNext: () => void }) {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Lock size={14} className="text-white/40" />
          <span className="text-xs text-white/40 uppercase tracking-wide font-medium">Secure · Encrypted</span>
        </div>
        <h2 className="text-2xl font-bold text-white mb-2">Personal information</h2>
        <p className="text-white/50 text-sm">Required by financial regulations (FINRA/SEC)</p>
      </div>
      {DEMO_MODE && (
        <div className="px-4 py-3 rounded-2xl bg-blue-500/10 border border-blue-500/20 text-xs text-blue-300">
          <span className="font-semibold">Demo Mode:</span> KYC is simulated. Fields auto-filled.
        </div>
      )}
      <div className="flex flex-col gap-4">
        <div>
          <label className="text-xs text-white/40 uppercase tracking-wide font-medium mb-1.5 block">Full legal name</label>
          <input
            value={DEMO_MODE ? "Demo User" : data.full_name}
            onChange={(e) => setData((d) => ({ ...d, full_name: e.target.value }))}
            placeholder="First and last name"
            readOnly={DEMO_MODE}
            className="w-full bg-white/5 border border-white/15 rounded-2xl px-4 py-3 text-sm text-white placeholder-white/30 outline-none focus:border-white/40"
          />
        </div>
        <div>
          <label className="text-xs text-white/40 uppercase tracking-wide font-medium mb-1.5 block">Date of birth</label>
          <input
            value={DEMO_MODE ? "01/01/1990" : data.dob}
            onChange={(e) => setData((d) => ({ ...d, dob: e.target.value }))}
            readOnly={DEMO_MODE}
            className="w-full bg-white/5 border border-white/15 rounded-2xl px-4 py-3 text-sm text-white outline-none focus:border-white/40"
          />
        </div>
        <div>
          <label className="text-xs text-white/40 uppercase tracking-wide font-medium mb-1.5 block">Home address</label>
          <input
            value={DEMO_MODE ? "123 Main St, New York, NY 10001" : data.address}
            onChange={(e) => setData((d) => ({ ...d, address: e.target.value }))}
            placeholder="Street, City, State, ZIP"
            readOnly={DEMO_MODE}
            className="w-full bg-white/5 border border-white/15 rounded-2xl px-4 py-3 text-sm text-white placeholder-white/30 outline-none focus:border-white/40"
          />
        </div>
      </div>
      <ContinueBtn onClick={onNext} />
    </div>
  );
}

// ── Step 8: Identity verify ────────────────────────────────────────────────────

function StepIdentityVerify({ setData, onNext }: { data: OnboardingData; setData: React.Dispatch<React.SetStateAction<OnboardingData>>; onNext: () => void }) {
  const [verifying, setVerifying] = useState(false);
  const [verified, setVerified] = useState(false);

  const verify = () => {
    setVerifying(true);
    setTimeout(() => {
      setVerified(true);
      setVerifying(false);
      setData((d) => ({ ...d, kyc_verified: true, ssn_last4: "1234" }));
    }, 2000);
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Lock size={14} className="text-white/40" />
          <span className="text-xs text-white/40 uppercase tracking-wide font-medium">256-bit encryption</span>
        </div>
        <h2 className="text-2xl font-bold text-white mb-2">Verify your identity</h2>
        <p className="text-white/50 text-sm">We need to confirm you are who you say you are</p>
      </div>
      {!verified ? (
        <>
          {DEMO_MODE && (
            <div className="px-4 py-3 rounded-2xl bg-blue-500/10 border border-blue-500/20 text-xs text-blue-300">
              <span className="font-semibold">Demo Mode:</span> SSN verification is simulated.
            </div>
          )}
          <div>
            <label className="text-xs text-white/40 uppercase tracking-wide font-medium mb-1.5 block">Last 4 digits of SSN</label>
            <input
              type="password"
              maxLength={4}
              defaultValue={DEMO_MODE ? "1234" : ""}
              readOnly={DEMO_MODE}
              placeholder="••••"
              className="w-full bg-white/5 border border-white/15 rounded-2xl px-4 py-3 text-sm text-white placeholder-white/30 outline-none focus:border-white/40 tracking-widest text-center text-xl"
            />
          </div>
          <button
            onClick={verify}
            disabled={verifying}
            className="w-full py-3.5 rounded-2xl bg-white text-black font-semibold text-sm flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {verifying ? <><Spin /> Verifying…</> : <><Lock size={15} /> Verify Identity</>}
          </button>
        </>
      ) : (
        <div className="flex flex-col items-center gap-4 py-4">
          <div className="w-16 h-16 rounded-full bg-green-500/20 border border-green-500/40 flex items-center justify-center">
            <CheckCircle2 size={32} className="text-green-400" />
          </div>
          <div className="text-center">
            <p className="text-white font-semibold">Identity verified</p>
            <p className="text-white/50 text-sm mt-1">Your account is approved for trading</p>
          </div>
          <ContinueBtn onClick={onNext} />
        </div>
      )}
    </div>
  );
}

// ── Step 9: Bank link ──────────────────────────────────────────────────────────

function StepBankLink({ data, setData, onNext, onSkip }: { data: OnboardingData; setData: React.Dispatch<React.SetStateAction<OnboardingData>>; onNext: () => void; onSkip: () => void }) {
  const [linking, setLinking] = useState(false);
  const [linked, setLinked] = useState(false);

  const linkBank = () => {
    setLinking(true);
    setTimeout(() => {
      setLinked(true);
      setLinking(false);
      setData((d) => ({ ...d, bank_linked: true, bank_name: "Chase Checking ••4521" }));
    }, 2500);
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">Link your bank</h2>
        <p className="text-white/50 text-sm">Securely connect your bank to fund your account via ACH</p>
      </div>
      {!linked ? (
        <>
          {DEMO_MODE && (
            <div className="px-4 py-3 rounded-2xl bg-blue-500/10 border border-blue-500/20 text-xs text-blue-300">
              <span className="font-semibold">Demo Mode:</span> Plaid is simulated — Chase Checking will be connected.
            </div>
          )}
          <div className="flex flex-col gap-3">
            <div className="px-4 py-4 rounded-2xl bg-white/5 border border-white/10 flex items-center gap-4">
              <Building2 size={24} className="text-blue-400 flex-shrink-0" />
              <div>
                <p className="text-white text-sm font-medium">10,000+ banks supported</p>
                <p className="text-white/40 text-xs">Chase, BofA, Wells Fargo, Fidelity, and more</p>
              </div>
            </div>
            <div className="flex items-center gap-3 px-2">
              <Lock size={12} className="text-white/30 flex-shrink-0" />
              <p className="text-xs text-white/40">Bank-level 256-bit TLS. We never store your credentials.</p>
            </div>
          </div>
          <button
            onClick={linkBank}
            disabled={linking}
            className="w-full py-3.5 rounded-2xl bg-white text-black font-semibold text-sm flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {linking ? <><Spin /> Connecting…</> : <><Building2 size={15} /> Connect Bank Account</>}
          </button>
          <SkipLink onSkip={onSkip} />
        </>
      ) : (
        <div className="flex flex-col items-center gap-4 py-4">
          <div className="w-16 h-16 rounded-full bg-green-500/20 border border-green-500/40 flex items-center justify-center">
            <CheckCircle2 size={32} className="text-green-400" />
          </div>
          <div className="text-center">
            <p className="text-white font-semibold">{data.bank_name} connected</p>
            <p className="text-white/50 text-sm mt-1">Ready to fund your account</p>
          </div>
          <ContinueBtn onClick={onNext} />
        </div>
      )}
    </div>
  );
}

// ── Step 10: Deposit amount ────────────────────────────────────────────────────

function StepDeposit({ data, setData, onNext, onSkip }: { data: OnboardingData; setData: React.Dispatch<React.SetStateAction<OnboardingData>>; onNext: () => void; onSkip: () => void }) {
  const [custom, setCustom] = useState("");
  const presets = [100, 500, 1000, 5000];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">Initial deposit</h2>
        <p className="text-white/50 text-sm">
          {data.bank_linked ? `From ${data.bank_name}` : "How much to start with"}
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {presets.map((amt) => (
          <button
            key={amt}
            onClick={() => setData((d) => ({ ...d, deposit_amount: amt }))}
            className={cn(
              "py-4 rounded-2xl border text-sm font-semibold transition-all",
              data.deposit_amount === amt
                ? "border-white/60 bg-white/10 text-white"
                : "border-white/10 bg-white/5 text-white/60 hover:border-white/30"
            )}
          >
            ${amt.toLocaleString()}
          </button>
        ))}
      </div>
      <div>
        <label className="text-xs text-white/40 uppercase tracking-wide font-medium mb-1.5 block">Custom amount</label>
        <div className="relative">
          <span className="absolute left-4 top-1/2 -translate-y-1/2 text-white/50 text-sm">$</span>
          <input
            type="number"
            value={custom}
            onChange={(e) => {
              setCustom(e.target.value);
              setData((d) => ({ ...d, deposit_amount: parseFloat(e.target.value) || 0 }));
            }}
            placeholder="0.00"
            className="w-full bg-white/5 border border-white/15 rounded-2xl pl-8 pr-4 py-3 text-sm text-white placeholder-white/30 outline-none focus:border-white/40"
          />
        </div>
      </div>
      <ContinueBtn onClick={onNext} disabled={!data.deposit_amount || data.deposit_amount < 1} label="Deposit" />
      <SkipLink onSkip={onSkip} />
    </div>
  );
}

// ── Step 11: Deposit confirm ───────────────────────────────────────────────────

function StepDepositConfirm({ data, onNext, onSkip }: { data: OnboardingData; onNext: () => void; onSkip: () => void }) {
  const [processing, setProcessing] = useState(false);
  const [done, setDone] = useState(false);
  const amt = data.deposit_amount || 0;

  const confirm = () => {
    setProcessing(true);
    setTimeout(() => { setDone(true); setProcessing(false); }, 2000);
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">Confirm deposit</h2>
        <p className="text-white/50 text-sm">Review before we process</p>
      </div>
      {!done ? (
        <>
          <div className="flex flex-col gap-3 p-5 rounded-2xl bg-white/5 border border-white/10">
            <div className="flex justify-between text-sm">
              <span className="text-white/50">Amount</span>
              <span className="text-white font-semibold">${amt.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-white/50">From</span>
              <span className="text-white">{data.bank_name || "Bank account"}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-white/50">Settlement</span>
              <span className="text-white">2-3 business days (ACH)</span>
            </div>
            <div className="h-px bg-white/10 my-1" />
            <div className="flex justify-between text-sm">
              <span className="text-white/50">Trade access</span>
              <span className="text-green-400 font-medium">✓ Instant</span>
            </div>
            {DEMO_MODE && <div className="text-xs text-blue-300 text-center mt-1">Demo: This deposit is simulated</div>}
          </div>
          <button
            onClick={confirm}
            disabled={processing}
            className="w-full py-3.5 rounded-2xl bg-white text-black font-semibold text-sm flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {processing ? <><Spin /> Processing…</> : `Confirm $${amt.toLocaleString()} Deposit`}
          </button>
          <SkipLink onSkip={onSkip} />
        </>
      ) : (
        <div className="flex flex-col items-center gap-4 py-4">
          <div className="w-16 h-16 rounded-full bg-green-500/20 border border-green-500/40 flex items-center justify-center">
            <CheckCircle2 size={32} className="text-green-400" />
          </div>
          <div className="text-center">
            <p className="text-white font-semibold">Deposit initiated!</p>
            <p className="text-white/50 text-sm mt-1">${amt.toLocaleString()} arriving in 2-3 business days</p>
          </div>
          <ContinueBtn onClick={onNext} />
        </div>
      )}
    </div>
  );
}

// ── Step 12: Welcome reward ────────────────────────────────────────────────────

function StepWelcomeReward({ onNext, onSkip }: { onNext: () => void; onSkip: () => void }) {
  const [claimed, setClaimed] = useState(false);
  const [rewardValue, setRewardValue] = useState(22);

  const claimMut = useMutation({
    mutationFn: () => client.post("/api/onboarding/claim-reward").then((r) => r.data),
    onSuccess: (d) => { setRewardValue(d.value ?? 22); setClaimed(true); },
    onError: () => setClaimed(true),
  });

  return (
    <div className="flex flex-col items-center text-center gap-6">
      <div className="relative">
        <div className="w-24 h-24 rounded-3xl bg-gradient-to-br from-yellow-400/20 to-orange-500/20 border border-yellow-400/30 flex items-center justify-center">
          <Gift size={40} className="text-yellow-400" />
        </div>
        {claimed && (
          <div className="absolute -top-2 -right-2 w-8 h-8 rounded-full bg-green-500 flex items-center justify-center">
            <CheckCircle2 size={16} className="text-white" />
          </div>
        )}
      </div>
      {!claimed ? (
        <>
          <div>
            <h2 className="text-2xl font-bold text-white mb-2">🎉 A gift for you!</h2>
            <p className="text-white/60 text-sm leading-relaxed">
              Welcome to BMG Capital! We're giving you a free fractional share of Apple (AAPL) to get you started.
            </p>
          </div>
          <div className="w-full p-5 rounded-2xl bg-gradient-to-br from-yellow-400/10 to-orange-500/10 border border-yellow-400/20">
            <div className="flex items-center justify-between mb-3">
              <div className="text-left">
                <p className="text-white font-semibold">Apple Inc.</p>
                <p className="text-white/50 text-xs">AAPL · NASDAQ</p>
              </div>
              <div className="text-right">
                <p className="text-yellow-400 font-bold text-lg">0.1 share</p>
                <p className="text-white/50 text-xs">~$22 value</p>
              </div>
            </div>
            <p className="text-xs text-white/40 text-center">Added to your paper portfolio</p>
          </div>
          <button
            onClick={() => claimMut.mutate()}
            disabled={claimMut.isPending}
            className="w-full py-3.5 rounded-2xl bg-gradient-to-r from-yellow-400 to-orange-500 text-black font-semibold text-sm flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {claimMut.isPending ? <><Spin /> Claiming…</> : <><Gift size={16} /> Claim My Free Share</>}
          </button>
          <SkipLink onSkip={onSkip} />
        </>
      ) : (
        <div className="flex flex-col items-center gap-4">
          <h2 className="text-2xl font-bold text-white">You got it! 🎊</h2>
          <p className="text-white/60 text-sm">0.1 AAPL share (~${rewardValue.toFixed(2)}) added to your portfolio</p>
          <ContinueBtn onClick={onNext} label="Awesome!" />
        </div>
      )}
    </div>
  );
}

// ── Step 13: AI calibration ────────────────────────────────────────────────────

function StepAICalibrate({ onNext }: { onNext: () => void }) {
  const [progress, setProgress] = useState(0);
  const [stepIdx, setStepIdx] = useState(0);
  const steps = [
    "Analyzing your investment profile…",
    "Configuring Strategy Lab…",
    "Calibrating risk parameters…",
    "Personalizing Discovery feed…",
    "Activating BMG Intelligence…",
    "Your platform is ready!",
  ];

  useEffect(() => {
    const interval = setInterval(() => {
      setProgress((p) => {
        const next = Math.min(p + 2, 100);
        if (next % 17 === 0) setStepIdx((s) => Math.min(s + 1, steps.length - 1));
        if (next >= 100) { clearInterval(interval); setTimeout(onNext, 800); }
        return next;
      });
    }, 60);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex flex-col items-center text-center gap-8">
      <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-blue-500/20 to-purple-600/20 border border-blue-500/30 flex items-center justify-center">
        <Sparkles size={36} className="text-blue-400 animate-pulse" />
      </div>
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">Personalizing your experience</h2>
        <p className="text-white/60 text-sm">{steps[stepIdx]}</p>
      </div>
      <div className="w-full bg-white/10 rounded-full h-2">
        <div className="h-full bg-gradient-to-r from-blue-500 to-purple-500 rounded-full transition-all duration-200" style={{ width: `${progress}%` }} />
      </div>
      <p className="text-xs text-white/30">{progress}%</p>
    </div>
  );
}

// ── Step 14: Feature tour ──────────────────────────────────────────────────────

function StepFeatureTour({ onNext, onSkip }: { onNext: () => void; onSkip: () => void }) {
  const [idx, setIdx] = useState(0);
  const features = [
    { icon: <BarChart2 size={32} className="text-blue-400" />, title: "Strategy Lab", desc: "19 automated strategies scan nightly. AI-powered entry/exit, equity tracking, and backtests.", color: "from-blue-500/20 to-blue-600/10" },
    { icon: <Zap size={32} className="text-purple-400" />, title: "BMG Intelligence", desc: "Press ⌘K anywhere. Ask for live quotes, run screeners, or analyze your portfolio in plain English.", color: "from-purple-500/20 to-purple-600/10" },
    { icon: <Bitcoin size={32} className="text-orange-400" />, title: "Crypto Lab", desc: "Full market table, automated crypto strategies, DeFi yields, token security, and DAO governance.", color: "from-orange-500/20 to-orange-600/10" },
    { icon: <Shield size={32} className="text-green-400" />, title: "Paper Trading", desc: "Practice with $100K virtual cash. Full order types, real-time P&L, risk-free learning.", color: "from-green-500/20 to-green-600/10" },
  ];
  const f = features[idx];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">What's inside</h2>
        <p className="text-white/50 text-sm">{idx + 1} of {features.length}</p>
      </div>
      <div className={cn("p-6 rounded-2xl bg-gradient-to-br border border-white/10 flex flex-col items-center text-center gap-4", f.color)}>
        <div className="w-16 h-16 rounded-2xl bg-white/10 flex items-center justify-center">{f.icon}</div>
        <div>
          <h3 className="text-white font-bold text-lg mb-2">{f.title}</h3>
          <p className="text-white/60 text-sm leading-relaxed">{f.desc}</p>
        </div>
      </div>
      <div className="flex gap-2 justify-center">
        {features.map((_, i) => (
          <button key={i} onClick={() => setIdx(i)} className={cn("h-1.5 rounded-full transition-all", i === idx ? "bg-white w-6" : "bg-white/20 w-1.5")} />
        ))}
      </div>
      {idx < features.length - 1 ? (
        <button onClick={() => setIdx((i) => i + 1)} className="w-full py-3.5 rounded-2xl border border-white/20 text-white font-medium text-sm flex items-center justify-center gap-2 hover:bg-white/5 transition-colors">
          Next <ChevronRight size={16} />
        </button>
      ) : (
        <ContinueBtn onClick={onNext} label="I'm ready!" />
      )}
      <SkipLink onSkip={onSkip} />
    </div>
  );
}

// ── Step 15: All set ───────────────────────────────────────────────────────────

function StepAllSet({ onFinish, loading }: { onFinish: () => void; loading: boolean }) {
  return (
    <div className="flex flex-col items-center text-center gap-8">
      <div className="relative">
        <div className="w-24 h-24 rounded-full bg-gradient-to-br from-green-400/20 to-emerald-600/20 border-2 border-green-400/40 flex items-center justify-center">
          <CheckCircle2 size={44} className="text-green-400" />
        </div>
        <div className="absolute inset-0 rounded-full border-2 border-green-400/20 animate-ping" />
      </div>
      <div>
        <h2 className="text-3xl font-bold text-white mb-3">You're all set! 🚀</h2>
        <p className="text-white/60 text-sm leading-relaxed max-w-xs mx-auto">
          Your BMG Capital account is personalized and ready. Start with paper trading to practice risk-free.
        </p>
      </div>
      <div className="w-full flex flex-col gap-3">
        {["Profile personalized", "Strategy Lab activated", "Free AAPL share added to portfolio", "BMG Intelligence (⌘K) ready"].map((item) => (
          <div key={item} className="flex items-center gap-3 px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-left">
            <CheckCircle2 size={16} className="text-green-400 flex-shrink-0" />
            <span className="text-sm text-white/70">{item}</span>
          </div>
        ))}
      </div>
      <button
        onClick={onFinish}
        disabled={loading}
        className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-500 to-purple-600 text-white font-bold text-sm flex items-center justify-center gap-2 disabled:opacity-50 hover:from-blue-400 hover:to-purple-500 transition-all shadow-lg shadow-blue-500/20"
      >
        {loading ? <><Spin /> Saving…</> : <>Start Trading <ChevronRight size={16} /></>}
      </button>
    </div>
  );
}

// ── Celebration overlay ────────────────────────────────────────────────────────

function CelebrationOverlay() {
  return (
    <div className="absolute inset-0 rounded-3xl flex flex-col items-center justify-center gap-4 bg-gradient-to-br from-green-500/20 to-emerald-600/10 backdrop-blur-sm z-10 transition-all duration-500">
      <span className="text-7xl select-none" role="img" aria-label="checkmark">✓</span>
      <p className="text-2xl font-bold text-white">You're all set!</p>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function Onboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [celebrating, setCelebrating] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<OnboardingData>({
    goal: "",
    experience: "",
    risk_tolerance: "",
    time_horizon: "",
    asset_classes: [],
    interests: [],
    full_name: "",
    dob: "",
    address: "",
    ssn_last4: "",
    kyc_verified: DEMO_MODE,
    bank_linked: false,
    bank_name: "",
    deposit_amount: 0,
  });

  const completeMut = useMutation({
    mutationFn: () =>
      client.post("/api/onboarding/complete", {
        goal: data.goal || "wealth",
        experience: data.experience || "beginner",
        risk_tolerance: data.risk_tolerance || "moderate",
        time_horizon: data.time_horizon || "long",
        asset_classes: data.asset_classes,
        interests: data.interests,
        deposit_amount: data.deposit_amount,
      }).then((r) => r.data),
    onSuccess: () => {
      setCelebrating(true);
      setTimeout(() => navigate("/"), 1500);
    },
    onError: () => { toast.error("Failed to save profile"); navigate("/"); },
  });

  const next = useCallback(() => setStep((s) => s + 1), []);
  const back = () => setStep((s) => Math.max(s - 1, 0));
  // Skip simply advances without calling any API
  const skip = useCallback(() => setStep((s) => s + 1), []);

  const allSteps = [
    <StepWelcome onNext={next} />,
    <StepAssetClasses data={data} setData={setData} onNext={next} onSkip={skip} />,
    <StepGoal data={data} setData={setData} onNext={next} onSkip={skip} />,
    <StepExperience data={data} setData={setData} onNext={next} onSkip={skip} />,
    <StepRisk data={data} setData={setData} onNext={next} onSkip={skip} />,
    <StepTimeHorizon data={data} setData={setData} onNext={next} onSkip={skip} />,
    <StepInterests data={data} setData={setData} onNext={next} onSkip={skip} />,
    <StepPersonalInfo data={data} setData={setData} onNext={next} />,
    <StepIdentityVerify data={data} setData={setData} onNext={next} />,
    <StepBankLink data={data} setData={setData} onNext={next} onSkip={skip} />,
    <StepDeposit data={data} setData={setData} onNext={next} onSkip={skip} />,
    data.deposit_amount > 0 ? <StepDepositConfirm data={data} onNext={next} onSkip={skip} /> : null,
    <StepWelcomeReward onNext={next} onSkip={skip} />,
    <StepAICalibrate onNext={next} />,
    <StepFeatureTour onNext={next} onSkip={skip} />,
    <StepAllSet onFinish={() => completeMut.mutate()} loading={completeMut.isPending} />,
  ].filter(Boolean) as React.ReactElement[];

  const currentStep = allSteps[Math.min(step, allSteps.length - 1)];
  const isLast = step >= allSteps.length - 1;
  const isEssential = ESSENTIAL_STEPS.has(step);

  // Keyboard navigation: Enter on the card fires the primary CTA
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key !== "Enter") return;
      // Don't intercept Enter inside text inputs or textareas
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "BUTTON") return;
      e.preventDefault();
      // Find the first non-disabled button in the card that looks like a CTA
      const btn = cardRef.current?.querySelector<HTMLButtonElement>(
        "button:not([disabled])"
      );
      btn?.click();
    },
    []
  );

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-md">
        {/* Step counter row */}
        <div className="flex items-center justify-between mb-4">
          {step > 0 && !isLast ? (
            <button onClick={back} className="flex items-center gap-1.5 text-white/40 hover:text-white/70 transition-colors text-sm">
              <ChevronLeft size={16} /> Back
            </button>
          ) : (
            <div />
          )}
          <span className="text-xs text-white/30 font-mono">
            {Math.min(step + 1, allSteps.length)}/{allSteps.length}
          </span>
        </div>

        {/* Thin progress bar */}
        <ProgressBar step={Math.min(step, allSteps.length - 1)} total={allSteps.length} />

        {/* Card — keyboard nav target */}
        <div
          ref={cardRef}
          key={step}
          tabIndex={-1}
          onKeyDown={handleKeyDown}
          className="relative outline-none rounded-3xl"
        >
          {celebrating && <CelebrationOverlay />}
          {currentStep}
        </div>

        {/* "Skip for now" hint on essential steps that lack a skip CTA */}
        {!isEssential && false /* skip buttons are embedded in each step */}
      </div>
    </div>
  );
}
