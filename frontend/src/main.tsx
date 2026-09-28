import { StrictMode, lazy } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./index.css";
import AppShell from "./app/AppShell";
import { RouteError } from "./app/RouteError";

const Landing = lazy(() => import("./pages/Landing"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Monitor = lazy(() => import("./pages/Monitor"));
const Anomalies = lazy(() => import("./pages/Anomalies"));
const Investigation = lazy(() => import("./pages/Investigation"));
const Alerts = lazy(() => import("./pages/Alerts"));
const Logs = lazy(() => import("./pages/Logs"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Services = lazy(() => import("./pages/Services"));
const ServiceDetail = lazy(() => import("./pages/ServiceDetail"));
const Aws = lazy(() => import("./pages/Aws"));
const Projects = lazy(() => import("./pages/Projects"));
const Team = lazy(() => import("./pages/Team"));
const Settings = lazy(() => import("./pages/Settings"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 },
  },
});

const router = createBrowserRouter([
  { path: "/", element: <Landing />, errorElement: <RouteError /> },
  {
    path: "/app",
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "monitor", element: <Monitor /> },
      { path: "anomalies", element: <Anomalies /> },
      { path: "anomalies/:id", element: <Investigation /> },
      { path: "alerts", element: <Alerts /> },
      { path: "logs", element: <Logs /> },
      { path: "analytics", element: <Analytics /> },
      { path: "services", element: <Services /> },
      { path: "services/:name", element: <ServiceDetail /> },
      { path: "aws", element: <Aws /> },
      { path: "projects", element: <Projects /> },
      { path: "team", element: <Team /> },
      { path: "settings", element: <Settings /> },
    ],
  },
  { path: "*", element: <RouteError notFound /> },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
