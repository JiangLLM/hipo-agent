# How the WebArena machines were built on AWS

This file records what we actually ran, so that anyone can rebuild the same setup without
guessing. Everything below happened in the Zillow sandbox account 717279734741, region
us-west-2.

## 1. What we needed and why

WebArena is a benchmark of 812 web tasks that run against real websites. Those websites are
not public. Each team has to host them. There are six of them, and four matter for us:
a shopping store, its admin panel, a forum, and a GitLab server.

Our agent runs each task 8 times in parallel, and then compares the 8 runs to learn from
them. For tasks that only read data, one server is enough, because nothing changes and the
8 runs cannot disturb each other. For tasks that write data, one server is not enough. All
8 runs log in with the same account, and the grader checks the state of the server, so the
first run that succeeds makes the check pass for all 8. That is why we ended up with eight
machines instead of one.

## 2. The first machine

The first machine was launched on 2026 July 18. Its details are:

1. Instance i-08d438a258bafaaeb, tagged hippo-webarena
2. Type m6i.xlarge, which gives 4 CPUs and 16 GB of memory
3. Availability zone us-west-2a, subnet subnet-04edf09770b28cade, VPC vpc-0ea22b3f56f64f15a
4. Security group sg-0006aabf64d95494e
5. Key pair hippo-webarena. The private key on the laptop is ~/.ssh/hippo-webarena-sandbox.pem
   and the login user is ubuntu
6. Root disk 1000 GiB, gp3, 3000 IOPS
7. Private address 10.44.12.29. There is no public address, so you must be on the VPN

It has no IAM instance profile, which means Session Manager does not work. SSH is the only
way in.

## 3. How the sites got onto that machine

The work was done by a cloud init script and three small shell scripts that still live in
/data on the machine. The order was download, load, start, configure.

1. Cloud init installed docker, tmux and aria2, then wrote /data/download.sh and ran it
   inside a tmux session. That script pulls four tar files from
   http://metis.lti.cs.cmu.edu/webarena-images and writes /data/downloads_done when finished.
   The four files are shopping_final_0712.tar, shopping_admin_final_0719.tar,
   postmill_populated_exposed_withimg.tar and gitlab_populated_final_port8023.tar
2. /data/wa_setup.sh ran docker load on every tar in /data/tars. The four images take about
   424 GB in total. GitLab is 156 GB, shopping is 141 GB, the forum is 107 GB and the shopping
   admin is 19.9 GB. After this the disk sits at about 651 GB used out of 968 GB
3. /data/wa_up.sh started four containers. The ports are 7770 for shopping, 7780 for the
   shopping admin, 9999 for the forum and 8023 for GitLab. GitLab needs two extra arguments,
   a 2 GB shared memory setting and an explicit start command, or it will not come up
4. /data/wa_config.sh wrote the machine address into the sites. This step is easy to forget
   and it breaks everything if you skip it. Magento and GitLab store their own public address
   in their own database, so a fresh container serves links that point at the machine where the
   image was originally built

One detail is worth knowing because it makes the rest of the work simple. None of the four
containers uses a docker volume or a bind mount. Every byte of site data lives inside the
container writable layer. So deleting a container and starting a new one from the image gives
you a clean site again. That is both how we make a fresh machine and how we reset between
runs.

## 4. Cloning the first machine into eight

We did not rebuild the sites seven more times. We took an image of the first machine and
started seven copies of it. The whole thing took about half an hour.

1. Refresh AWS credentials first. The sandbox uses SSO, so the credentials in
   ~/.aws/credentials are temporary and expire in hours. Check them with
   `aws sts get-caller-identity`
2. Create the image. We passed `--no-reboot` so the running machine was never interrupted.
   This is safe here for one reason only. We do not care about the container writable layers
   in the snapshot, because every clone rebuilds its containers from the images, and image
   layers are read only and therefore always consistent

```
aws ec2 create-image --instance-id i-08d438a258bafaaeb \
  --name hippo-webarena-clone-20260726 --no-reboot
```

   The result was ami-05add2ab04b84ab85. The snapshot is 1000 GiB and took about twenty
   minutes to reach the available state.

3. Launch seven copies with the same type, subnet, security group and key.

```
aws ec2 run-instances --image-id ami-05add2ab04b84ab85 --count 7 \
  --instance-type m6i.xlarge --key-name hippo-webarena \
  --subnet-id subnet-04edf09770b28cade \
  --security-group-ids sg-0006aabf64d95494e
```

   The seven private addresses were 10.44.12.12, 10.44.12.27, 10.44.12.38, 10.44.12.41,
   10.44.12.44, 10.44.12.48 and 10.44.12.58. With the original at 10.44.12.29 that makes
   eight.

