#!/bin/bash
# Deploy the WebArena MAP frontend in us-west-2, pointed at the still-live official backend.
#
# Why this box exists: map's 109 tasks are ALL read-only, but the frontend (openstreetmap-website,
# port 3000) was never part of our four-site AMI. The heavy backend — tile server (:8080) and
# OSRM routing (:5000) — is still served by the official host 18.208.187.221 (probed 2026-08-11:
# tiles answer 200, OSRM returns real routes). So one t3a.xlarge running just the frontend
# unlocks the whole site. Read-only means rollouts cannot contaminate each other, so ONE box
# serves all 8 rollouts — no fleet needed.
#
#   bash scripts/wa_map_deploy.sh            # copy AMI (once), launch (once), verify, print URL
#   bash scripts/wa_map_deploy.sh verify     # just re-verify an existing box
#
# Idempotent: every step checks before it acts, so rerunning after a partial failure is safe.
set -uo pipefail

REGION=us-west-2
SRC_REGION=us-east-2
SRC_AMI=ami-08a862bf98e3bd7aa          # official webarena AMI (environment_docker README)
NAME=webarena-map-frontend
BACKEND=18.208.187.221
SUBNET=subnet-04edf09770b28cade        # same subnet as the 8-box fleet (AWS_FLEET.md)
KEY_NAME="${WA_KEYPAIR:-hippo-webarena}"   # the local .pem is named ...-sandbox.pem; the EC2 key pair is not
CMD="${1:-deploy}"

aws sts get-caller-identity --region $REGION >/dev/null 2>&1 || {
  echo "!! AWS credentials missing or expired — refresh them first"; exit 1; }

find_instance() {
  aws ec2 describe-instances --region $REGION \
    --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=pending,running" \
    --query 'Reservations[].Instances[].[InstanceId,PrivateIpAddress]' --output text | head -1
}

verify() {  # $1 = ip
  local ip=$1 ok=0
  echo "== verify map frontend on $ip"
  code=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "http://$ip:3000/" || echo 000)
  echo "   frontend :3000 -> $code"
  [ "$code" = "200" ] || ok=1
  # the frontend must actually reach the official backend, not just render a shell
  tile=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "http://$BACKEND:8080/tile/0/0/0.png" || echo 000)
  echo "   backend tile server -> $tile"
  [ "$tile" = "200" ] || ok=1
  osrm=$(curl -s -m 20 "http://$BACKEND:5000/route/v1/driving/-79.9959,40.4406;-80.2329,40.4915?overview=false" | head -c 12)
  echo "   backend OSRM -> ${osrm:-(no answer)}"
  case "$osrm" in *'"code":"Ok'*) ;; *) ok=1 ;; esac
  if [ $ok = 0 ]; then
    echo "== MAP READY.  Run it with:"
    echo "   WA_MAP_HOST=http://$ip bash scripts/run_wa_fleet.sh map"
  else
    echo "== NOT READY (frontend can take ~10 min after first boot while docker compose starts)"
  fi
  return $ok
}

if [ "$CMD" = "verify" ]; then
  read -r _id ip <<<"$(find_instance)"
  [ -n "${ip:-}" ] || { echo "!! no $NAME instance found"; exit 1; }
  verify "$ip"; exit $?
fi

# 1. Copy the AMI across regions (once). ~1000GB image: the copy takes about an hour.
AMI=$(aws ec2 describe-images --region $REGION --owners self \
  --filters "Name=name,Values=$NAME" --query 'Images[0].ImageId' --output text)
if [ "$AMI" = "None" ] || [ -z "$AMI" ]; then
  echo "== copying $SRC_AMI from $SRC_REGION (about an hour for 1TB)"
  AMI=$(aws ec2 copy-image --region $REGION --source-region $SRC_REGION \
        --source-image-id $SRC_AMI --name $NAME --query ImageId --output text) || exit 1
fi
echo "== ami: $AMI"
STATE=$(aws ec2 describe-images --region $REGION --image-ids "$AMI" \
        --query 'Images[0].State' --output text)
echo "   state: $STATE"
if [ "$STATE" != "available" ]; then
  echo "   waiting for the copy to finish (checks every 60s; safe to Ctrl-C and rerun later)"
  until [ "$(aws ec2 describe-images --region $REGION --image-ids "$AMI" \
             --query 'Images[0].State' --output text)" = "available" ]; do sleep 60; done
fi

# 2. Launch (once). user-data MAP_BACKEND_IP is the documented hook: the AMI's first boot reads
#    it and writes the backend address into the frontend's docker compose config.
read -r ID IP <<<"$(find_instance)"
if [ -z "${ID:-}" ]; then
  echo "== launching $NAME"
  ID=$(aws ec2 run-instances --region $REGION --image-id "$AMI" --instance-type t3a.xlarge \
       --key-name "$KEY_NAME" --subnet-id $SUBNET \
       --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=1000,VolumeType=gp3}' \
       --user-data "MAP_BACKEND_IP=$BACKEND" \
       --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
       --query 'Instances[0].InstanceId' --output text) || exit 1
  aws ec2 wait instance-running --region $REGION --instance-ids "$ID"
  IP=$(aws ec2 describe-instances --region $REGION --instance-ids "$ID" \
       --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)
fi
echo "== instance: $ID  ip: $IP"

# 3. Verify (retry for up to 15 min — first boot pulls up docker compose)
for _ in $(seq 1 15); do verify "$IP" && exit 0; sleep 60; done
echo "!! still not serving after 15 min — ssh in and check: cd ~/openstreetmap-website && docker compose ps"
exit 1
