import { type FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/context/auth-context";
import {
  ApiStatusError,
  apiCreateInvite,
  apiListInvites,
  apiListMembers,
  apiPatchCompanyName,
  apiPatchMemberRole,
  apiRemoveMember,
  apiRevokeInvite,
  type CompanyMember,
  type InviteRole,
  type OrgInviteItem,
} from "@/features/company-settings/api";
import { mapApiError } from "@/lib/map-api-error";
import { isValidEmail } from "@/lib/simple-email";

type MembersPanelProps = {
  companyId: string;
  companyName: string;
  canManageTeam: boolean;
  onCompanyRenamed?: () => Promise<unknown>;
};

function formatDay(iso: string): string {
  return iso.slice(0, 10);
}

function roleBadgeVariant(role: CompanyMember["role"]): "default" | "secondary" | "outline" {
  if (role === "owner") return "default";
  if (role === "admin") return "secondary";
  return "outline";
}

export function MembersPanel({
  companyId,
  companyName,
  canManageTeam,
  onCompanyRenamed,
}: MembersPanelProps) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const [name, setName] = useState(companyName);
  const [savingName, setSavingName] = useState(false);
  const [members, setMembers] = useState<CompanyMember[]>([]);
  const [invites, setInvites] = useState<OrgInviteItem[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<InviteRole>("member");
  const [inviteEmailError, setInviteEmailError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<CompanyMember | null>(null);

  useEffect(() => {
    setName(companyName);
  }, [companyName]);

  const reload = useCallback(async () => {
    const [memberRes, inviteRes] = await Promise.all([
      apiListMembers(accessToken, companyId),
      canManageTeam
        ? apiListInvites(accessToken, companyId)
        : Promise.resolve({ items: [] as OrgInviteItem[] }),
    ]);
    setMembers(memberRes.items);
    setInvites(inviteRes.items);
  }, [accessToken, companyId, canManageTeam]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        await reload();
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  async function onSaveName() {
    const next = name.trim();
    if (!next || !canManageTeam || next === companyName.trim()) return;
    setSavingName(true);
    setError(null);
    try {
      await apiPatchCompanyName(accessToken, companyId, next);
      await onCompanyRenamed?.();
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingName(false);
    }
  }

  async function onRoleChange(member: CompanyMember, role: InviteRole) {
    setError(null);
    try {
      const updated = await apiPatchMemberRole(accessToken, companyId, member.user_id, role);
      setMembers((rows) => rows.map((row) => (row.user_id === updated.user_id ? updated : row)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onConfirmRemove() {
    if (!removeTarget) return;
    setError(null);
    try {
      await apiRemoveMember(accessToken, companyId, removeTarget.user_id);
      setMembers((rows) => rows.filter((row) => row.user_id !== removeTarget.user_id));
      setRemoveTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onSendInvite(e: FormEvent) {
    e.preventDefault();
    if (!canManageTeam) return;
    const trimmed = inviteEmail.trim();
    setError(null);
    setInviteEmailError(null);
    setCopied(false);
    if (!isValidEmail(trimmed)) {
      setInviteEmailError(t("settings.members.invite.invalidEmail"));
      return;
    }
    const alreadyMember = members.some(
      (member) => member.email.trim().toLowerCase() === trimmed.toLowerCase(),
    );
    if (alreadyMember) {
      setInviteEmailError(t("settings.members.invite.alreadyMember"));
      return;
    }
    setSending(true);
    try {
      const created = await apiCreateInvite(accessToken, companyId, {
        email: trimmed,
        role: inviteRole,
      });
      setInviteUrl(created.invite_url);
      setInviteEmail("");
      await reload();
    } catch (err) {
      setInviteUrl(null);
      const message = err instanceof Error ? err.message : String(err);
      if (
        err instanceof ApiStatusError &&
        (err.status === 422 || err.status === 409 || /email/i.test(message))
      ) {
        setInviteEmailError(mapApiError(message, t));
      } else {
        setError(mapApiError(message, t));
      }
    } finally {
      setSending(false);
    }
  }

  async function onCopyLink() {
    if (!inviteUrl) return;
    await navigator.clipboard.writeText(inviteUrl);
    setCopied(true);
  }

  async function onRevoke(invite: OrgInviteItem) {
    setError(null);
    try {
      await apiRevokeInvite(accessToken, companyId, invite.id);
      setInvites((rows) => rows.filter((row) => row.id !== invite.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const nameDirty = name.trim() !== companyName.trim();

  if (loading) {
    return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {t("settings.members.title")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {canManageTeam
            ? t("settings.members.subtitleEditor")
            : t("settings.members.subtitleMember")}
        </p>
      </div>

      {!canManageTeam && (
        <Alert variant="info">
          <AlertDescription>{t("settings.members.readOnly")}</AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="space-y-4 rounded-xl border border-border bg-card p-6">
        <h2 className="text-sm font-semibold">{t("settings.members.companyName")}</h2>
        {canManageTeam ? (
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="flex-1"
              autoComplete="organization"
            />
            <Button
              type="button"
              loading={savingName}
              disabled={!name.trim() || !nameDirty}
              onClick={() => void onSaveName()}
            >
              {t("common.save")}
            </Button>
          </div>
        ) : (
          <p className="text-sm text-foreground">{companyName}</p>
        )}
        {savedFlash && (
          <Alert variant="success" className="flex h-9 items-center px-3 py-0">
            <AlertDescription className="col-start-auto leading-none text-success-foreground">
              {t("settings.members.saved")}
            </AlertDescription>
          </Alert>
        )}
      </div>

      <div className="space-y-4 rounded-xl border border-border bg-card p-6">
        <h2 className="text-sm font-semibold">{t("settings.members.roster")}</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("settings.members.columns.name")}</TableHead>
              <TableHead>{t("settings.members.columns.email")}</TableHead>
              <TableHead>{t("settings.members.columns.role")}</TableHead>
              <TableHead>{t("settings.members.columns.joined")}</TableHead>
              {canManageTeam && <TableHead>{t("settings.members.columns.actions")}</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.map((member) => (
              <TableRow key={member.user_id} className="hover:bg-accent">
                <TableCell>{member.display_name}</TableCell>
                <TableCell>{member.email}</TableCell>
                <TableCell>
                  <Badge variant={roleBadgeVariant(member.role)}>
                    {t(`settings.members.roles.${member.role}`)}
                  </Badge>
                </TableCell>
                <TableCell>{formatDay(member.joined_at)}</TableCell>
                {canManageTeam && (
                  <TableCell>
                    {member.role === "owner" ? null : (
                      <div className="flex flex-wrap items-center gap-2">
                        <Select
                          value={member.role}
                          onValueChange={(value) => void onRoleChange(member, value as InviteRole)}
                        >
                          <SelectTrigger size="sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="admin">
                              {t("settings.members.roles.admin")}
                            </SelectItem>
                            <SelectItem value="member">
                              {t("settings.members.roles.member")}
                            </SelectItem>
                          </SelectContent>
                        </Select>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          onClick={() => setRemoveTarget(member)}
                        >
                          {t("settings.members.remove")}
                        </Button>
                      </div>
                    )}
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {canManageTeam && (
        <div className="space-y-4 rounded-xl border border-border bg-card p-6">
          <div>
            <h2 className="text-sm font-semibold">{t("settings.members.invite.title")}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("settings.members.invite.hint")}
            </p>
          </div>
          <form
            noValidate
            onSubmit={(e) => void onSendInvite(e)}
            className="flex flex-col gap-2 sm:flex-row sm:items-start"
          >
            <FormField
              id="invite-email"
              label={t("common.email")}
              className="min-w-0 flex-1"
              error={inviteEmailError}
            >
              <Input
                id="invite-email"
                type="email"
                inputMode="email"
                autoComplete="off"
                value={inviteEmail}
                aria-invalid={Boolean(inviteEmailError)}
                aria-describedby={inviteEmailError ? "invite-email-error" : undefined}
                onChange={(e) => {
                  setInviteEmail(e.target.value);
                  if (inviteEmailError) setInviteEmailError(null);
                }}
              />
            </FormField>
            <FormField id="invite-role" label={t("settings.members.columns.role")}>
              <Select
                value={inviteRole}
                onValueChange={(value) => setInviteRole(value as InviteRole)}
              >
                <SelectTrigger id="invite-role" className="h-9 w-full sm:w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="admin">{t("settings.members.roles.admin")}</SelectItem>
                  <SelectItem value="member">{t("settings.members.roles.member")}</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
            <div className="space-y-2">
              <Label className="invisible hidden sm:flex" aria-hidden="true">
                &nbsp;
              </Label>
              <Button type="submit" loading={sending} disabled={!inviteEmail.trim()}>
                {t("settings.members.invite.send")}
              </Button>
            </div>
          </form>
          {inviteUrl && (
            <div className="space-y-2">
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input value={inviteUrl} readOnly className="flex-1" />
                <Button
                  type="button"
                  variant="outline"
                  className={copied ? "text-success" : undefined}
                  onClick={() => void onCopyLink()}
                >
                  {copied ? t("settings.members.invite.copied") : t("settings.members.invite.copy")}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                {t("settings.members.invite.pasteHint")}
              </p>
            </div>
          )}
        </div>
      )}

      {canManageTeam && invites.length > 0 && (
        <div className="space-y-4 rounded-xl border border-border bg-card p-6">
          <h2 className="text-sm font-semibold">{t("settings.members.pending.title")}</h2>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("settings.members.columns.email")}</TableHead>
                <TableHead>{t("settings.members.columns.role")}</TableHead>
                <TableHead>{t("settings.members.pending.expires")}</TableHead>
                <TableHead>{t("settings.members.columns.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invites.map((invite) => (
                <TableRow key={invite.id} className="hover:bg-accent">
                  <TableCell>{invite.email}</TableCell>
                  <TableCell>
                    <Badge variant={invite.role === "admin" ? "secondary" : "outline"}>
                      {t(`settings.members.roles.${invite.role}`)}
                    </Badge>
                  </TableCell>
                  <TableCell>{formatDay(invite.expires_at)}</TableCell>
                  <TableCell>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => void onRevoke(invite)}
                    >
                      {t("settings.members.pending.revoke")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <AlertDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.members.removeTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("settings.members.removeBody", { name: removeTarget?.display_name ?? "" })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void onConfirmRemove()}>
              {t("settings.members.remove")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
