export type AppTab =
  | "dashboard"
  | "ai-tutor"
  | "code-review"
  | "sandbox"
  | "settings";

export type NavGroup = "workspace" | "preferences";

export interface NavItemConfig {
  id: AppTab;
  label: string;
  title: string;
  subtitle: string;
  group: NavGroup;
}

export const NAV_ITEMS: readonly NavItemConfig[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    title: "Overview",
    subtitle: "Workspace activity, service health, and quick actions",
    group: "workspace",
  },
  {
    id: "ai-tutor",
    label: "AI Learning Tutor",
    title: "AI Learning Tutor",
    subtitle: "Curriculum-grounded question answering and citations",
    group: "workspace",
  },
  {
    id: "code-review",
    label: "Code Reviewer",
    title: "Code Reviewer",
    subtitle: "",
    group: "workspace",
  },
  {
    id: "sandbox",
    label: "Code Sandbox",
    title: "Code Sandbox",
    subtitle: "Isolated Docker execution for Python, Java, and C++",
    group: "workspace",
  },
  {
    id: "settings",
    label: "Settings",
    title: "Settings",
    subtitle: "Account, editor defaults, AI model, and diagnostics",
    group: "preferences",
  },
] as const;

export const VALID_APP_TABS: readonly AppTab[] = NAV_ITEMS.map((item) => item.id);

export const TAB_META: Record<AppTab, NavItemConfig> = NAV_ITEMS.reduce(
  (acc, item) => {
    acc[item.id] = item;
    return acc;
  },
  {} as Record<AppTab, NavItemConfig>
);

export function isAppTab(value: string | null): value is AppTab {
  return value !== null && (VALID_APP_TABS as readonly string[]).includes(value);
}