4. Before launching, we checked three quotas, and all three were fine. The CPU limit was
   1152 while we needed 32. The gp3 storage limit was 50 TiB while we needed 8 TiB. The
   subnet had 32 free addresses while we needed 7.

5. On each clone, run scripts/wa_clone_bootstrap.sh. It deletes the four containers, starts
   fresh ones from the images, writes the clone own address into the sites, and then checks
   the result. Containers arrive in the exited state because the original ones were started
   without a restart policy, so this step is required, not optional.

## 5. The mistake we made here, and how to avoid repeating it

The first attempt reported success on all seven clones while seven of them were broken. It
is worth reading this section before you trust any health check.

1. What went wrong. The shopping site kept sending visitors to
   http://metis.lti.cs.cmu.edu:7770/, the address baked into the original image. So an agent
   on any clone would have been pushed back to a machine we do not control
2. Why the patch failed. Shopping has the largest database, so its command line tool was not
   ready yet when the script tried to use it. The script waited a fixed 45 seconds and then
   moved on
3. Why nobody noticed. The script sent all output to /dev/null, so the failure printed
   nothing. And the check only looked for addresses starting with 10, so a hostname like
   metis.lti.cs.cmu.edu did not match anything
4. The three fixes. Wait until the Magento command line answers instead of sleeping for a
   guessed number of seconds. Never hide the output of a command whose failure matters. Follow
   redirects in the check and treat any foreign host as a failure, not only private addresses

The lesson is short. A check that cannot fail is not a check. Both of the bugs above were
invisible, and both of them looked exactly like success.

## 6. The map site

Map is the one site we still do not run, and there is a shortcut worth knowing.

1. Map is not a single docker image. It has a front end on port 3000 and a separate back end
   with five services, a tile server, a geocoder and three routing engines
2. The official way to host the back end pulls 189 GB of prepared data from a public S3
   bucket and wants a 1000 GB disk. We tried to verify that path and found the official
   startup script has two real bugs
3. You do not need the back end. WebArena runs its own shared back end at 18.208.187.221 and
   it is still alive. We tested all five ports and they answer in about 200 milliseconds, and
   the data is frozen at 2023 May 26, which is the version the benchmark answers were written
   against
4. So the remaining work is small. Start the front end on port 3000 on one machine and point
   it at 18.208.187.221. One machine is enough because all 109 map tasks only read data
5. Wikipedia is not worth the effort. No task config refers to it directly. It only serves as
   background reading for 23 tasks, and 17 of those also need map, so wikipedia alone buys
   you 6 tasks and costs a 95 GB download

## 7. Daily use

Three commands cover everything.

```
bash scripts/wa_fleet.sh check     # every machine must serve its own address
bash scripts/wa_fleet.sh reset     # rebuild all sites from the images, all machines at once
bash scripts/wa_fleet.sh urls      # print the address list to hand to the runner
```

The check is strict on purpose. It follows redirects and it fails if a page mentions any host
other than the machine you asked about. A machine that answers 200 while pointing somewhere
else is worse than a machine that is down, because the run will finish and the numbers will
look reasonable.

## 8. Cost

1. Eight m6i.xlarge machines cost about 1.54 dollars per hour together
2. Eight 1000 GiB gp3 disks cost about 640 dollars per month, so roughly 21 dollars per day
3. Together that is around 58 dollars per day while all eight are running
4. This is small next to the model spending. A single site with two arms and 8 runs per task
   costs somewhere near 1000 dollars in model calls
5. If the machines will sit idle for a while, stop the seven clones. You keep paying for the
   disks but not for the CPUs

## 9. What proves the setup works

The point of eight machines is that the 8 runs of one task must be independent. We did not
take that on trust. After a two task smoke run we read the addresses out of the step log and
counted distinct hosts.

```
rollout 0: 10.44.12.29     rollout 4: 10.44.12.41
rollout 1: 10.44.12.12     rollout 5: 10.44.12.44
rollout 2: 10.44.12.27     rollout 6: 10.44.12.48
rollout 3: 10.44.12.38     rollout 7: 10.44.12.58
```

Eight runs, eight machines, no overlap. Before we fixed a bug in the runner, all eight lines
read 10.44.12.29 while the log still announced that isolation was on, so this table is the
only real evidence. Rerun it after any change to the worker setup.
