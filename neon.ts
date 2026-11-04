import { defineConfig } from "@neon/config/v1";

export default defineConfig({
  // Só o Postgres: a Lumio tem login próprio (JWT + argon2, isolamento por RLS),
  // então o Neon Auth não é usado.
  // Branch policy: per-branch tuning
  branch: (branch) => {
    if (branch.isDefault) {
      // Default branch: no overrides, uses project defaults
      return {};
    }
    if (!branch.exists) {
      // New non-default branches: auto-expire
      // Run `neon checkout <name>` to create a new branch with these settings
      return { ttl: "7d" };
    }
    // Existing branch: no changes
    return {};
  },
});
