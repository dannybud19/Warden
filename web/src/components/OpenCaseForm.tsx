"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import * as api from "@/lib/api";
import type { OpenCaseInput } from "@/lib/api";
import { STUDENT_NAME_KEY } from "@/lib/config";
import { ErrorBanner } from "@/components/ErrorBanner";

const EMPTY = {
  name: "", landlordName: "", companyName: "", companyNumber: "", url: "", address: "",
  rent: "", deposit: "", university: "", notes: "",
};
type FormState = typeof EMPTY;

/** Returns the trimmed string, or undefined when empty. */
function str(v: string): string | undefined {
  const t = v.trim();
  return t === "" ? undefined : t;
}

/** Returns a number, or undefined when empty or not numeric. */
function num(v: string): number | undefined {
  const t = v.trim();
  if (t === "") return undefined;
  const n = Number(t);
  return Number.isFinite(n) ? n : undefined;
}

/** Returns the object, or undefined if every value in it is undefined. */
function nonEmpty<T extends Record<string, unknown>>(o: T): T | undefined {
  return Object.values(o).some((v) => v !== undefined) ? o : undefined;
}

export function OpenCaseForm() {
  const router = useRouter();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof FormState) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      localStorage.setItem(STUDENT_NAME_KEY, form.name.trim());
    } catch {
      /* storage unavailable */
    }
    // NOTE: "Your name" is only stored locally; OpenCaseInput.student has no name field.
    const input: OpenCaseInput = {
      student: {
        university: str(form.university),
        notes: str(form.notes),
      },
      listing: nonEmpty({
        url: str(form.url),
        address: str(form.address),
        rent_pcm: num(form.rent),
        deposit: num(form.deposit),
      }),
      landlord: nonEmpty({
        name: str(form.landlordName),
        company_name: str(form.companyName),
        company_number: str(form.companyNumber),
      }),
    };
    try {
      const c = await api.openCase(input);
      // NOTE: if case_id is missing from the response we show an error rather than navigate.
      if (!c.case_id) throw new Error("The server did not return a case id.");
      router.push(`/case/${c.case_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={onSubmit}>
      <ErrorBanner message={error} />
      <label htmlFor="oc-name">Your name</label>
      <input id="oc-name" required value={form.name} onChange={set("name")} />
      <label htmlFor="oc-landlord">Landlord name</label>
      <input id="oc-landlord" value={form.landlordName} onChange={set("landlordName")} />
      <label htmlFor="oc-company">Agency / company name</label>
      <input id="oc-company" value={form.companyName} onChange={set("companyName")} />
      <label htmlFor="oc-number">Company number</label>
      <input id="oc-number" value={form.companyNumber} onChange={set("companyNumber")} />
      <label htmlFor="oc-url">Listing URL</label>
      <input id="oc-url" value={form.url} onChange={set("url")} />
      <label htmlFor="oc-address">Listing address</label>
      <input id="oc-address" value={form.address} onChange={set("address")} />
      <label htmlFor="oc-rent">Rent per month (£)</label>
      <input id="oc-rent" type="number" min="0" step="any" value={form.rent} onChange={set("rent")} />
      <label htmlFor="oc-deposit">Deposit (£)</label>
      <input id="oc-deposit" type="number" min="0" step="any" value={form.deposit} onChange={set("deposit")} />
      <label htmlFor="oc-uni">University</label>
      <input id="oc-uni" value={form.university} onChange={set("university")} />
      <label htmlFor="oc-notes">Notes (How are you feeling about this place? Any deadlines?)</label>
      <textarea id="oc-notes" value={form.notes} onChange={set("notes")} />
      <button type="submit" disabled={busy}>{busy ? "Opening…" : "Open case"}</button>
    </form>
  );
}
