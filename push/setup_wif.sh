#!/bin/bash
# One-time setup: lets the workflows of Sillapps/sillapps.github.io send FCM
# messages for the sillapps-push Firebase project, without any key file
# (Workload Identity Federation: GitHub's OIDC token is exchanged for a
# short-lived Google token of the fcm-sender service account).
#
# Uses the Google login of the Firebase CLI for sillapps.pro@gmail.com (never
# gcloud: its account on this Mac is not Sillapps). Safe to run twice.
#   bash push/setup_wif.sh
set -euo pipefail

ACCOUNT=sillapps.pro@gmail.com
PROJECT=sillapps-push
REPO=Sillapps/sillapps.github.io
SA_ID=fcm-sender
SA="$SA_ID@$PROJECT.iam.gserviceaccount.com"
POOL=github
PROVIDER=github

firebase projects:list --account "$ACCOUNT" >/dev/null # refreshes the login
TOKEN=$(python3 -c "
import json, os
d = json.load(open(os.path.expanduser('~/.config/configstore/firebase-tools.json')))
print([a for a in d['additionalAccounts'] if a['user']['email'] == '$ACCOUNT'][0]['tokens']['access_token'])")
api() { curl -sS -X "$1" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" "$2" ${3:+-d "$3"}; }

NUMBER=$(api GET "https://cloudresourcemanager.googleapis.com/v1/projects/$PROJECT" | python3 -c "import json,sys; print(json.load(sys.stdin)['projectNumber'])")
echo "project $PROJECT ($NUMBER)"

echo "1. service account $SA"
api POST "https://iam.googleapis.com/v1/projects/$PROJECT/serviceAccounts" \
  "{\"accountId\":\"$SA_ID\",\"serviceAccount\":{\"displayName\":\"FCM sender (GitHub Actions)\"}}" | grep -E '"(email|message)"' || true

echo "2. it may send FCM messages (and nothing else)"
POLICY=$(api POST "https://cloudresourcemanager.googleapis.com/v1/projects/$PROJECT:getIamPolicy" '{}')
NEW=$(python3 -c "
import json, sys
p = json.loads(sys.argv[1]); role = 'roles/firebasecloudmessaging.admin'; m = 'serviceAccount:$SA'
b = next((b for b in p.setdefault('bindings', []) if b['role'] == role), None)
if b is None: p['bindings'].append({'role': role, 'members': [m]})
elif m not in b['members']: b['members'].append(m)
print(json.dumps({'policy': p}))" "$POLICY")
api POST "https://cloudresourcemanager.googleapis.com/v1/projects/$PROJECT:setIamPolicy" "$NEW" | grep -c firebasecloudmessaging >/dev/null && echo "   ok"

echo "3. identity pool and GitHub provider (only this repo)"
api POST "https://iam.googleapis.com/v1/projects/$PROJECT/locations/global/workloadIdentityPools?workloadIdentityPoolId=$POOL" \
  '{"displayName":"GitHub Actions"}' | grep -E '"(name|message)"' | head -1 || true
sleep 5
api POST "https://iam.googleapis.com/v1/projects/$PROJECT/locations/global/workloadIdentityPools/$POOL/providers?workloadIdentityPoolProviderId=$PROVIDER" \
  "{\"displayName\":\"GitHub\",\"oidc\":{\"issuerUri\":\"https://token.actions.githubusercontent.com\"},\"attributeMapping\":{\"google.subject\":\"assertion.sub\",\"attribute.repository\":\"assertion.repository\"},\"attributeCondition\":\"assertion.repository == '$REPO'\"}" | grep -E '"(name|message)"' | head -1 || true

echo "4. the repo may act as $SA_ID"
MEMBER="principalSet://iam.googleapis.com/projects/$NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.repository/$REPO"
api POST "https://iam.googleapis.com/v1/projects/$PROJECT/serviceAccounts/$SA:setIamPolicy" \
  "{\"policy\":{\"bindings\":[{\"role\":\"roles/iam.workloadIdentityUser\",\"members\":[\"$MEMBER\"]}]}}" | grep -c workloadIdentityUser >/dev/null && echo "   ok"

echo "5. repo variables (not secrets: nothing here is sensitive)"
gh variable set PUSH_WIF_PROVIDER --repo "$REPO" --body "projects/$NUMBER/locations/global/workloadIdentityPools/$POOL/providers/$PROVIDER"
gh variable set PUSH_SERVICE_ACCOUNT --repo "$REPO" --body "$SA"
echo "done: test with  gh workflow run push-fuel-wa.yml --repo $REPO -f topic=fuelwa-test -f force=true"
