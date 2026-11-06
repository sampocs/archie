import { useRouter } from "expo-router";

import { Screen } from "@/theme/components/Screen";

/** Shell: Task 13 fills the body. */
export default function ReviewSettingsScreen() {
  const router = useRouter();

  return <Screen title="Review reminder" onBack={router.back}>{null}</Screen>;
}
