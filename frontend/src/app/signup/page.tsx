import { redirect } from "next/navigation";

export const instant = false;

export default function SignUpPage() {
  redirect("/sign-up");
}
