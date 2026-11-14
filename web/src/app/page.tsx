import { OpenCaseForm } from "@/components/OpenCaseForm";

export default function Home() {
  return (
    <main className="page">
      <p>Open a case for a property you&apos;re talking to an agent about.</p>
      <OpenCaseForm />
    </main>
  );
}
