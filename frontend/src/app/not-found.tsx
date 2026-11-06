import Link from "next/link";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-[#090d16] flex flex-col items-center justify-center text-white px-4">
      <h2 className="text-xl font-bold mb-2">Page Not Found</h2>
      <p className="text-sm text-slate-400 mb-4">The requested resource could not be found.</p>
      <Link
        href="/"
        className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-medium text-white transition-colors"
      >
        Return to Dashboard
      </Link>
    </div>
  );
}

