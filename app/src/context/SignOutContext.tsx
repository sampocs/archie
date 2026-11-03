import { createContext, useContext } from "react";

// The app root provides the real handler (clearSession); the default is a no-op so screens render standalone.
export const SignOutContext = createContext<() => void>(() => undefined);

export function useSignOut(): () => void {
  return useContext(SignOutContext);
}
