import { useLocalSearchParams, useRouter } from "expo-router";

import { Screen } from "@/theme/components/Screen";

/** Shell: `mode` is due | ahead | topic | quiz | card; `id` is the topic or card. Task 10 fills the body. */
export default function ReviewSessionScreen() {
  const router = useRouter();
  useLocalSearchParams<{ mode?: string; id?: string }>();

  return <Screen title="Review" onBack={router.back}>{null}</Screen>;
}
