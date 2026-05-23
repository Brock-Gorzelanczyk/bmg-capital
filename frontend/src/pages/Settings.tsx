import { useNavigate } from "react-router-dom";
import { LogOut, User, Shield, Bell, Palette } from "lucide-react";
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

      {/* Account section */}
      <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl mb-4">
        <div className="flex items-center gap-3 p-4 border-b border-[#1E293B]">
          <User size={15} className="text-[#475569]" />
          <span className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest">Account</span>
        </div>
        <div className="p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-[#94A3B8]">Username</span>
            <span className="text-sm text-[#F8FAFC] font-medium">{user?.username ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-[#94A3B8]">Email</span>
            <span className="text-sm text-[#F8FAFC] font-medium">{user?.email ?? "—"}</span>
          </div>
        </div>
      </div>

      {/* Sign out */}
      <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl">
        <div className="flex items-center gap-3 p-4 border-b border-[#1E293B]">
          <Shield size={15} className="text-[#475569]" />
          <span className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest">Session</span>
        </div>
        <div className="p-4">
          <button
            onClick={handleSignOut}
            className="flex items-center gap-2 bg-[#EF4444]/10 hover:bg-[#EF4444]/20 border border-[#EF4444]/20 hover:border-[#EF4444]/40 text-[#EF4444] text-sm font-medium rounded-lg px-4 py-2.5 transition-colors cursor-pointer"
          >
            <LogOut size={15} />
            Sign out
          </button>
          <p className="text-[#334155] text-xs mt-2">
            You'll be returned to the login page.
          </p>
        </div>
      </div>
    </div>
  );
}
