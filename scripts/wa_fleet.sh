#!/bin/bash
# Manage the 8-box WebArena fleet (one box per rollout, so mutating tasks can produce N
# independent rewards instead of one shared answer sheet).
#
#   bash scripts/wa_fleet.sh check     # every box: ports up AND serving its OWN ip
#   bash scripts/wa_fleet.sh reset     # recreate all sites from pristine images, in parallel
#   bash scripts/wa_fleet.sh reset gitlab   # one site only (much cheaper than the full recreate)
#   bash scripts/wa_fleet.sh urls      # print the wa.base_urls value to pass to the runner
#
# `check` is deliberately stricter than "is the port open": a clone that has not had its base_url
# re-patched still answers 200 while emitting absolute links to the box it was cloned from, which
# would silently funnel every rollout back onto one deployment.
set -uo pipefail
cd "$(dirname "$0")/.."

KEY="${WA_KEY:-$HOME/.ssh/hippo-webarena-sandbox.pem}"
FLEET="${WA_FLEET:-10.44.12.29 10.44.12.12 10.44.12.27 10.44.12.38 10.44.12.41 10.44.12.44 10.44.12.48 10.44.12.58}"
CMD="${1:-check}"
SITE="${2:-}"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=8 -o BatchMode=yes"

case "$CMD" in
  urls)
    out=""
    for ip in $FLEET; do out="${out:+$out,}http://$ip"; done
    echo "$out"
    ;;

  check)
    # Only probe the site we are about to use. Checking all four means an unrelated site being
    # down (gitlab rebuilding, say) blocks a shopping_admin run for no reason.
    #   bash scripts/wa_fleet.sh check shopping_admin
    SPECS="shopping 7770|shopping_admin 7780|forum 9999|gitlab 8023"
    case "$SITE" in
      "") ;;
      reddit) SPECS="forum 9999" ;;
      shopping|shopping_admin|gitlab) SPECS="$SITE $(case $SITE in shopping) echo 7770;; shopping_admin) echo 7780;; gitlab) echo 8023;; esac)" ;;
      *) echo "!! unknown site '$SITE'"; exit 1 ;;
    esac
    ok=0; bad=0
    for ip in $FLEET; do
      line="  $ip"
      IFS='|'; for spec in $SPECS; do unset IFS
        set -- $spec
        # -L matters: an unpatched Magento answers 302 to the host baked into the upstream image
        # (metis.lti.cs.cmu.edu). A header-only check calls that "302, alive" and moves on, which
        # is exactly how the first fleet check passed 8/8 while 7 boxes were pointing off-fleet.
        read -r code final <<<"$(curl -s -o /dev/null -L --max-time 30 \
            -w '%{http_code} %{url_effective}' "http://$ip:$2/" 2>/dev/null || echo '000 -')"
        if [ "$code" = "000" ]; then line="$line  $1:DOWN"
        else
          case "$final" in
            *"$ip"*) line="$line  $1:$code" ;;
            *)       line="$line  $1:FOREIGN($final)" ;;
          esac
        fi
      done
      case "$line" in *DOWN*|*FOREIGN*) bad=$((bad+1)); echo "$line  <== NOT READY" ;;
                      *) ok=$((ok+1)); echo "$line" ;; esac
    done
    echo "== fleet: $ok ready, $bad not ready"
    [ "$bad" = 0 ] || exit 1
    ;;

  reset)
    echo "== resetting ${SITE:-all sites} on $(echo $FLEET | wc -w | tr -d ' ') boxes, in parallel"
    pids=""
    for ip in $FLEET; do
      scp -q -i "$KEY" -o StrictHostKeyChecking=no scripts/wa_clone_bootstrap.sh "ubuntu@$ip:/tmp/boot.sh"
      $SSH "ubuntu@$ip" "bash /tmp/boot.sh $SITE" > "/tmp/wa_reset_$ip.log" 2>&1 &
      pids="$pids $!"
    done
    fail=0
    for p in $pids; do wait "$p" || fail=$((fail+1)); done
    echo "== reset finished ($fail boxes reported failure); logs /tmp/wa_reset_<ip>.log"
    [ "$fail" = 0 ] || exit 1
    ;;

  *) echo "usage: $0 {check|reset [site]|urls}"; exit 1 ;;
esac
