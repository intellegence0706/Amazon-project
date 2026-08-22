"use client";

import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/products", label: "Products" },
  { href: "/leads", label: "Leads" },
];

export function Nav() {
  const path = usePathname() ?? "/";
  const active = (href: string) =>
    href === "/" ? path === "/" : path.startsWith(href);

  return (
    <nav className="top">
      <div className="inner">
        <span className="brand">Sourcing Engine</span>
        {LINKS.map((l) => (
          <a key={l.href} href={l.href} className={active(l.href) ? "on" : undefined}>
            {l.label}
          </a>
        ))}
        <a href="/settings" className={active("/settings") ? "on" : undefined}
           style={{ marginLeft: "auto" }}>
          Settings
        </a>
      </div>
    </nav>
  );
}
