# =====================================================================
# Script Action: vm_evaluate_request        (APIthon)
# Used by: Activity 1 of request_vm (Wait for Completion)
#
# Input args:
#   user_email      <- meta_info.user.email_addr
#   user_name       <- meta_info.user.full_name
#   department      <- meta_info.user.department
#   environment     <- data.environment
#   os_image        <- data.os_image
#   instance_type   <- data.instance_type     (InstanceType object from the resolver)
#   vm_name         <- data.vm_name           (short label, e.g. "loadtest")
#   disk_gb         <- data.disk_gb
#   duration_days   <- data.duration_days
#   justification   <- data.business_justification
#   now             <- $TIME()                (used only to make a request ID)
#
# Returns one "request" object holding everything the compound action needs:
# the approval route and reasons, the hostname, the row for the Spacelift
# stack, and all the chat messages.
# =====================================================================

# ------------------ DEMO CONFIG: keep in sync with vm_get_instance_types ------------------
DEFAULT_QUOTA_VCPU = 16
DEPT_QUOTA_VCPU = {"engineering": 32, "data science": 64, "contractors": 8}
CURRENT_USAGE_VCPU = {
    "aryaman.chakravarty@cprime.com": 4,
    "demo.contractor@yourco.com": 6,
}
DEFAULT_USAGE_VCPU = 4
CLUSTER_FREE = {
    "dev":  {"vcpu": 64, "memory_gb": 256},
    "test": {"vcpu": 32, "memory_gb": 128},
    "prod": {"vcpu": 12, "memory_gb": 48},
}
APPROVAL_ABOVE_VCPU = 8

# Approval routing for specific people.
APPROVAL_REQUIRED_DEPARTMENTS = ["contractors", "finance", "marketing"]
APPROVAL_REQUIRED_USERS = ["demo.contractor@yourco.com"]
MAX_DAYS_WITHOUT_APPROVAL = 30
MAX_DISK_WITHOUT_APPROVAL = 250

# Who approves. For a one-person demo, approve your own requests in chat.
DEFAULT_APPROVER = "aryaman.chakravarty@cprime.com"
DEPT_APPROVER = {}

# Spacelift: account subdomain (https://<account>.app.spacelift.io) and stack ID.
SPACELIFT_ACCOUNT = "aryaman20031411"
SPACELIFT_STACK = "vm-provisioner"
# ----------------------------------------------------------------------------------------

email = (user_email or "").lower()
dept = (department or "").lower()
env = (environment or "dev").lower()
if env not in CLUSTER_FREE:
    env = "dev"
itype = instance_type or {}
type_id = str(itype.get("id") or itype.get("name") or "t3.micro")
vcpu = int(itype.get("vcpu", 2))
mem = int(itype.get("memory_gb", 1))
free_tier = bool(itype.get("free_tier", False))
family = str(itype.get("family", ""))
disk = int(disk_gb or 20)
days = int(duration_days or 7)

os_short = "lnx"
os_l = (os_image or "").lower()
if "win" in os_l:
    os_short = "win"
elif "rhel" in os_l or "red hat" in os_l:
    os_short = "rhel"
elif "ubuntu" in os_l:
    os_short = "ubu"
if os_short == "win" and disk < 30:
    disk = 30   # Windows images need at least 30 GB

quota = DEPT_QUOTA_VCPU.get(dept, DEFAULT_QUOTA_VCPU)
used = CURRENT_USAGE_VCPU.get(email, DEFAULT_USAGE_VCPU)
remaining = quota - used
cluster = CLUSTER_FREE[env]

# ---- routing ----
reasons = []
route = "AUTO"
if vcpu > cluster["vcpu"] or mem > cluster["memory_gb"]:
    route = "BLOCKED"
    reasons.append("Not enough free capacity in " + env + " (" + str(cluster["vcpu"]) + " vCPU free)")
else:
    if env == "prod":
        reasons.append("Production environment")
    if vcpu > APPROVAL_ABOVE_VCPU:
        reasons.append("More than " + str(APPROVAL_ABOVE_VCPU) + " vCPU (" + str(vcpu) + ")")
    if vcpu > remaining:
        reasons.append("Exceeds your vCPU quota (" + str(max(remaining, 0)) + " of " + str(quota) + " left)")
    if not free_tier:
        reasons.append(type_id + " is not free-tier eligible, so it costs money")
    if dept in APPROVAL_REQUIRED_DEPARTMENTS or email in APPROVAL_REQUIRED_USERS:
        reasons.append("Your role requires approval for new VMs")
    if days > MAX_DAYS_WITHOUT_APPROVAL:
        reasons.append("Lease longer than " + str(MAX_DAYS_WITHOUT_APPROVAL) + " days")
    if disk > MAX_DISK_WITHOUT_APPROVAL:
        reasons.append("Disk larger than " + str(MAX_DISK_WITHOUT_APPROVAL) + " GB")
    if len(reasons) > 0:
        route = "APPROVAL"

