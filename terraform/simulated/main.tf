# Simulated VMs: real Terraform, real Spacelift runs, no cloud account needed.
#
# The stack holds ALL current VM requests in one variable, TF_VAR_vm_requests:
#   rows separated by ";", fields separated by "|", in this order:
#   request_id|environment|vcpu|memory_gb|disk_gb|os_image|owner|hostname|lease_days|requester_email
# Moveworks adds a row to provision and removes a row to delete; Terraform does the rest.
# "none" means no VMs.

terraform {
  required_version = ">= 1.4"
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

variable "vm_requests" {
  type    = string
  default = "none"
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
    }
  }
}

resource "random_integer" "octet3" {
  for_each = local.vms
  min      = 1
  max      = 250
}

resource "random_integer" "octet4" {
  for_each = local.vms
  min      = 2
  max      = 250
}

resource "random_id" "instance" {
  for_each    = local.vms
  byte_length = 6
}

# Stands in for the hypervisor. The sleeps make each create/delete take long enough to watch.
resource "terraform_data" "vm" {
  for_each = local.vms
  input    = merge(each.value, { request_id = each.key })

  provisioner "local-exec" {
    command = <<-EOT
      echo "Allocating ${each.value.vcpu} vCPU / ${each.value.memory_gb} GB in ${each.value.environment}..."
      sleep 20
      echo "Installing ${each.value.os_image}, attaching ${each.value.disk_gb} GB disk..."
      sleep 20
      echo "Registering ${each.value.hostname} for ${each.value.requester_email}..."
      sleep 10
      echo "Done."
    EOT
  }

  provisioner "local-exec" {
    when    = destroy
    command = "echo 'Shutting down ${self.input.hostname}...'; sleep 15; echo 'Released.'"
  }
}

# One line per VM: request_id|hostname|ip|instance_id|requester_email|environment|instance_type|os_image
output "vm_inventory" {
  value = join(";", [
    for k, v in local.vms : join("|", [
      k,
      v.hostname,
      "10.${lookup({ dev = 10, test = 20, prod = 30 }, v.environment, 99)}.${random_integer.octet3[k].result}.${random_integer.octet4[k].result}",
      "vm-${random_id.instance[k].hex}",
      v.requester_email,
      v.environment,
      "sim-${v.vcpu}cpu-${v.memory_gb}gb",
      v.os_image,
    ])
  ])
}

output "vm_count" {
  value = length(local.vms)
}
