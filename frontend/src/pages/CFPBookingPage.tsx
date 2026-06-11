import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Calendar, Video, Phone, CheckCircle, ExternalLink, Clock, MessageSquare } from "lucide-react";
import { toast } from "sonner";
import { getCFPAvailability, bookCFPSession, getMyCFPBookings, type CFPSlot, type CFPBookingResult, type CFPBookingItem } from "@/api/cfp";
import { getMyTier } from "@/api/tiers";
import { useNavigate } from "react-router-dom";

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function formatSlotDate(iso: string) {
  const d = new Date(iso);
  return `${DAY_NAMES[d.getDay()]}, ${MONTH_NAMES[d.getMonth()]} ${d.getDate()}`;
}

function formatSlotTime(iso: string) {
  const d = new Date(iso);
  const h = d.getHours();
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:00 ${ampm}`;
}

function groupSlotsByDate(slots: CFPSlot[]): Record<string, CFPSlot[]> {
  const groups: Record<string, CFPSlot[]> = {};
  for (const slot of slots) {
    const dateKey = slot.datetime.split("T")[0];
    if (!groups[dateKey]) groups[dateKey] = [];
    groups[dateKey].push(slot);
  }
  return groups;
}

export default function CFPBookingPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [selectedSlot, setSelectedSlot] = useState<string | null>(null);
  const [topic, setTopic] = useState("");
  const [format, setFormat] = useState<"video" | "phone">("video");
  const [confirmation, setConfirmation] = useState<CFPBookingResult | null>(null);

  const { data: availData } = useQuery({ queryKey: ["cfp-availability"], queryFn: getCFPAvailability });
  const { data: myBookings = [] } = useQuery({ queryKey: ["cfp-my-bookings"], queryFn: getMyCFPBookings });
  const { data: tierData } = useQuery({ queryKey: ["my-tier"], queryFn: getMyTier });

  const userTier = tierData?.tier ?? "free";
  const ents = tierData?.entitlements as Record<string, unknown> | undefined;
  const cfpLimit = ents ? Number(ents["cfp_sessions_per_year"] ?? 0) : 0;

  const thisYearBookings = myBookings.filter((b: CFPBookingItem) => {
    return new Date(b.slot_datetime).getFullYear() === new Date().getFullYear()
      && b.status !== "cancelled";
  });

  const sessionsUsed = thisYearBookings.length;
  const sessionsRemaining = cfpLimit === -1 ? "Unlimited" : Math.max(0, cfpLimit - sessionsUsed);
  const canBook = cfpLimit === -1 || sessionsUsed < cfpLimit;

  const slots = availData?.slots ?? [];
  const slotsByDate = groupSlotsByDate(slots);

  const bookMutation = useMutation({
    mutationFn: () => bookCFPSession(selectedSlot!, topic, format),
    onSuccess: (data) => {
      setConfirmation(data);
      qc.invalidateQueries({ queryKey: ["cfp-my-bookings"] });
      toast.success("Session booked!");
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Booking failed";
      toast.error(msg);
    },
  });

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">

        {/* Header */}
        <div className="rounded-2xl border border-[#4ade80]/30 bg-[#4ade80]/5 p-6">
          <div className="flex items-center gap-3 mb-2">
            <Calendar className="w-6 h-6 text-[#4ade80]" />
            <h1 className="text-2xl font-black text-[var(--text-primary)]">CFP Sessions</h1>
          </div>
          <p className="text-sm text-[var(--text-secondary)]">Book a 1:1 session with a Certified Financial Planner.</p>
          {userTier === "free" ? (
            <div className="mt-4 rounded-xl bg-yellow-500/10 border border-yellow-500/30 p-4 text-sm text-yellow-300">
              CFP sessions require <strong>Plus or Premium</strong> tier.{" "}
              <button onClick={() => navigate("/upgrade")} className="underline font-semibold hover:text-yellow-200">Upgrade now</button>
            </div>
          ) : (
            <div className="mt-4 flex items-center gap-6">
              <div>
                <div className="text-2xl font-black font-mono text-[#4ade80]">{sessionsRemaining}</div>
                <div className="text-xs text-[var(--text-secondary)]">sessions remaining</div>
              </div>
              <div>
                <div className="text-2xl font-black font-mono text-[var(--text-primary)]">{sessionsUsed}</div>
                <div className="text-xs text-[var(--text-secondary)]">used this year</div>
              </div>
              <div>
                <div className="text-sm font-bold text-[var(--text-primary)] capitalize">{userTier}</div>
                <div className="text-xs text-[var(--text-secondary)]">current tier</div>
              </div>
            </div>
          )}
        </div>

        {/* Booking Form */}
        {userTier !== "free" && !confirmation && (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 space-y-5">
            <h2 className="font-bold text-[var(--text-primary)]">Book a Session</h2>

            {/* Slot Picker */}
            <div className="space-y-3">
              <label className="text-sm font-semibold text-[var(--text-secondary)]">Select a Time</label>
              {Object.keys(slotsByDate).length === 0 && (
                <div className="text-sm text-[var(--text-secondary)]">No available slots found.</div>
              )}
              <div className="space-y-3">
                {Object.entries(slotsByDate).map(([dateKey, dateSlots]) => {
                  const firstSlot = dateSlots[0];
                  const d = new Date(firstSlot.datetime);
                  return (
                    <div key={dateKey}>
                      <div className="text-xs text-[var(--text-secondary)] font-semibold mb-2">{formatSlotDate(firstSlot.datetime)}</div>
                      <div className="flex flex-wrap gap-2">
                        {dateSlots.map(slot => (
                          <button
                            key={slot.datetime}
                            onClick={() => setSelectedSlot(slot.datetime)}
                            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                              selectedSlot === slot.datetime
                                ? "border-[#4ade80] bg-[#4ade80]/10 text-[var(--text-primary)]"
                                : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[#4ade80]/40"
                            }`}
                          >
                            <Clock className="w-3.5 h-3.5" />
                            {formatSlotTime(slot.datetime)}
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Topic */}
            <div className="space-y-2">
              <label className="text-sm font-semibold text-[var(--text-secondary)]">Topic (optional)</label>
              <div className="relative">
                <MessageSquare className="absolute left-3 top-3 w-4 h-4 text-[var(--text-secondary)]" />
                <textarea
                  value={topic}
                  onChange={e => setTopic(e.target.value)}
                  placeholder="e.g. Retirement planning, tax optimization, portfolio review..."
                  rows={3}
                  className="w-full bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg pl-10 pr-4 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:border-[#4ade80] resize-none"
                />
              </div>
            </div>

            {/* Format Toggle */}
            <div className="space-y-2">
              <label className="text-sm font-semibold text-[var(--text-secondary)]">Format</label>
              <div className="flex gap-2">
                {(["video", "phone"] as const).map(f => (
                  <button
                    key={f}
                    onClick={() => setFormat(f)}
                    className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                      format === f
                        ? "border-[#4ade80] bg-[#4ade80]/10 text-[var(--text-primary)]"
                        : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[#4ade80]/40"
                    }`}
                  >
                    {f === "video" ? <Video className="w-4 h-4" /> : <Phone className="w-4 h-4" />}
                    <span className="capitalize">{f}</span>
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={() => bookMutation.mutate()}
              disabled={!selectedSlot || !canBook || bookMutation.isPending}
              className="w-full py-3 rounded-xl bg-[#4ade80] text-black font-bold text-sm hover:bg-[#a3e635] transition-colors disabled:opacity-50"
            >
              {bookMutation.isPending ? "Booking…" : "Book Session"}
            </button>
            {!canBook && (
              <p className="text-xs text-yellow-400 text-center">
                You've used all your CFP sessions for this year.{" "}
                <button onClick={() => navigate("/upgrade")} className="underline">Upgrade to Premium</button> for unlimited.
              </p>
            )}
          </div>
        )}

        {/* Confirmation */}
        {confirmation && (
          <div className="rounded-2xl border border-[#4ade80]/30 bg-[#4ade80]/5 p-6 space-y-4">
            <div className="flex items-center gap-3">
              <CheckCircle className="w-6 h-6 text-[#4ade80]" />
              <h2 className="font-bold text-[var(--text-primary)]">Session Confirmed!</h2>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Confirmation ID</span>
                <span className="font-mono font-bold text-[var(--text-primary)]">{confirmation.confirmation_id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Date & Time</span>
                <span className="text-[var(--text-primary)]">
                  {formatSlotDate(confirmation.slot_datetime)} at {formatSlotTime(confirmation.slot_datetime)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Format</span>
                <span className="text-[var(--text-primary)] capitalize">{confirmation.format}</span>
              </div>
              {confirmation.topic && (
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">Topic</span>
                  <span className="text-[var(--text-primary)] max-w-[60%] text-right">{confirmation.topic}</span>
                </div>
              )}
            </div>
            {confirmation.format === "video" && (
              <a
                href={confirmation.zoom_link}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-blue-600 text-white font-bold text-sm hover:bg-blue-500 transition-colors"
              >
                <Video className="w-4 h-4" />
                Join Zoom Meeting
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            )}
            <p className="text-xs text-[var(--text-secondary)] text-center">A calendar invite has been sent to your email.</p>
            <button
              onClick={() => setConfirmation(null)}
              className="w-full py-2.5 rounded-xl bg-[var(--bg-base)] text-[var(--text-primary)] text-sm font-semibold hover:bg-[var(--border-subtle)] transition-colors"
            >
              Book Another Session
            </button>
          </div>
        )}

        {/* Past Sessions */}
        {myBookings.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Past Sessions</h2>
            <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-[var(--text-secondary)] border-b border-[var(--border-subtle)]">
                    <th className="text-left p-4">Date</th>
                    <th className="text-left p-4">Topic</th>
                    <th className="text-center p-4">Format</th>
                    <th className="text-center p-4">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {myBookings.map((b: CFPBookingItem) => (
                    <tr key={b.id}>
                      <td className="p-4">
                        <div className="text-[var(--text-primary)]">{formatSlotDate(b.slot_datetime)}</div>
                        <div className="text-xs text-[var(--text-secondary)]">{formatSlotTime(b.slot_datetime)}</div>
                      </td>
                      <td className="p-4 text-[var(--text-secondary)] max-w-xs truncate">{b.topic || "—"}</td>
                      <td className="p-4 text-center">
                        <span className="flex items-center justify-center gap-1 text-[var(--text-secondary)]">
                          {b.format === "video" ? <Video className="w-3.5 h-3.5" /> : <Phone className="w-3.5 h-3.5" />}
                          <span className="capitalize text-xs">{b.format}</span>
                        </span>
                      </td>
                      <td className="p-4 text-center">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                          b.status === "confirmed" ? "bg-[#4ade80]/20 text-[#4ade80]" :
                          b.status === "cancelled" ? "bg-zinc-500/20 text-zinc-400" :
                          "bg-blue-500/20 text-blue-400"
                        }`}>{b.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
