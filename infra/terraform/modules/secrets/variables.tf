variable "name_prefix" {
  description = "Prefix for Secrets Manager secret names, e.g. \"kureha/prod\"."
  type        = string
}

variable "recovery_window_in_days" {
  description = "Secrets Manager deletion recovery window. 0 force-deletes on destroy (only sane for throwaway/test environments)."
  type        = number
  default     = 7
}

variable "tags" {
  type    = map(string)
  default = {}
}
