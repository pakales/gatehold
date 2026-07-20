import type { Metadata } from "next";
import { GateholdDashboard } from "./GateholdDashboard";

export const metadata: Metadata = {
  title: "Local clearance for coding agents",
  description:
    "See how Gatehold raises semantic workstream holds and queues heavy agent work when your local machine is under pressure.",
};

export default function Home() {
  return <GateholdDashboard />;
}
