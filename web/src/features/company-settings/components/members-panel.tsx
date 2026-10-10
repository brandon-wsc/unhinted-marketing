import { MailX } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CopyField } from "@/components/copy-field";
import { FormField } from "@/components/form-field";
import { RowIconAction } from "@/components/row-icon-action";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
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
  apiGetGovernance,
  apiListInvites,
  apiListMembers,
  apiPatchCompanyName,
  apiPatchGovernance,
  apiPatchMember,
  apiRemoveMember,
  apiRevokeInvite,
  type CompanyGovernanceSettings,
  type CompanyMember,
  type InviteRole,
  type OrgInviteItem,
} from "@/features/company-settings/api";
import { useAsyncData } from "@/hooks/use-async-data";
import { useFlash } from "@/hooks/use-flash";
import { mapApiError } from "@/lib/map-api-error";
import { isValidEmail } from "@/lib/simple-email";
import { errorMessage } from "@/lib/utils";

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
  const [savedFlash, setSavedFlash] = useFlash<boolean>();
  const [name, setName] = useState(companyName);
  const [savingName, setSavingName] = useState(false);
  const [members, setMembers] = useState<CompanyMember[]>([]);
  const [invites, setInvites] = useState<OrgInviteItem[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<InviteRole>("member");
  const [inviteEmailError, setInviteEmailError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<CompanyMember | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [draftRole, setDraftRole] = useState<InviteRole>("member");
  const [limitInput, setLimitInput] = useState("");
  const [limitError, setLimitError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [savingDetail, setSavingDetail] = useState(false);
  const [governance, setGovernance] = useState<CompanyGovernanceSettings | null>(null);
  const [savingPolicy, setSavingPolicy] = useState(false);

  useEffect(() => {
    setName(companyName);
  }, [companyName]);

  const { loading, error, setError, reload } = useAsyncData(
    async () => {
      const [memberRes, inviteRes, governanceRes] = await Promise.all([
        apiListMembers(accessToken, companyId),
        canManageTeam
          ? apiListInvites(accessToken, companyId)
          : Promise.resolve({ items: [] as OrgInviteItem[] }),
        canManageTeam
          ? apiGetGovernance(accessToken, companyId)
          : Promise.resolve(null as CompanyGovernanceSettings | null),
      ]);
      return { members: memberRes.items, invites: inviteRes.items, governance: governanceRes };
    },
    ({ members, invites, governance }) => {
      setMembers(members);
      setInvites(invites);
      setGovernance(governance);
    },
    [accessToken, companyId, canManageTeam],
  );

  async function onSaveName() {
    const next = name.trim();
    if (!next || !canManageTeam || next === companyName.trim()) return;
    setSavingName(true);
    setError(null);
    try {
      await apiPatchCompanyName(accessToken, companyId, next);
      await onCompanyRenamed?.();
      setSavedFlash(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingName(false);
    }
  }

  const detailMember = detailId ? (members.find((m) => m.user_id === detailId) ?? null) : null;
  const detailEditable = detailMember != null && canManageTeam && detailMember.role !== "owner";
  const trimmedLimit = limitInput.trim();
  const parsedLimit = trimmedLimit === "" ? null : Number(trimmedLimit);
  const detailDirty =
    detailMember != null &&
    (draftRole !== detailMember.role || parsedLimit !== detailMember.monthly_token_limit);

  function openMemberDetail(member: CompanyMember) {
    setDetailId(member.user_id);
    setDraftRole(member.role === "owner" ? "member" : member.role);
    setLimitInput(member.monthly_token_limit != null ? String(member.monthly_token_limit) : "");
    setLimitError(null);
    setDetailError(null);
  }

  async function onSaveDetail() {
    if (!detailMember) return;
    if (trimmedLimit !== "" && (!Number.isInteger(parsedLimit) || (parsedLimit ?? 0) < 1)) {
      setLimitError(t("settings.members.limit.invalid"));
      return;
    }
    setSavingDetail(true);
    setDetailError(null);
    try {
      const updated = await apiPatchMember(accessToken, companyId, detailMember.user_id, {
        role: draftRole,
        monthly_token_limit: parsedLimit,
      });
      setMembers((rows) => rows.map((row) => (row.user_id === updated.user_id ? updated : row)));
      setDetailId(null);
    } catch (err) {
      setDetailError(errorMessage(err));
    } finally {
      setSavingDetail(false);
    }
  }

  function usageLabel(member: CompanyMember): string {
    return member.monthly_token_limit != null
      ? t("settings.members.usage.ofLimit", {
          used: member.used_tokens.toLocaleString(),
          limit: member.monthly_token_limit.toLocaleString(),
        })
      : t("settings.members.usage.unlimited", {
          used: member.used_tokens.toLocaleString(),
        });
  }

  async function onTogglePublishApproval(checked: boolean) {
    if (!governance) return;
    setSavingPolicy(true);
    setError(null);
    try {
      const updated = await apiPatchGovernance(accessToken, companyId, {
        member_publish_requires_approval: checked,
      });
      setGovernance(updated);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingPolicy(false);
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
      setError(errorMessage(err));
    }
  }

  async function onSendInvite(e: FormEvent) {
    e.preventDefault();
    if (!canManageTeam) return;
    const trimmed = inviteEmail.trim();
    setError(null);
    setInviteEmailError(null);
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
      const message = errorMessage(err);
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

  async function onRevoke(invite: OrgInviteItem) {
    setError(null);
    try {
      await apiRevokeInvite(accessToken, companyId, invite.id);
      setInvites((rows) => rows.filter((row) => row.id !== invite.id));
    } catch (err) {
      setError(errorMessage(err));
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
              <TableHead>{t("settings.members.columns.member")}</TableHead>
              <TableHead>{t("settings.members.columns.role")}</TableHead>
              <TableHead>{t("settings.members.columns.usage")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.map((member) => (
              <TableRow key={member.user_id}>
                <TableCell className="max-w-72">
                  <button
                    type="button"
                    onClick={() => openMemberDetail(member)}
                    className="w-full cursor-pointer rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="block truncate font-medium">{member.display_name}</span>
                    <span className="block truncate text-sm text-muted-foreground">
                      {member.email}
                    </span>
                  </button>
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <Badge variant={roleBadgeVariant(member.role)}>
                    {t(`settings.members.roles.${member.role}`)}
                  </Badge>
                </TableCell>
                <TableCell className="whitespace-nowrap tabular-nums">
                  {usageLabel(member)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {canManageTeam && governance && (
        <div className="space-y-4 rounded-xl border border-border bg-card p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold">
                {t("settings.members.publishApproval.title")}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("settings.members.publishApproval.hint")}
              </p>
            </div>
            <Switch
              checked={governance.member_publish_requires_approval}
              disabled={savingPolicy}
              onCheckedChange={(checked) => void onTogglePublishApproval(checked)}
              aria-label={t("settings.members.publishApproval.title")}
            />
          </div>
        </div>
      )}

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
              <CopyField
                key={inviteUrl}
                value={inviteUrl}
                copyLabel={t("settings.members.invite.copy")}
                copiedLabel={t("settings.members.invite.copied")}
              />
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
                <TableHead className="text-right">
                  <span className="sr-only">{t("settings.members.columns.actions")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invites.map((invite) => (
                <TableRow key={invite.id}>
                  <TableCell className="max-w-64">
                    <span className="block truncate">{invite.email}</span>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    <Badge variant={invite.role === "admin" ? "secondary" : "outline"}>
                      {t(`settings.members.roles.${invite.role}`)}
                    </Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {formatDay(invite.expires_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <RowIconAction
                      label={t("settings.members.pending.revoke")}
                      onClick={() => void onRevoke(invite)}
                    >
                      <MailX />
                    </RowIconAction>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={detailMember !== null} onOpenChange={(open) => !open && setDetailId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{detailMember?.display_name}</DialogTitle>
            <DialogDescription>{detailMember?.email}</DialogDescription>
          </DialogHeader>
          {detailMember && (
            <form
              noValidate
              onSubmit={(e) => {
                e.preventDefault();
                void onSaveDetail();
              }}
              className="space-y-5"
            >
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground">
                  {t("settings.members.columns.role")}
                </p>
                {detailEditable ? (
                  <Select
                    value={draftRole}
                    onValueChange={(value) => setDraftRole(value as InviteRole)}
                  >
                    <SelectTrigger
                      size="sm"
                      className="w-40"
                      aria-label={t("settings.members.columns.role")}
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="admin">{t("settings.members.roles.admin")}</SelectItem>
                      <SelectItem value="member">{t("settings.members.roles.member")}</SelectItem>
                    </SelectContent>
                  </Select>
                ) : (
                  <Badge variant={roleBadgeVariant(detailMember.role)}>
                    {t(`settings.members.roles.${detailMember.role}`)}
                  </Badge>
                )}
              </div>

              <div className="space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground">
                  {t("settings.members.limit.title")}
                </p>
                {detailEditable ? (
                  <>
                    <p className="text-xs text-muted-foreground">
                      {t("settings.members.limit.hint", {
                        name: detailMember.display_name,
                        used: detailMember.used_tokens.toLocaleString(),
                      })}
                    </p>
                    <Input
                      type="number"
                      inputMode="numeric"
                      min={1}
                      step={1}
                      value={limitInput}
                      aria-label={t("settings.members.limit.field")}
                      aria-invalid={Boolean(limitError)}
                      aria-describedby={limitError ? "member-limit-error" : undefined}
                      onChange={(e) => {
                        setLimitInput(e.target.value);
                        if (limitError) setLimitError(null);
                      }}
                    />
                    {limitError && (
                      <p id="member-limit-error" className="text-xs text-destructive">
                        {limitError}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-sm tabular-nums">{usageLabel(detailMember)}</p>
                )}
              </div>

              <div className="space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground">
                  {t("settings.members.columns.joined")}
                </p>
                <p className="text-sm">{formatDay(detailMember.joined_at)}</p>
              </div>

              {detailError && <p className="text-xs text-destructive">{detailError}</p>}

              {detailEditable && (
                <DialogFooter className="sm:justify-between">
                  <Button
                    type="button"
                    variant="destructive"
                    disabled={savingDetail}
                    onClick={() => {
                      setRemoveTarget(detailMember);
                      setDetailId(null);
                    }}
                  >
                    {t("settings.members.removeTitle")}
                  </Button>
                  <Button type="submit" loading={savingDetail} disabled={!detailDirty}>
                    {t("common.save")}
                  </Button>
                </DialogFooter>
              )}
            </form>
          )}
        </DialogContent>
      </Dialog>

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
