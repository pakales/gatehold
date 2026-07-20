import type { Metadata } from "next";
import { GateholdDashboard } from "./GateholdDashboard";

export const metadata: Metadata = {
  title: "Gatehold — Local clearance for parallel coding agents",
  description:
    "Two keys to start. Verified cleanup to release. Prevent overlapping work before cooperative coding agents share one machine.",
};

export default function Home() {
  return <GateholdDashboard />;
}
