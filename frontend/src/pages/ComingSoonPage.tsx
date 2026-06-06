import { useNavigate } from "react-router-dom";
export default function ComingSoonPage({ title = "Coming Soon" }: { title?: string }) {
  const navigate = useNavigate();
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center">
      <div className="text-4xl">🚧</div>
      <h1 className="text-2xl font-bold text-[var(--text-primary)]">{title}</h1>
      <p className="text-[var(--text-muted)]">This feature is under construction.</p>
      <button onClick={() => navigate(-1)} className="px-4 py-2 bg-[var(--accent)] text-black rounded-lg text-sm font-medium">Go Back</button>
    </div>
  );
}
