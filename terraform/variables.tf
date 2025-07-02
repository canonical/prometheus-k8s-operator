variable "app_name" {
  description = "Application name"
  type        = string
}

variable "channel" {
  description = "Charm channel"
  type        = string
  default     = "latest/stable"
}

variable "config" {
  description = "Config options as in the ones we pass in juju config"
  type        = map(string)
  default     = {}
}

# We use constraints to set AntiAffinity in K8s
# https://discourse.charmhub.io/t/pod-priority-and-affinity-in-juju-charms/4091/13?u=jose
variable "constraints" {
  description = "Constraints to be applied"
  type        = string
  default     = ""
}

variable "model_name" {
  description = "Model name"
  type        = string
}

variable "revision" {
  description = "Charm revision"
  type        = number
  nullable    = true
  default     = null
}

variable "units" {
  description = "Number of units"
  type        = number
  default     = 1
}