approver = DEPT_APPROVER.get(dept, DEFAULT_APPROVER)

# ---- identifiers ----
digits = ""
for c in str(now or "000000"):
    if c.isdigit():
        digits = digits + c
if len(digits) < 6:
    digits = (digits + "000000")[:6]
request_id = "VMR-" + digits[-6:]

owner = email.split("@")[0].replace(".", "")[:8]

# Hostname: <env>-<vm_name or os>-<owner>-<nnn>, lowercase letters, digits and hyphens only
label = ""
for c in str(vm_name or "").lower():
    if c.isalnum():
        label = label + c
    elif c in "-_ " and len(label) > 0 and label[-1] != "-":
        label = label + "-"
label = label.strip("-")[:20]
if label == "":
    label = os_short
hostname = env + "-" + label + "-" + owner + "-" + digits[-3:]

spec = type_id + " (" + str(vcpu) + " vCPU / " + str(mem) + " GB RAM, " + str(disk) + " GB disk)"
reasons_text = "; ".join(reasons)

# One row for TF_VAR_vm_requests on the Spacelift stack. "|" and ";" are the
# delimiters, so strip them out of free-text fields.
# request_id|environment|vcpu|memory_gb|disk_gb|os_image|owner|hostname|lease_days|requester_email|instance_type
row_fields = [request_id, env, str(vcpu), str(mem), str(disk), str(os_image or ""), owner,
              hostname, str(days), email, type_id]
clean_fields = []
for fv in row_fields:
    clean_fields.append(str(fv).replace("|", "-").replace(";", ","))
request_row = "|".join(clean_fields)

spacelift_stack_url = "https://" + SPACELIFT_ACCOUNT + ".app.spacelift.io/stack/" + SPACELIFT_STACK

# ---- chat messages ----
if route == "AUTO":
    route_text = "Auto-approved: within your quota and policy."
elif route == "APPROVAL":
    route_text = "Needs approval from " + approver + " because: " + reasons_text + "."
else:
    route_text = "Can't be provisioned right now. " + reasons_text + ". Try a smaller type or another environment."

summary_text = (
    "Request " + request_id + "\n"
    + "- Name: " + hostname + "\n"
    + "- Environment: " + env + "\n"
    + "- OS: " + str(os_image) + "\n"
    + "- Instance type: " + spec + (", " + family if family else "") + "\n"
    + "- Lease: " + str(days) + " days\n"
    + "- Your quota: " + str(max(remaining, 0)) + " of " + str(quota) + " vCPU left\n"
    + "- Route: " + route_text
)

approval_details = (
    str(user_name) + " (" + email + ", " + str(department) + ") is requesting a VM.\n"
    + "Name: " + hostname + "\nEnvironment: " + env + "\nOS: " + str(os_image)
    + "\nInstance type: " + spec + "\nLease: " + str(days) + " days"
    + "\nJustification: " + str(justification)
    + "\nWhy approval is needed: " + reasons_text
)

request = {
    "request_id": request_id,
    "route": route,
    "reasons": reasons,
    "requester_email": email,
    "approver_email": approver,
    "environment": env,
    "os_image": os_image,
    "instance_type": type_id,
    "vcpu": vcpu,
    "memory_gb": mem,
    "disk_gb": disk,
    "duration_days": days,
    "hostname": hostname,
    "owner": owner,
    "request_row": request_row,
    "spacelift_stack": SPACELIFT_STACK,
    "spacelift_stack_url": spacelift_stack_url,
    "summary_text": summary_text,
    "approval_title": "VM request " + request_id + ": " + type_id + " in " + env,
    "approval_details": approval_details,
    "msg_blocked": "Request " + request_id + " was not submitted. " + route_text,
    "msg_denied": "Your VM request " + request_id + " was declined by the approver. Nothing was provisioned.",
    "msg_started": "Request " + request_id + " is approved. Sending " + hostname + " (" + spec + ") to Spacelift to run Terraform...",
    "msg_failed": "The Terraform run for " + request_id + " did not finish. Nothing new is running. Details: " + spacelift_stack_url,
    "msg_timeout": "Request " + request_id + " is still running in Spacelift after 10 minutes. Track it here: " + spacelift_stack_url,
    "spec": spec,
}

request
