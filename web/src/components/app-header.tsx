import type { ReactNode } from "react";
import { AppLogo } from "@/components/app-logo";
import { UserMenuDropdown } from "@/components/user-menu-dropdown";

type AppHeaderProps = {
  className?: string;
};

export function AppHeader({ className = "" }: AppHeaderProps) {
  return (
    <header
      className={`sticky top-0 z-40 border-b border-[var(--color-border)] bg-[var(--color-card)]/80 backdrop-blur ${className}`}
    >
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <AppLogo />
        <UserMenuDropdown />
      </div>
    </header>
  );
}

type AppShellProps = {
  children: ReactNode;
  mainClassName?: string;
};

export function AppShell({ children, mainClassName = "" }: AppShellProps) {
  return (
    <div className="min-h-screen flex flex-col">
      <AppHeader />
      <main className={`flex-1 ${mainClassName}`}>{children}</main>
    </div>
  );
}
