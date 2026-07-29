import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NexusAI Console",
  description: "Governed AI gateway, knowledge hub, evaluation and agent platform",
};

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/gateway", label: "Gateway" },
  { href: "/knowledge", label: "Knowledge" },
  { href: "/observability", label: "Observability" },
  { href: "/evaluation", label: "Evaluation" },
  { href: "/agents", label: "Agents" },
  { href: "/governance", label: "Governance" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="flex min-h-screen">
          {/* TODO(UI-001): workspace switcher, auth guard, permission-gated nav */}
          <aside className="w-56 shrink-0 border-r border-rule bg-white">
            <div className="px-5 py-5">
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-steel">
                Nexus
              </div>
              <div className="mt-0.5 text-lg font-bold tracking-tight">Console</div>
            </div>
            <nav className="px-2 pb-6">
              {NAV.map((item) => (
                <a
                  key={item.href}
                  href={item.href}
                  className="block rounded px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 hover:text-ink"
                >
                  {item.label}
                </a>
              ))}
            </nav>
          </aside>
          <main className="flex-1 px-8 py-7">{children}</main>
        </div>
      </body>
    </html>
  );
}
