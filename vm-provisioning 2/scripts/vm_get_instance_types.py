# =====================================================================
# Script Action: vm_get_instance_types       (APIthon)
# Used by: the dynamic resolver on the InstanceType data type
#
# Input args (all strings):
#   user_email   <- meta_info.user.email_addr
#   department   <- meta_info.user.department
#   environment  <- data.environment   (Strategy Mapping)
#   os_image     <- data.os_image      (Strategy Mapping)
#
# Returns the EC2 instance types this user can pick right now. Each option
# carries vCPU and memory, so the agent can match "I need 16 GB" to a type.
# Types are left out if they don't fit the environment's free capacity, are
# too small for the OS, or (on a free-plan AWS account) aren't free-tier
# eligible. Types over the user's quota are offered but flagged for approval.
# =====================================================================

# ------------------ DEMO CONFIG: keep in sync with vm_evaluate_request ------------------
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
ALLOW_QUOTA_EXCEPTIONS = True
APPROVAL_REQUIRED_DEPARTMENTS = ["contractors", "finance", "marketing"]
APPROVAL_REQUIRED_USERS = ["demo.contractor@yourco.com"]

# True while the AWS account is on the Free plan: only free-tier eligible types are offered.
# Set to False after upgrading to the Paid plan; other types then need approval (they cost money).
FREE_PLAN_ONLY = True

# The catalog. Keep it in sync with allowed_instance_types in terraform/aws/main.tf.
CATALOG = [
    {"id": "t3.micro",        "family": "Burstable",         "vcpu": 2,  "memory_gb": 1,  "free_tier": True},
    {"id": "t3.small",        "family": "Burstable",         "vcpu": 2,  "memory_gb": 2,  "free_tier": True},
    {"id": "t3.medium",       "family": "Burstable",         "vcpu": 2,  "memory_gb": 4,  "free_tier": False},
    {"id": "t3.large",        "family": "Burstable",         "vcpu": 2,  "memory_gb": 8,  "free_tier": False},
    {"id": "c7i-flex.large",  "family": "Compute optimized", "vcpu": 2,  "memory_gb": 4,  "free_tier": True},
    {"id": "m7i-flex.large",  "family": "General purpose",   "vcpu": 2,  "memory_gb": 8,  "free_tier": True},
    {"id": "m7i-flex.xlarge", "family": "General purpose",   "vcpu": 4,  "memory_gb": 16, "free_tier": False},
    {"id": "m7i.2xlarge",     "family": "General purpose",   "vcpu": 8,  "memory_gb": 32, "free_tier": False},
    {"id": "r7i.large",       "family": "Memory optimized",  "vcpu": 2,  "memory_gb": 16, "free_tier": False},
    {"id": "r7i.xlarge",      "family": "Memory optimized",  "vcpu": 4,  "memory_gb": 32, "free_tier": False},
    {"id": "m7i.4xlarge",     "family": "General purpose",   "vcpu": 16, "memory_gb": 64, "free_tier": False},
]
MIN_MEMORY_GB_WINDOWS = 2
# ----------------------------------------------------------------------------------------

email = (user_email or "").lower()
dept = (department or "").lower()
env = (environment or "dev").lower()
if env not in CLUSTER_FREE:
    env = "dev"
is_windows = "win" in (os_image or "").lower()

quota = DEPT_QUOTA_VCPU.get(dept, DEFAULT_QUOTA_VCPU)
used = CURRENT_USAGE_VCPU.get(email, DEFAULT_USAGE_VCPU)
remaining = quota - used
if remaining < 0:
    remaining = 0
cluster = CLUSTER_FREE[env]
role_needs_approval = dept in APPROVAL_REQUIRED_DEPARTMENTS or email in APPROVAL_REQUIRED_USERS

options = []
for t in CATALOG:
    if FREE_PLAN_ONLY and not t["free_tier"]:
        continue
    if is_windows and t["memory_gb"] < MIN_MEMORY_GB_WINDOWS:
        continue
    if t["vcpu"] > cluster["vcpu"] or t["memory_gb"] > cluster["memory_gb"]:
        continue
    fits_quota = t["vcpu"] <= remaining
    if not fits_quota and not ALLOW_QUOTA_EXCEPTIONS:
        continue

    needs_approval = (role_needs_approval or env == "prod" or t["vcpu"] > APPROVAL_ABOVE_VCPU
                      or not fits_quota or not t["free_tier"])
    label = t["id"] + " - " + str(t["vcpu"]) + " vCPU / " + str(t["memory_gb"]) + " GB RAM, " + t["family"]
    if t["free_tier"]:
        label = label + ", free tier"
    if not fits_quota:
        label = label + " (over your quota - needs approval)"
    elif needs_approval:
        label = label + " (needs approval)"

    options.append({
        "id": t["id"],
        "name": t["id"],
        "display_name": label,
        "family": t["family"],
        "vcpu": t["vcpu"],
        "memory_gb": t["memory_gb"],
        "free_tier": t["free_tier"],
        "needs_approval": needs_approval,
        "quota_vcpu": quota,
        "remaining_vcpu": remaining,
        "environment": env,
    })

options
