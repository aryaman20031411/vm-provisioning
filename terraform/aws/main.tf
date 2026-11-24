# Real VMs on AWS EC2, the simplest possible setup:
#   - the stack holds ALL current VM requests in TF_VAR_vm_requests (same format as ../simulated):
#     request_id|environment|vcpu|memory_gb|disk_gb|os_image|owner|hostname|lease_days|requester_email
#     rows separated by ";". "none" means no VMs. Moveworks adds/removes rows.
#   - uses the account's DEFAULT VPC and subnet, so there's no network to build
#   - cost_saver = true (default) launches every VM as a t3.micro and records the
#     size that was asked for in the tags. Set TF_VAR_cost_saver=false for real sizes.
#
# Credentials: attach a Spacelift AWS integration (an IAM role) to the stack. No keys.

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

variable "cost_saver" {
  type    = bool
  default = true
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
      is_windows      = length(regexall("(?i)windows", f[5])) > 0
      is_rhel         = length(regexall("(?i)rhel|red hat", f[5])) > 0
    }
  }

  real_types = {
    "2-8"   = "m7i-flex.large"
    "4-16"  = "m7i.xlarge"
    "8-32"  = "m7i.2xlarge"
    "16-64" = "m7i.4xlarge"
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
  instance_type               = var.cost_saver ? "t3.micro" : lookup(local.real_types, "${each.value.vcpu}-${each.value.memory_gb}", "m7i-flex.large")
  subnet_id                   = sort(data.aws_subnets.default.ids)[0]
  associate_public_ip_address = true

  root_block_device {
    volume_size = var.cost_saver ? (each.value.is_windows ? 30 : 8) : each.value.disk_gb
    volume_type = "gp3"
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  tags = {
    Name           = each.value.hostname
    RequestId      = each.key
    Environment    = each.value.environment
    Owner          = each.value.requester_email
    LeaseDays      = tostring(each.value.lease_days)
    RequestedSize  = "${each.value.vcpu} vCPU / ${each.value.memory_gb} GB / ${each.value.disk_gb} GB disk"
    ManagedBy      = "moveworks-spacelift"
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
