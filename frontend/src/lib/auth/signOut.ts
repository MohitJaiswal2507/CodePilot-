import { authClient } from "@/lib/auth/client";
import { clearApiAuthToken } from "@/services/api";

interface RouterLike {
  push: (href: string) => void;
  refresh: () => void;
}

export async function performSignOut(router: RouterLike): Promise<void> {
  await authClient.signOut();
  clearApiAuthToken();
  if (typeof window !== "undefined") {
    localStorage.removeItem("codepilot_session_id");
    localStorage.removeItem("codepilot_auth_token");
    localStorage.removeItem("codepilot_active_tab");
  }
  router.push("/login");
  router.refresh();
}

