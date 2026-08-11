# Using AWS at Zillow

Account Zillow Sandbox 2025, id 717279734741, role Zillow-Sandbox-Developer, region
`us-west-2`. No access yet? Request that role in
[ServiceNow, item "Access to AWS"](https://zillow.service-now.com/esc?id=sc_cat_item&sys_id=d0176f1013ed2b0095693a128144b06f&table=sc_cat_item&searchTerm=aws).
Machines only have private 10.x addresses, so connect to the VPN first. Cisco Secure Client,
server Seattle or Ashburn, group zillow, steps in
[KB0885818](https://zillow.service-now.com/zhub?id=kb_article&sysparm_article=KB0885818).

## Log in

**UI.** Open <https://zillow.awsapps.com/start> (or the AWS tile on
[Okta](https://zillow.okta.com/app/UserHome)). Click Zillow Sandbox 2025, then
Zillow-Sandbox-Developer. In the console, set the region menu at the top right to Oregon.

**CLI.** On that same portal page, click Access keys next to the role, copy the three export
lines, and paste them into your terminal. Also run `export AWS_DEFAULT_REGION=us-west-2` because
the pasted lines set no region. If the `aws` command is missing, `brew install awscli`
installs it. Check that it worked:

```
aws sts get-caller-identity
```

Good output shows Account 717279734741. The keys expire after a few hours. Then every
command reports an invalid token, and you paste fresh ones. Tired of pasting keys every few
hours? Run `aws configure sso` one time, following the
[internal SSO guide](https://zillowgroup.atlassian.net/wiki/spaces/ZillowOps/pages/175539546/AWS+SSO+Command+Line+Configuration+and+Support).
After that, `aws sso login --profile Zillow-Sandbox-Developer-717279734741` refreshes your
session in the browser.

## See what is running

**UI.** [EC2 instances list](https://us-west-2.console.aws.amazon.com/ec2/home?region=us-west-2#Instances:).

**CLI.**

```
aws ec2 describe-instances --filters "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].{Id:InstanceId,Ip:PrivateIpAddress,Name:Tags[?Key==`Name`]|[0].Value}' \
  --output table
```

## Start an instance

If instance, image, and key pair are new words for you, the official
[What is Amazon EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/concepts.html) page
explains them in five minutes. Every machine starts from an image. A fresh machine uses the standard Ubuntu image and needs
no preparation, so go straight to Launch below. A copy of an existing machine needs an image
of that machine first. The steps below use hippo-webarena as an example, and they work for
any machine.

### Make an image of an existing machine (skip this for a fresh machine)

**UI.** In the [instances list](https://us-west-2.console.aws.amazon.com/ec2/home?region=us-west-2#Instances:)
select the machine, then Actions > Image and templates > Create image. Give the image a
unique name and tick No reboot. Wait until it shows Available under
[AMIs](https://us-west-2.console.aws.amazon.com/ec2/home?region=us-west-2#Images:), twenty
minutes or more.

**CLI.** Put your machine's id in the first command. It prints an image id. Repeat the
second command with that id until it prints available.

```
aws ec2 create-image --instance-id i-08d438a258bafaaeb --name yutongs-webarena-20260803 --no-reboot
```

```
aws ec2 describe-images --image-ids ami-... --query 'Images[0].State' --output text
```

### Launch

**UI.** Open [Launch instances](https://us-west-2.console.aws.amazon.com/ec2/home?region=us-west-2#LaunchInstances:)
and fill in the form top to bottom:

1. Name. Put your username in it. AWS Guardrails opens Jira tickets for unnamed machines.
2. Image. For a fresh machine pick Ubuntu Server 24.04 on the Quick Start tab. For a copy
   pick your image on the My AMIs tab.
3. Instance type. m6i.xlarge is our usual size. For a copy, match the source machine.
4. Key pair. Pick one you own, or choose Create new key pair and keep the .pem file it
   downloads. That download is your only chance to ever get this file.
5. Network settings. Click Edit, then pick subnet subnet-04edf09770b28cade and existing
   security group sg-0006aabf64d95494e, the pair our machines use.

Click Launch instance.

**CLI.** The same form in one command, `aws ec2 run-instances`. Its flags match the form
items above, so reuse the same image id, instance type, key pair, subnet, and security
group, plus a Name tag with your username. The full flag list is in the
[official run-instances reference](https://docs.aws.amazon.com/cli/latest/reference/ec2/run-instances.html).
For standard Ubuntu, the Quick Start tab shows the image id next to the image name.

## SSH into a machine

The IP is in the instances list. The user is ubuntu. The key file is the .pem of the key
pair that the machine uses. The example below uses the hippo-webarena pair, and if you
need that file, ask Yutong. If ssh prints nothing and never connects, the VPN is off.
Session Manager does not work in this account, so SSH is the only way in.

```
chmod 400 ~/.ssh/hippo-webarena-sandbox.pem
ssh -i ~/.ssh/hippo-webarena-sandbox.pem ubuntu@10.44.12.29
```

## Stop or delete

**UI.** Select the instance, open Instance state, then click Stop or Terminate.

**CLI.** Use your machine's id from the instances list. Stop keeps the disk, so you still
pay for it. Terminate deletes everything forever.

```
aws ec2 stop-instances --instance-ids i-...
```

```
aws ec2 terminate-instances --instance-ids i-...
```
