import type { TFunction } from "i18next";

const API_ERROR_KEYS: Record<string, string> = {
  "Invalid email address": "errors.invalidEmail",
  "Password must be at least 8 characters": "errors.passwordTooShort",
  "Passwords do not match": "errors.passwordMismatch",
  "Email already registered": "errors.emailAlreadyRegistered",
  "Invalid email or password": "errors.invalidCredentials",
  "Account is disabled": "errors.accountDisabled",
  "Invalid refresh token": "errors.invalidRefreshToken",
  "This email already belongs to a member of this company": "settings.members.invite.alreadyMember",
  "A pending invite already exists for this email": "settings.members.invite.alreadyPending",
  "A pending proposal already exists for this product code": "settings.products.alreadyPending",
  "A product with this product code already exists": "settings.products.fields.skuConflict",
  image_required: "preview.error.imageRequired",
  social_account_not_connected: "preview.error.notConnected",
};

export function mapApiError(message: string, t: TFunction): string {
  const key = API_ERROR_KEYS[message];
  if (key) return t(key);
  const statusMatch = /^Request failed \((\d+)\)$/.exec(message);
  if (statusMatch) return t("errors.requestFailed", { status: statusMatch[1] });
  return message;
}
