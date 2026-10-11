#!/bin/sh
# azd postprovision hook (ADR 0044). Runs after `azd provision` / `azd up`.
# Bicep outputs are injected as env vars by azd; fall back to `azd env
# get-values` so the script also works standalone:
#   eval "$(azd env get-values | sed 's/^/export /')" && deploy/azure/postprovision.sh
#
# Steps:
#   1. Upload the nginx upstream template to the nginx-conf Files share and
#      restart the web revision (the share mounts at /etc/nginx/templates —
#      the first revision may have started before the file existed).
#   2. Run the migrate job (alembic upgrade head) and wait for it.
#   3. Print the URLs and the custom-domain next step.
set -e

RG="${RESOURCE_GROUP_NAME:?bicep output RESOURCE_GROUP_NAME missing}"
JOB="${MIGRATE_JOB_NAME:?}"
ST="${STORAGE_ACCOUNT_NAME:?}"
SHARE="${NGINX_SHARE_NAME:-nginx-conf}"
WEB="${WEB_APP_NAME:?}"

echo "==> Uploading nginx upstream template to share '$SHARE'"
KEY="$(az storage account keys list -g "$RG" -n "$ST" --query '[0].value' -o tsv)"
az storage file upload \
  --account-name "$ST" --account-key "$KEY" \
  --share-name "$SHARE" \
  --source "$(dirname "$0")/nginx/default.conf.template" \
  --only-show-errors -o none

echo "==> Restarting latest web revision to pick up the template"
REV="$(az containerapp revision list -g "$RG" -n "$WEB" \
  --query 'sort_by(@, &properties.createdTime)[-1].name' -o tsv)"
az containerapp revision restart -g "$RG" -n "$WEB" --revision "$REV" -o none

echo "==> Running migrate job '$JOB' (alembic upgrade head)"
az containerapp job start -g "$RG" -n "$JOB" -o none
for i in $(seq 1 90); do
  STATUS="$(az containerapp job execution list -g "$RG" -n "$JOB" \
    --query 'sort_by(@, &properties.startTime)[-1].properties.status' -o tsv 2>/dev/null || true)"
  case "$STATUS" in
    Succeeded) echo "==> migrate: succeeded"; break ;;
    Failed|Degraded)
      echo "!! migrate job status: $STATUS"
      echo "   logs: az containerapp job logs show -g $RG -n $JOB --follow"
      exit 1 ;;
  esac
  sleep 10
done
[ "$STATUS" = "Succeeded" ] || { echo "!! migrate job did not finish in 15 min (status: $STATUS)"; exit 1; }

cat <<EOF

==> Deploy complete
    web:  https://${WEB_FQDN}
    api:  http://${API_INTERNAL_FQDN} (internal only)

    Custom domain (e.g. demo.unhinted.hk):
      1. CNAME  demo  →  ${WEB_FQDN}
      2. TXT    asuid.demo  →  $(az containerapp show -g "$RG" -n "$WEB" --query properties.customDomainVerificationId -o tsv)
      3. az containerapp hostname add -g $RG -n $WEB --hostname demo.unhinted.hk
      4. az containerapp env certificate create -g $RG -n ${MANAGED_ENV_NAME} \\
           --hostname demo.unhinted.hk --validation-method CNAME
      5. az containerapp hostname bind -g $RG -n $WEB --hostname demo.unhinted.hk \\
           --environment ${MANAGED_ENV_NAME} --validation-method CNAME

    First boot: open the web URL → /setup wizard creates SUPERADMIN + first org.
EOF
