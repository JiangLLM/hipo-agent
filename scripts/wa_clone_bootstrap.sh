#!/bin/bash
# Bring ONE WebArena box to a pristine, self-consistent state. Runs ON the box (as ubuntu).
#
# Also the reset primitive: the four site containers keep no volumes and no bind mounts
# (verified: `docker inspect` reports mounts=0 for all four), so every byte of site state lives
# in the container's writable layer. Deleting the container and re-running it from the pristine
# image therefore restores the site exactly — which is both how a clone gets clean, and how we
# reset between passes. Same script, both jobs.
#
# The base_url patch is not optional. Magento and GitLab persist their public URL in their own
# databases, so a clone of the original box serves absolute links pointing at the ORIGINAL box
# (the source box's homepage emits its own IP 386 times). Left unpatched, an agent on clone N
# would be redirected onto box 1 and every rollout would silently share one deployment again —
# exactly the contamination the clones exist to prevent. Hence: derive the IP locally, never
# hardcode it.
#
#   bash wa_clone_bootstrap.sh            # recreate all four sites, patch, verify
#   bash wa_clone_bootstrap.sh gitlab     # one site only (cheap targeted reset)
set -uo pipefail

IP=$(hostname -I | awk '{print $1}')
SITES=${*:-"shopping shopping_admin forum gitlab"}
echo "== box $(hostname) ip=$IP  sites: $SITES"

start_one() {
  case "$1" in
    shopping)       docker rm -f shopping >/dev/null 2>&1
                    docker run -d --name shopping -p 7770:80 shopping_final_0712 >/dev/null ;;
    shopping_admin) docker rm -f shopping_admin >/dev/null 2>&1
                    docker run -d --name shopping_admin -p 7780:80 shopping_admin_final_0719 >/dev/null ;;
    forum)          docker rm -f forum >/dev/null 2>&1
                    docker run -d --name forum -p 9999:80 postmill-populated-exposed-withimg >/dev/null ;;
    gitlab)         docker rm -f gitlab >/dev/null 2>&1
                    # --shm-size=2g and the explicit runsvdir-start entrypoint are from the
                    # original deployment; gitlab will not come up without them.
                    docker run -d --name gitlab --shm-size=2g -p 8023:8023 \
                      gitlab-populated-final-port8023 /opt/gitlab/embedded/bin/runsvdir-start >/dev/null ;;
    *) echo "!! unknown site $1"; return 1 ;;
  esac
  echo "   started $1"
}

# Start them ONE AT A TIME and let each settle. Recreating all four at once spikes memory well
# above the steady state they happily share, and on a 15 GB box gitlab is the one the kernel
# kills (Exited 137). That is how a reset intended to clean the fleet took gitlab down on all
# eight machines at once.
# forum polls instead of sleeping: postmill is up in seconds, and the per-mutating-task reddit
# reset calls this once per task — a flat 30s sleep there would double the reset cadence cost.
for s in $SITES; do
  start_one "$s"
  if [ "$s" = "forum" ]; then
    for _ in $(seq 1 30); do
      curl -sf -o /dev/null -m 2 "http://localhost:9999/" && break
      sleep 1
    done
  else
    sleep 30
  fi
done

# Wait for Magento to actually answer its own CLI, do not guess with sleep. The first attempt at
# this used `sleep 45` and swallowed stderr; shopping (141 GB image, much larger DB) was not ready
# yet, its base_url patch failed silently, and the clone went on serving 302s to
# metis.lti.cs.cmu.edu — the host baked into the upstream image. Silence looked like success.
wait_magento() {
  local c=$1
  for _ in $(seq 1 60); do
    if docker exec "$c" /var/www/magento2/bin/magento config:show web/secure/base_url >/dev/null 2>&1
    then echo "   $c cli ready"; return 0; fi
    sleep 10
  done
  echo "   !! $c cli never became ready"; return 1
}

patch_magento() {   # container, port
  local c=$1 port=$2
  wait_magento "$c" || return 1
  # setup:store-config:set is the one that fixes web/unsecure/base_url (the redirect source);
  # the direct UPDATE covers web/secure/base_url, which that command leaves alone. Both needed.
  docker exec "$c" /var/www/magento2/bin/magento setup:store-config:set \
    --base-url="http://${IP}:${port}" || { echo "   !! $c store-config:set failed"; return 1; }
  docker exec "$c" mysql -u magentouser -pMyPassword magentodb \
    -e "UPDATE core_config_data SET value='http://${IP}:${port}/' WHERE path='web/secure/base_url';" \
    || echo "   .. $c secure_base_url update skipped (non-fatal)"
  docker exec "$c" /var/www/magento2/bin/magento cache:flush >/dev/null \
    || { echo "   !! $c cache:flush failed"; return 1; }
  echo "   patched $c -> http://${IP}:${port}"
}

for s in $SITES; do
  case "$s" in
    shopping)       patch_magento shopping 7770 || exit 1 ;;
    shopping_admin) patch_magento shopping_admin 7780 || exit 1 ;;
    gitlab)
      docker exec gitlab sed -i "s|^external_url.*|external_url 'http://${IP}:8023'|" \
        /etc/gitlab/gitlab.rb 2>/dev/null
      # reconfigure is the slow step (minutes); run it in the foreground so "done" means done
      docker exec gitlab gitlab-ctl reconfigure >/dev/null 2>&1
      echo "   patched gitlab -> http://${IP}:8023" ;;
    forum)
      echo "   forum needs no url patch (postmill derives links from the Host header)" ;;
  esac
done

echo "== verify (a site is only usable when it serves ITS OWN ip)"
fail=0
for spec in "shopping 7770" "shopping_admin 7780" "forum 9999" "gitlab 8023"; do
  set -- $spec
  case " $SITES " in *" $1 "*) ;; *) continue ;; esac
  # follow redirects: an unpatched Magento answers 302 to the host baked into the image, and a
  # header-only check reads that as "alive". url_effective after -L is the honest signal.
  read -r code final <<<"$(curl -s -o /dev/null -L --max-time 40 \
      -w '%{http_code} %{url_effective}' "http://${IP}:$2/" 2>/dev/null || echo '000 -')"
  # Match ANY foreign host, not just 10.x — the first version of this check only looked for
  # private addresses and therefore missed metis.lti.cs.cmu.edu entirely.
  leak=$(curl -s -L --max-time 40 "http://${IP}:$2/" 2>/dev/null \
         | grep -oE 'https?://[A-Za-z0-9.-]+(:[0-9]+)?' | sort -u \
         | grep -vE "://($IP|www\.magentocommerce\.com|postmill\.xyz|ogp\.me|schema\.org|www\.w3\.org|gitlab\.com|about\.gitlab\.com|docs\.gitlab\.com|forum\.gitlab\.com)" \
         | head -3 | tr '\n' ' ')
  case "$final" in *"$IP"*) ;; *) leak="${leak}redirected-to:$final " ;; esac
  if [ -n "$leak" ] || [ "$code" = "000" ]; then
    echo "   !! $1 http=$code FOREIGN: $leak"
    fail=1
  else
    echo "   ok $1 http=$code, urls local"
  fi
done
[ "$fail" = 0 ] && echo "== BOX READY $IP" || { echo "== BOX NOT READY $IP"; exit 1; }
