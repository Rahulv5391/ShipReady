"use server";

import { redirect } from "next/navigation";

import { apiUrl } from "@/lib/api";
import { saveSession } from "@/lib/session";

export type SignInState = { error: string; email: string } | undefined;

type LoginAnswer = {
  access_token: string;
  expires_at: string;
  user: { email: string; name: string; org_id: string };
};

/** Signs in with the API (POST /auth/login) and keeps its token in the session cookies. */
export async function signIn(_: SignInState, form: FormData): Promise<SignInState> {
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "");
  if (!email || !password) {
    return { error: "Enter your work email and password.", email };
  }
  let response: Response;
  try {
    response = await fetch(apiUrl("/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, remember: form.get("remember") === "on" }),
      cache: "no-store",
    });
  } catch {
    return { error: "ShipReady can't be reached right now. Try again in a minute.", email };
  }
  if (response.status === 401) {
    return { error: "That email and password don't match. Check both and try again.", email };
  }
  if (!response.ok) {
    return { error: "Signing in didn't work. Try again in a minute.", email };
  }
  const answer = (await response.json()) as LoginAnswer;
  await saveSession(answer.access_token, new Date(answer.expires_at), {
    email: answer.user.email,
    name: answer.user.name,
    orgId: answer.user.org_id,
  });
  redirect("/shipments");
}
