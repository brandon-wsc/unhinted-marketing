import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/context/auth-context";
import { SetupProvider } from "@/context/setup-context";
import { ThemeProvider } from "@/context/theme-context";
import { ToastProvider } from "@/context/toast-context";
import { CompanySettingsPage } from "@/pages/company-settings";
import { DashboardPage } from "@/pages/dashboard";
import { InviteAcceptPage } from "@/pages/invite-accept";
import { LegacyAdminRedirect } from "@/pages/legacy-admin-redirect";
import { LoginPage } from "@/pages/login";
import { RegisterPage } from "@/pages/register";
import { SetupPage } from "@/pages/setup";
import { SystemPage } from "@/pages/system";
import "@/i18n";
import "streamdown/styles.css";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <ToastProvider>
        <TooltipProvider>
          <BrowserRouter>
            <AuthProvider>
              <SetupProvider>
                <Routes>
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/register" element={<RegisterPage />} />
                  <Route path="/setup" element={<SetupPage />} />
                  <Route path="/invite/:token" element={<InviteAcceptPage />} />
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/settings" element={<CompanySettingsPage />} />
                  <Route path="/system" element={<SystemPage />} />
                  <Route path="/admin" element={<LegacyAdminRedirect />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </SetupProvider>
            </AuthProvider>
          </BrowserRouter>
        </TooltipProvider>
      </ToastProvider>
    </ThemeProvider>
  </StrictMode>,
);
