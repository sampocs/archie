import { useRouter } from "expo-router";

import { Screen } from "@/theme/components/Screen";

/** Shell: Task 11 fills the body. */
export default function PractiseTopicScreen() {
  const router = useRouter();

  return <Screen title="Practise a topic" onBack={router.back}>{null}</Screen>;
}
