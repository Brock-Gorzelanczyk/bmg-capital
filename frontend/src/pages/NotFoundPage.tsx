import { useNavigate } from "react-router-dom";

const SUGGESTIONS = [
  { label: "Dashboard", path: "/dashboard" },
  { label: "Strategy Lab", path: "/strategy" },
  { label: "Paper Trading", path: "/paper" },
];

export default function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-[#09090b] flex items-center justify-center p-8">
      <div className="text-center max-w-md w-full">
        {/* 404 heading */}
        <p className="text-8xl font-extrabold text-zinc-800 select-none leading-none mb-2">
          404
        </p>
        <h1 className="text-2xl font-bold text-white mb-2">Page Not Found</h1>
        <p className="text-zinc-400 text-sm mb-8">
          The page you&apos;re looking for doesn&apos;t exist.
        </p>

        {/* Go Home button */}
        <button
          onClick={() => navigate("/")}
          className="inline-flex items-center gap-2 bg-white text-black text-sm font-semibold px-5 py-2.5 rounded-lg hover:bg-zinc-200 transition-colors mb-10"
        >
          <span aria-hidden="true">&#8592;</span>
          Go Home
        </button>

        {/* Suggestions */}
        <div className="border-t border-zinc-800 pt-8">
          <p className="text-zinc-500 text-xs uppercase tracking-widest mb-4">
            Or try one of these
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            {SUGGESTIONS.map(({ label, path }) => (
              <button
                key={path}
                onClick={() => navigate(path)}
                className="text-sm text-zinc-400 hover:text-white bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 px-4 py-2 rounded-lg transition-colors"
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
