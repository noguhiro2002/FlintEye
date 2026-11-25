export type SettingsTier = "basic" | "advanced";

export type SettingsSection =
  | "cameras" | "recording" | "multiview" | "runtime"
  | "general" | "mediamtx" | "logging" | "integrations" | "advanced";

export interface SettingsTarget {
  section: SettingsSection;
  tier?: SettingsTier;
  anchor?: string;
}
