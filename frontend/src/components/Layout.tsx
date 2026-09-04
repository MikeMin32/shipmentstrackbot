import { Link, Outlet, useLocation } from "react-router-dom";

const links = [
  { to: "/", label: "Home" },
  { to: "/shipments", label: "List" },
  { to: "/shipments/new", label: "Add" },
  { to: "/accounts", label: "Accounts" },
  { to: "/archive", label: "Archive" },
];

export function isNavActive(to: string, pathname: string): boolean {
  if (to === "/") {
    return pathname === "/";
  }
  if (to === "/shipments/new") {
    return pathname === "/shipments/new";
  }
  if (to === "/shipments") {
    return pathname === "/shipments" || (pathname.startsWith("/shipments/") && pathname !== "/shipments/new");
  }
  if (to === "/accounts") {
    return pathname === "/accounts" || pathname.startsWith("/accounts/");
  }
  if (to === "/archive") {
    return pathname === "/archive" || pathname.startsWith("/archive/");
  }
  return pathname === to;
}

export function Layout({ devAuth }: { devAuth: boolean }) {
  const { pathname } = useLocation();
  return (
    <div className="app-shell">
      {devAuth ? (
        <div className="dev-banner">Development auth is active. Do not use in production.</div>
      ) : null}
      <Outlet />
      <nav className="bottom-nav">
        {links.map((link) => {
          const active = isNavActive(link.to, pathname);
          return (
            <Link
              key={link.to}
              to={link.to}
              className={active ? "active" : undefined}
              aria-current={active ? "page" : undefined}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
