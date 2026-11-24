# Real VMs on AWS EC2.
#   - The stack holds ALL current VM requests in TF_VAR_vm_requests, rows separated by ";":
#     request_id|environment|vcpu|memory_gb|disk_gb|os_image|owner|hostname|lease_days|requester_email|instance_type
#     "none" means no VMs. Moveworks adds/removes rows.
#   - Each VM launches as the instance type the user picked, if it's on allowed_instance_types.
#   - Uses the account's DEFAULT VPC and subnet, so there's no network to build.
#
# Credentials: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION as stack environment
# variables (or a Spacelift AWS integration, if your AWS account allows it).

terraform {
  required_version = ">= 1.4"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "vm_requests" {
  type    = string
  default = "none"
}

variable "region" {
  type    = string
  default = "us-east-2"
}

# Must match the CATALOG in scripts/vm_get_instance_types.py.
variable "allowed_instance_types" {
  type = list(string)
  default = [
    "t3.micro", "t3.small", "t3.medium", "t3.large",
    "c7i-flex.large", "m7i-flex.large", "m7i-flex.xlarge", "m7i.2xlarge",
    "r7i.large", "r7i.xlarge", "m7i.4xlarge",
  ]
}

locals {
  rows = [for r in split(";", var.vm_requests) : split("|", r) if length(split("|", r)) >= 10]
  vms = {
    for f in local.rows : f[0] => {
      environment     = f[1]
      vcpu            = tonumber(f[2])
      memory_gb       = tonumber(f[3])
      disk_gb         = tonumber(f[4])
      os_image        = f[5]
      owner           = f[6]
      hostname        = f[7]
      lease_days      = tonumber(f[8])
      requester_email = f[9]
      instance_type   = coalesce(try(f[10], ""), "t3.micro")
      is_windows      = length(regexall("(?i)windows", f[5])) > 0
      is_rhel         = length(regexall("(?i)rhel|red hat", f[5])) > 0
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd*/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

data "aws_ami" "rhel" {
  most_recent = true
  owners      = ["309956199498"] # Red Hat
  filter {
    name   = "name"
    values = ["RHEL-9.*_HVM-*-x86_64-*"]
  }
}

data "aws_ami" "windows" {
  most_recent = true
  owners      = ["801119661308"] # Amazon
  filter {
    name   = "name"
    values = ["Windows_Server-2022-English-Full-Base-*"]
  }
}

resource "aws_instance" "vm" {
  for_each = local.vms

  ami                         = each.value.is_windows ? data.aws_ami.windows.id : (each.value.is_rhel ? data.aws_ami.rhel.id : data.aws_ami.ubuntu.id)
  instance_type               = each.value.instance_type
  subnet_id                   = sort(data.aws_subnets.default.ids)[0]
  associate_public_ip_address = true

  root_block_device {
    volume_size = each.value.is_windows ? max(each.value.disk_gb, 30) : max(each.value.disk_gb, 8)
    volume_type = "gp3"
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  tags = {
    Name        = each.value.hostname
    RequestId   = each.key
    Environment = each.value.environment
    Owner       = each.value.requester_email
    LeaseDays   = tostring(each.value.lease_days)
    ManagedBy   = "moveworks-spacelift"
  }

  lifecycle {
    precondition {
      condition     = contains(var.allowed_instance_types, each.value.instance_type)
      error_message = "Instance type ${each.value.instance_type} (request ${each.key}) is not in allowed_instance_types."
    }
  }
}

# One line per VM: request_id|hostname|ip|instance_id|requester_email|environment|instance_type|os_image
output "vm_inventory" {
  value = join(";", [
    for k, v in local.vms : join("|", [
      k,
      v.hostname,
      aws_instance.vm[k].public_ip,
      aws_instance.vm[k].id,
      v.requester_email,
      v.environment,
      aws_instance.vm[k].instance_type,
      v.os_image,
    ])
  ])
}

output "vm_count" {
  value = length(local.vms)
}
