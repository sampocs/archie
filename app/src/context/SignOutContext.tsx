import { createContext, useContext } from "react";

// Task 9 provides the real handler (clearSession); the default is a no-op so screens render standalone.
export const SignOutContext = createContext<() => void>(() => undefined);

export function useSignOut(): () => void {
  return useContext(SignOutContext);
}
