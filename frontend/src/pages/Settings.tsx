import { useNavigate } from "react-router-dom";
import { LogOut, User } from "lucide-react";
import { useAuthStore } from "@/store/authStore";

export default function Settings() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();

  const handleSignOut = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="max-w-2xl mx-auto pb-20 md:pb-6">
      <h1 className="text-xl font-bold text-[#F8FAFC] mb-6">Settings</h1>

      {/* Account info */}
      <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl mb-4 overflow-hidden">
        <div className="px-4 py-3 border-b border-[#1E293B]">
          <span className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest">Account</span>
        </div>
        <div className="divide-y divide-[#1E293B]">
          <div className="flex items-center justify-between px-4 py-3">
            <div className="flex items-center gap-2 text-[#94A3B8]">
              <User size={14} />
              <span className="text-sm">Username</span>
            </div>
            <span className="text-sm text-[#F8FAFC] font-medium">{user?.username ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between px-4 py-3">
            <span className="text-sm text-[#94A3B8]">Email</span>
            <span className="text-sm text-[#F8FAFC] font-medium">{user?.email ?? "—"}</span>
          </div>
        </div>
      </div>

      {/* Sign out */}
      <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[#1E293B]">
          <span className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest">Session</span>
        </div>
        <div className="p-4">
          <button
            onClick={handleSignOut}
            className="flex items-center gap-2.5 w-full bg-[#EF4444]/10 hover:bg-[#EF4444]/20 border border-[#EF4444]/20 hover:border-[#EF4444]/40 text-[#EF4444] text-sm font-semibold rounded-lg px-4 py-3 transition-colors cursor-pointer"
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
