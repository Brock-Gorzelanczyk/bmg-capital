import { useState, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  AtSign,
  ChevronRight,
  Download,
  ExternalLink,
  Mail,
  Trash2,
  UserPlus,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { cn, timeAgo } from "@/lib/utils";
import {
  getInvestors,
  getFollowUpsDue,
  createInvestor,
  updateInvestor,
  deleteInvestor,
  getEmailTemplates,
  personalizeTemplate,
  seedFounder,
  type Investor,
  type FollowUpDue,
  type EmailTemplate,
} from "@/api/founder";

// ─── Constants ────────────────────────────────────────────────────────────────

const COLUMNS = [
  { id: "not_contacted",      label: "Not Contacted",      color: "#6b7280" },
  { id: "email_sent",         label: "Email Sent",          color: "#3b82f6" },
  { id: "reply_received",     label: "Reply Received",      color: "#8b5cf6" },
  { id: "meeting_scheduled",  label: "Meeting Scheduled",   color: "#f59e0b" },
  { id: "met",                label: "Met",                 color: "#4ade80" },
  { id: "following_up",       label: "Following Up",        color: "#f97316" },
  { id: "committed",          label: "Committed 🎉",        color: "#22c55e" },
  { id: "passed",             label: "Passed",              color: "#ef4444" },
] as const;

type ColumnId = (typeof COLUMNS)[number]["id"];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function daysSince(dateStr: string | null): number | null {
  if (!dateStr) return null;
  return Math.floor((Date.now() - new Date(dateStr).getTime()) / 86_400_000);
}

function introBadge(path: Investor["intro_path"]) {
  const map: Record<string, string> = {
    cold:     "bg-zinc-700 text-zinc-300",
    warm:     "bg-amber-500/20 text-amber-300",
    referral: "bg-[#4ade80]/20 text-[#4ade80]",
  };
  return (
    <span className={cn("text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded tracking-wide", map[path] ?? "bg-zinc-700 text-zinc-300")}>
      {path}
    </span>
  );
}

function exportCsv(investors: Investor[]) {
  const headers = ["id","name","firm","role","contact_email","twitter_handle","linkedin_url","intro_path","status","last_contact_at","next_action","check_size_target","stage_focus","created_at"];
  const rows = investors.map(inv =>
    headers.map(h => {
      const val = inv[h as keyof Investor] ?? "";
      return `"${String(val).replace(/"/g, '""')}"`;
    }).join(",")
  );
  const blob = new Blob([headers.join(",") + "\n" + rows.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "investors.csv";
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Add Investor Modal ───────────────────────────────────────────────────────

interface AddModalProps {
  onClose: () => void;
  onSave: (data: Partial<Investor>) => void;
  isSaving: boolean;
}

function AddInvestorModal({ onClose, onSave, isSaving }: AddModalProps) {
  const [form, setForm] = useState<Partial<Investor>>({
    status: "not_contacted",
    intro_path: "cold",
    notes_md: "",
  });

  const set = (key: keyof Investor, value: string) =>
    setForm(prev => ({ ...prev, [key]: value }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-[480px] bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-6 shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-[var(--text-primary)] font-semibold text-base">Add Investor</h2>
          <button onClick={onClose} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-3">
          {(["name","firm","role"] as const).map(field => (
            <div key={field}>
              <label className="block text-[11px] text-[var(--text-secondary)] mb-1 capitalize">{field} {field === "name" || field === "firm" ? "*" : ""}</label>
              <input
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#4ade80]"
                value={(form[field] as string) ?? ""}
                onChange={e => set(field, e.target.value)}
                placeholder={field}
              />
            </div>
          ))}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] text-[var(--text-secondary)] mb-1">Email</label>
              <input
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#4ade80]"
                value={form.contact_email ?? ""}
                onChange={e => set("contact_email", e.target.value)}
                placeholder="email@firm.com"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[var(--text-secondary)] mb-1">Intro Path</label>
              <select
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#4ade80]"
                value={form.intro_path ?? "cold"}
                onChange={e => set("intro_path", e.target.value)}
              >
                <option value="cold">Cold</option>
                <option value="warm">Warm</option>
                <option value="referral">Referral</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] text-[var(--text-secondary)] mb-1">Check Size Target</label>
              <input
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#4ade80]"
                value={form.check_size_target ?? ""}
                onChange={e => set("check_size_target", e.target.value)}
                placeholder="e.g. $250k"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[var(--text-secondary)] mb-1">Stage Focus</label>
              <input
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#4ade80]"
                value={form.stage_focus ?? ""}
                onChange={e => set("stage_focus", e.target.value)}
                placeholder="e.g. Pre-seed"
              />
            </div>
          </div>

          <div>
            <label className="block text-[11px] text-[var(--text-secondary)] mb-1">Next Action</label>
            <input
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#4ade80]"
              value={form.next_action ?? ""}
              onChange={e => set("next_action", e.target.value)}
              placeholder="Send intro email..."
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] rounded-lg border border-[var(--border-subtle)]"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave(form)}
            disabled={isSaving || !form.name || !form.firm}
            className="px-4 py-2 text-sm font-semibold bg-[#4ade80] text-black rounded-lg disabled:opacity-50 hover:bg-[#a3e635] transition-colors"
          >
            {isSaving ? "Saving..." : "Add Investor"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Move Popover ─────────────────────────────────────────────────────────────

interface MovePopoverProps {
  currentStatus: string;
  onMove: (newStatus: ColumnId) => void;
  onClose: () => void;
}

function MovePopover({ currentStatus, onMove, onClose }: MovePopoverProps) {
  return (
    <div
      className="absolute z-30 right-0 top-8 w-44 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl shadow-2xl py-1"
      onClick={e => e.stopPropagation()}
    >
      {COLUMNS.filter(c => c.id !== currentStatus).map(col => (
        <button
          key={col.id}
          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)] text-left"
          onClick={() => { onMove(col.id); onClose(); }}
        >
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: col.color }} />
          {col.label}
        </button>
      ))}
    </div>
  );
}

// ─── Investor Card ─────────────────────────────────────────────────────────────

interface InvestorCardProps {
  investor: Investor;
  onOpenDetail: (inv: Investor) => void;
  onMove: (id: number, status: ColumnId) => void;
}

function InvestorCard({ investor, onOpenDetail, onMove }: InvestorCardProps) {
  const [showMove, setShowMove] = useState(false);
  const days = daysSince(investor.last_contact_at);
  const staleness = days !== null && days > 7;

  return (
    <div
      draggable
      onDragStart={e => e.dataTransfer.setData("investorId", String(investor.id))}
      className="bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-xl p-3 cursor-grab active:cursor-grabbing hover:border-[var(--border-emphasis)] transition-colors group select-none"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-1 mb-1">
        <div className="min-w-0">
          <p className="text-[var(--text-primary)] text-sm font-medium truncate">{investor.name}</p>
          <p className="text-[var(--text-secondary)] text-[11px] truncate">{investor.firm}</p>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          {introBadge(investor.intro_path)}
        </div>
      </div>

      {/* Last contact */}
      <p className={cn("text-[11px] mt-1.5", staleness ? "text-red-400" : "text-[var(--text-tertiary)]")}>
        {days === null ? "Never contacted" : `${days}d ago`}
      </p>

      {/* Next action */}
      {investor.next_action && (
        <p className="text-[11px] text-[var(--text-secondary)] mt-0.5 line-clamp-2">
          Next: {investor.next_action}
        </p>
      )}

      {/* Actions */}
      <div className="flex items-center gap-1.5 mt-2.5 relative">
        <div className="relative">
          <button
            className="text-[11px] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] border border-[var(--border-subtle)] rounded-md px-2 py-0.5 flex items-center gap-0.5 hover:border-[var(--border-emphasis)] transition-colors"
            onClick={e => { e.stopPropagation(); setShowMove(v => !v); }}
          >
            Move <ChevronRight className="w-3 h-3" />
          </button>
          {showMove && (
            <MovePopover
              currentStatus={investor.status}
              onMove={status => onMove(investor.id, status)}
              onClose={() => setShowMove(false)}
            />
          )}
        </div>
        <button
          className="text-[11px] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] border border-[var(--border-subtle)] rounded-md px-2 py-0.5 hover:border-[var(--border-emphasis)] transition-colors"
          onClick={e => { e.stopPropagation(); onOpenDetail(investor); }}
        >
          Detail
        </button>
      </div>
    </div>
  );
}

// ─── Detail Drawer ─────────────────────────────────────────────────────────────

interface DetailDrawerProps {
  investor: Investor;
  onClose: () => void;
  onUpdate: (id: number, data: Partial<Investor>) => void;
  onDelete: (id: number) => void;
}

function DetailDrawer({ investor, onClose, onUpdate, onDelete }: DetailDrawerProps) {
  const [notes, setNotes] = useState(investor.notes_md);
  const [nextAction, setNextAction] = useState(investor.next_action ?? "");
  const [lastContact, setLastContact] = useState(investor.last_contact_at ?? "");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [emailBody, setEmailBody] = useState<string | null>(null);
  const [emailSubject, setEmailSubject] = useState<string | null>(null);
  const [generatingEmail, setGeneratingEmail] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<string>("");

  const { data: templates = [] } = useQuery<EmailTemplate[]>({
    queryKey: ["email-templates"],
    queryFn: getEmailTemplates,
  });

  const col = COLUMNS.find(c => c.id === investor.status);

  const handleGenerateEmail = async () => {
    if (!selectedTemplate) {
      toast.error("Select a template first");
      return;
    }
    setGeneratingEmail(true);
    try {
      const result = await personalizeTemplate(selectedTemplate, investor.id);
      setEmailSubject(result.subject);
      setEmailBody(result.body);
    } catch {
      toast.error("Failed to generate email");
    } finally {
      setGeneratingEmail(false);
    }
  };

  const handleMarkContacted = () => {
    const now = new Date().toISOString();
    setLastContact(now);
    onUpdate(investor.id, { last_contact_at: now });
    toast.success("Marked as contacted today");
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-[400px] h-full bg-[var(--bg-elevated)] border-l border-[var(--border-subtle)] flex flex-col overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between p-5 border-b border-[var(--border-subtle)]">
          <div>
            <h2 className="text-[var(--text-primary)] font-semibold text-base">{investor.name}</h2>
            <p className="text-[var(--text-secondary)] text-sm">{investor.firm} · {investor.role}</p>
            {col && (
              <span className="inline-flex items-center gap-1.5 mt-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full border" style={{ color: col.color, borderColor: col.color + "40", background: col.color + "15" }}>
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: col.color }} />
                {col.label}
              </span>
            )}
          </div>
          <button onClick={onClose} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] p-1">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* Contact info */}
          <div className="space-y-2">
            {investor.contact_email && (
              <a href={`mailto:${investor.contact_email}`} className="flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
                <Mail className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate">{investor.contact_email}</span>
              </a>
            )}
            {investor.twitter_handle && (
              <a href={`https://twitter.com/${investor.twitter_handle.replace("@","")}`} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
                <AtSign className="w-3.5 h-3.5 shrink-0" />
                <span>{investor.twitter_handle}</span>
              </a>
            )}
            {investor.linkedin_url && (
              <a href={investor.linkedin_url} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
                <ExternalLink className="w-3.5 h-3.5 shrink-0" />
                <span>LinkedIn</span>
              </a>
            )}
          </div>

          {/* Metadata pills */}
          {(investor.check_size_target || investor.stage_focus) && (
            <div className="flex flex-wrap gap-1.5">
              {investor.check_size_target && (
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] border border-[var(--border-subtle)]">
                  {investor.check_size_target}
                </span>
              )}
              {investor.stage_focus && (
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] border border-[var(--border-subtle)]">
                  {investor.stage_focus}
                </span>
              )}
              {introBadge(investor.intro_path)}
            </div>
          )}

          {/* Last contact */}
          <div>
            <label className="block text-[11px] text-[var(--text-secondary)] mb-1">Last Contact Date</label>
            <input
              type="datetime-local"
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#4ade80]"
              value={lastContact ? lastContact.slice(0, 16) : ""}
              onChange={e => setLastContact(e.target.value)}
              onBlur={() => onUpdate(investor.id, { last_contact_at: lastContact || null })}
            />
          </div>

          {/* Next action */}
          <div>
            <label className="block text-[11px] text-[var(--text-secondary)] mb-1">Next Action</label>
            <input
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#4ade80]"
              value={nextAction}
              onChange={e => setNextAction(e.target.value)}
              onBlur={() => onUpdate(investor.id, { next_action: nextAction })}
              placeholder="What's the next step?"
            />
          </div>

          {/* Notes */}
          <div>
            <label className="block text-[11px] text-[var(--text-secondary)] mb-1">Notes (Markdown)</label>
            <textarea
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#4ade80] resize-none"
              rows={5}
              value={notes}
              onChange={e => setNotes(e.target.value)}
              onBlur={() => onUpdate(investor.id, { notes_md: notes })}
              placeholder="Markdown notes about this investor..."
            />
          </div>

          {/* Email generator */}
          <div className="border-t border-[var(--border-subtle)] pt-4">
            <p className="text-[11px] text-[var(--text-secondary)] mb-2 font-medium uppercase tracking-wide">Generate Email</p>
            <div className="flex gap-2 mb-2">
              <select
                className="flex-1 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-2 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#4ade80]"
                value={selectedTemplate}
                onChange={e => setSelectedTemplate(e.target.value)}
              >
                <option value="">Select template...</option>
                {templates.map(t => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
              <button
                onClick={handleGenerateEmail}
                disabled={generatingEmail}
                className="px-3 py-1.5 text-sm font-medium bg-[#4ade80]/20 text-[#4ade80] border border-[#4ade80]/30 rounded-lg hover:bg-[#4ade80]/30 disabled:opacity-50 transition-colors"
              >
                {generatingEmail ? "..." : "Generate"}
              </button>
            </div>
            {emailBody && (
              <div className="space-y-2">
                {emailSubject && (
                  <div>
                    <p className="text-[10px] text-[var(--text-tertiary)] mb-1">Subject</p>
                    <div className="bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)]">
                      {emailSubject}
                    </div>
                  </div>
                )}
                <div>
                  <p className="text-[10px] text-[var(--text-tertiary)] mb-1">Body</p>
                  <textarea
                    readOnly
                    className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] resize-none cursor-text"
                    rows={6}
                    value={emailBody}
                    onClick={e => (e.target as HTMLTextAreaElement).select()}
                  />
                </div>
                <button
                  onClick={() => {
                    const full = emailSubject ? `Subject: ${emailSubject}\n\n${emailBody}` : emailBody;
                    navigator.clipboard.writeText(full);
                    toast.success("Copied to clipboard");
                  }}
                  className="w-full text-sm py-1.5 rounded-lg border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-emphasis)] transition-colors"
                >
                  Copy to clipboard
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Footer actions */}
        <div className="p-4 border-t border-[var(--border-subtle)] space-y-2">
          <button
            onClick={handleMarkContacted}
            className="w-full py-2 text-sm font-medium bg-[#4ade80]/20 text-[#4ade80] border border-[#4ade80]/30 rounded-lg hover:bg-[#4ade80]/30 transition-colors"
          >
            Mark contacted today
          </button>
          {!showDeleteConfirm ? (
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="w-full py-2 text-sm font-medium text-red-400 border border-red-400/20 rounded-lg hover:bg-red-400/10 transition-colors flex items-center justify-center gap-1.5"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Delete investor
            </button>
          ) : (
            <div className="flex gap-2">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="flex-1 py-2 text-sm text-[var(--text-secondary)] border border-[var(--border-subtle)] rounded-lg hover:border-[var(--border-emphasis)]"
              >
                Cancel
              </button>
              <button
                onClick={() => { onDelete(investor.id); onClose(); }}
                className="flex-1 py-2 text-sm font-semibold bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
              >
                Confirm delete
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Kanban Column ─────────────────────────────────────────────────────────────

interface KanbanColumnProps {
  col: (typeof COLUMNS)[number];
  investors: Investor[];
  onDrop: (investorId: number, targetStatus: ColumnId) => void;
  onOpenDetail: (inv: Investor) => void;
  onMove: (id: number, status: ColumnId) => void;
  onAddClick?: () => void;
}

function KanbanColumn({ col, investors, onDrop, onOpenDetail, onMove, onAddClick }: KanbanColumnProps) {
  const [isDragOver, setIsDragOver] = useState(false);

  return (
    <div
      className={cn(
        "flex flex-col w-[220px] shrink-0 rounded-xl border transition-colors",
        isDragOver ? "border-[var(--border-emphasis)] bg-[var(--bg-elevated)]/80" : "border-[var(--border-subtle)] bg-[var(--bg-elevated)]"
      )}
      style={{ height: "calc(100vh - 160px)" }}
      onDragOver={e => { e.preventDefault(); setIsDragOver(true); }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={e => {
        e.preventDefault();
        setIsDragOver(false);
        const investorId = Number(e.dataTransfer.getData("investorId"));
        if (investorId) onDrop(investorId, col.id);
      }}
    >
      {/* Column header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-[var(--border-subtle)] shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: col.color }} />
          <span className="text-[11px] font-semibold text-[var(--text-primary)] truncate">{col.label}</span>
          <span className="text-[10px] text-[var(--text-tertiary)] shrink-0">{investors.length}</span>
        </div>
        {onAddClick && (
          <button
            onClick={onAddClick}
            className="text-[var(--text-tertiary)] hover:text-[#4ade80] transition-colors ml-1 shrink-0"
            title="Add investor"
          >
            <UserPlus className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* Card list */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {investors.map(inv => (
          <InvestorCard
            key={inv.id}
            investor={inv}
            onOpenDetail={onOpenDetail}
            onMove={onMove}
          />
        ))}
        {investors.length === 0 && (
          <div className="flex items-center justify-center h-16 text-[11px] text-[var(--text-tertiary)]">
            Drop here
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Follow-up Banner ─────────────────────────────────────────────────────────

interface FollowUpBannerProps {
  items: FollowUpDue[];
  onClickInvestor: (inv: Investor) => void;
}

function FollowUpBanner({ items, onClickInvestor }: FollowUpBannerProps) {
  if (!items.length) return null;

  const labelFor = (type: FollowUpDue["follow_up_type"]) => {
    if (type === "thank_you_due") return "thank you overdue";
    if (type === "decision_due") return "decision overdue";
    return `${items.find(i => i.follow_up_type === type)?.days_overdue ?? 0} days`;
  };

  return (
    <div className="flex items-center gap-2 px-4 py-2.5 bg-amber-500/10 border border-amber-500/20 rounded-xl mb-3 flex-wrap">
      <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
      <span className="text-amber-300 text-xs font-medium shrink-0">
        {items.length} follow-up{items.length > 1 ? "s" : ""} due:
      </span>
      {items.map((item, i) => (
        <button
          key={item.investor.id}
          onClick={() => onClickInvestor(item.investor)}
          className="text-xs text-amber-200 hover:text-white underline underline-offset-2"
        >
          {item.investor.name} ({labelFor(item.follow_up_type)}){i < items.length - 1 ? "," : ""}
        </button>
      ))}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function InvestorPipelinePage() {
  const queryClient = useQueryClient();
  const [detailInvestor, setDetailInvestor] = useState<Investor | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const draggingId = useRef<number | null>(null);

  const { data: investors = [], isLoading } = useQuery<Investor[]>({
    queryKey: ["founder-investors"],
    queryFn: getInvestors,
    staleTime: 30_000,
  });

  const { data: followUps = [] } = useQuery<FollowUpDue[]>({
    queryKey: ["founder-follow-ups"],
    queryFn: getFollowUpsDue,
    staleTime: 60_000,
  });

  // Move mutation with optimistic update
  const moveMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      updateInvestor(id, { status }),
    onMutate: async ({ id, status }) => {
      await queryClient.cancelQueries({ queryKey: ["founder-investors"] });
      const prev = queryClient.getQueryData<Investor[]>(["founder-investors"]);
      queryClient.setQueryData<Investor[]>(["founder-investors"], old =>
        old?.map(inv => inv.id === id ? { ...inv, status } : inv) ?? []
      );
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(["founder-investors"], ctx.prev);
      toast.error("Failed to move investor");
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["founder-investors"] });
      queryClient.invalidateQueries({ queryKey: ["founder-follow-ups"] });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<Investor> }) =>
      updateInvestor(id, data),
    onMutate: async ({ id, data }) => {
      await queryClient.cancelQueries({ queryKey: ["founder-investors"] });
      const prev = queryClient.getQueryData<Investor[]>(["founder-investors"]);
      queryClient.setQueryData<Investor[]>(["founder-investors"], old =>
        old?.map(inv => inv.id === id ? { ...inv, ...data } : inv) ?? []
      );
      // Keep detail drawer in sync
      setDetailInvestor(prev => prev?.id === id ? { ...prev, ...data } : prev);
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(["founder-investors"], ctx.prev);
      toast.error("Failed to update investor");
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["founder-investors"] });
    },
  });

  const createMutation = useMutation({
    mutationFn: (data: Partial<Investor>) => createInvestor(data),
    onSuccess: () => {
      toast.success("Investor added");
      queryClient.invalidateQueries({ queryKey: ["founder-investors"] });
      setShowAddModal(false);
    },
    onError: () => toast.error("Failed to add investor"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteInvestor(id),
    onSuccess: () => {
      toast.success("Investor deleted");
      queryClient.invalidateQueries({ queryKey: ["founder-investors"] });
      queryClient.invalidateQueries({ queryKey: ["founder-follow-ups"] });
    },
    onError: () => toast.error("Failed to delete investor"),
  });

  const seedMutation = useMutation({
    mutationFn: seedFounder,
    onSuccess: () => {
      toast.success("Demo data seeded");
      queryClient.invalidateQueries({ queryKey: ["founder-investors"] });
    },
    onError: () => toast.error("Failed to seed data"),
  });

  const handleMove = useCallback((id: number, status: ColumnId) => {
    moveMutation.mutate({ id, status });
  }, [moveMutation]);

  const handleUpdate = useCallback((id: number, data: Partial<Investor>) => {
    updateMutation.mutate({ id, data });
  }, [updateMutation]);

  const handleDelete = useCallback((id: number) => {
    deleteMutation.mutate(id);
  }, [deleteMutation]);

  const committed = investors.filter(inv => inv.status === "committed").length;

  return (
    <div className="flex flex-col h-full min-h-0 p-4 pb-2">
      {/* Page header */}
      <div className="flex items-center justify-between mb-3 shrink-0">
        <div>
          <h1 className="text-[var(--text-primary)] font-semibold text-lg">Investor Pipeline</h1>
          <p className="text-[var(--text-secondary)] text-xs mt-0.5">
            {investors.length} total · {committed} committed
          </p>
        </div>
        <div className="flex items-center gap-2">
          {investors.length === 0 && (
            <button
              onClick={() => seedMutation.mutate()}
              disabled={seedMutation.isPending}
              className="px-3 py-1.5 text-sm font-medium bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-secondary)] rounded-lg hover:text-[var(--text-primary)] hover:border-[var(--border-emphasis)] disabled:opacity-50 transition-colors"
            >
              {seedMutation.isPending ? "Seeding..." : "Seed demo data"}
            </button>
          )}
          <button
            onClick={() => exportCsv(investors)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-secondary)] rounded-lg hover:text-[var(--text-primary)] hover:border-[var(--border-emphasis)] transition-colors"
            title="Export CSV"
          >
            <Download className="w-3.5 h-3.5" />
            Export CSV
          </button>
        </div>
      </div>

      {/* Follow-up banner */}
      <FollowUpBanner items={followUps} onClickInvestor={setDetailInvestor} />

      {/* Board */}
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="w-6 h-6 border-2 border-[#4ade80] border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="flex-1 overflow-x-auto min-h-0">
          <div className="flex gap-3 pb-2" style={{ minWidth: "max-content" }}>
            {COLUMNS.map(col => {
              const colInvestors = investors.filter(inv => inv.status === col.id);
              return (
                <KanbanColumn
                  key={col.id}
                  col={col}
                  investors={colInvestors}
                  onDrop={handleMove}
                  onOpenDetail={setDetailInvestor}
                  onMove={handleMove}
                  onAddClick={col.id === "not_contacted" ? () => setShowAddModal(true) : undefined}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Detail drawer */}
      {detailInvestor && (
        <DetailDrawer
          investor={detailInvestor}
          onClose={() => setDetailInvestor(null)}
          onUpdate={handleUpdate}
          onDelete={handleDelete}
        />
      )}

      {/* Add modal */}
      {showAddModal && (
        <AddInvestorModal
          onClose={() => setShowAddModal(false)}
          onSave={data => createMutation.mutate(data)}
          isSaving={createMutation.isPending}
        />
      )}
    </div>
  );
}
